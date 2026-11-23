import { apiPrefix } from '@/config'
import type { ApiErrorResponse } from './error'
import { globalErrorHandler, HttpError } from './error'
import { getAccessToken } from './auth'

// ==========================================
// ==========================================

/**
 * SSE 事件结构
 * @template T 数据载荷的类型
 */
export interface SseEvent<T> {
  event: string
  data: T
  id?: string
  retry?: number
}

/**
 * 流式请求配置项
 * @template B 请求体 (Body) 的类型
 * @template R 响应数据 (Response Data) 的类型
 */
export interface StreamRequestOptions<B, R> {
  url: string
  /** 请求方法：SSE 断流续传端点是 GET（无请求体），默认 POST */
  method?: 'POST' | 'GET'
  /** 请求体参数 */
  body?: B
  /** 请求头 (使用标准 HeadersInit 类型) */
  headers?: HeadersInit
  /** 控制器信号，用于取消请求 */
  signal?: AbortSignal

  /**
   * 收到消息时的回调
   * @param data 解析后的数据
   * @param event 完整的事件对象
   */
  onMessage?: (data: R, event: SseEvent<R>) => void

  /** 连接建立成功回调 */
  onOpen?: () => void

  /** 流式传输结束回调 */
  onFinish?: () => void

  /** 发生错误时的回调 */
  onError?: (err: HttpError) => void
}

// ==========================================
// ==========================================

/**
 * 严格类型的流式请求封装 (SSE over POST)
 */
export async function stream<B, R>(
  options: StreamRequestOptions<B, R>,
): Promise<void | ApiErrorResponse> {
  const { url, method = 'POST', body, headers, signal, onMessage, onOpen, onFinish, onError } = options

  const normalizedUrl = url.startsWith('/') ? url : `/${url}`
  const fullUrl = `${apiPrefix}${normalizedUrl}`
  const accessToken = getAccessToken()

  try {
    const requestInit: RequestInit = {
      method,
      headers: {
        // GET（SSE 续传）不能带 Content-Type，也不能带 body
        ...(method === 'POST' ? { 'Content-Type': 'application/json' } : {}),
        Accept: 'text/event-stream',
        // 'X-Requested-With': 'XMLHttpRequest',
        // ===== 认证信息 =====
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        ...headers,
      },
      body: method === 'POST' && body ? JSON.stringify(body) : undefined,
      signal,
    }

    const response = await fetch(fullUrl, requestInit)

    if (!response.ok) {
      const contentType = response.headers.get('Content-Type') || ''
      let errorMessage = `HTTP Error ${response.status}`

      // 尝试读取错误信息
      try {
        if (contentType.includes('application/json')) {
          // 使用 unknown 进行类型收窄
          const errorRes: unknown = await response.json()
          if (isApiErrorResponse(errorRes)) {
            errorMessage = errorRes.message || errorRes.msg || errorMessage
          }
        } else {
          errorMessage = await response.text()
        }
      } catch {
        // 忽略解析错误，使用默认状态码信息
      }

      throw new HttpError(errorMessage, response.status)
    }

    const contentType = response.headers.get('Content-Type') || ''

    if (contentType.includes('application/json')) {
      const json = await response.json()
      if (isApiErrorResponse(json)) {
        return json
      }
      throw new HttpError('Unexpected JSON response')
    }

    if (!contentType.includes('text/event-stream')) {
      throw new HttpError(`Unexpected Content-Type: ${contentType}`)
    }

    if (!response.body) {
      throw new HttpError('Response body is empty')
    }

    onOpen?.()

// 初始化流读取器 (明确类型)
    const reader: ReadableStreamDefaultReader<Uint8Array> = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''

    while (true) {
      const result: ReadableStreamReadResult<Uint8Array> = await reader.read()
      const { done, value } = result

      if (done) {
        break
      }

      // value 是 Uint8Array，解码为 string
      const chunk = decoder.decode(value, { stream: true })
      buffer += chunk

      // 处理粘包：以双换行符分隔
      const lines = buffer.split('\n\n')

      // 最后一个片段可能不完整，保留到下一次
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        if (!line.trim()) continue

        const message = parseSSEMessage<R>(line)

        if (message) {
          onMessage?.(message.data, message)
        }
      }
    }

    if (buffer.trim()) {
      const message = parseSSEMessage<R>(buffer)
      if (message) {
        onMessage?.(message.data, message)
      }
    }

    onFinish?.()
  } catch (error: unknown) {
// 错误处理 (使用 unknown 类型守卫)

    // 处理手动取消 (AbortError)
    if (error instanceof Error && error.name === 'AbortError') {
      onFinish?.()
      return
    }

    const httpError =
      error instanceof HttpError
        ? error
        : new HttpError(error instanceof Error ? error.message : String(error))

    if (onError) {
      onError(httpError)
    } else {
      globalErrorHandler(httpError)
    }
  }
}

// ==========================================
// ==========================================

/**
 * 判断是否为 ApiErrorResponse 结构的类型守卫
 */
function isApiErrorResponse(obj: unknown): obj is ApiErrorResponse {
  return typeof obj === 'object' && obj !== null && ('message' in obj || 'msg' in obj)
}

/**
 * SSE 解析器
 * 严格处理泛型 R
 */
function parseSSEMessage<R>(chunk: string): SseEvent<R> | null {
  // 使用 Partial 临时构建对象，避免初始化的类型报错
  const eventData: Partial<SseEvent<R>> = {
    event: 'message',
  }

  const lines = chunk.split('\n')
  let rawDataString = ''

  for (const line of lines) {
    if (line.startsWith('data:')) {
      rawDataString = line.substring(5).trim()
    } else if (line.startsWith('event:')) {
      eventData.event = line.substring(6).trim()
    } else if (line.startsWith('id:')) {
      eventData.id = line.substring(3).trim()
    } else if (line.startsWith('retry:')) {
      const retry = parseInt(line.substring(6).trim(), 10)
      if (!isNaN(retry)) {
        eventData.retry = retry
      }
    }
  }

  // 如果没有数据行，通常不是有效的业务消息
  if (!rawDataString && !eventData.event) {
    return null
  }

  // 数据解析逻辑
  try {
    // 尝试解析 JSON
    // 注意：这里我们需要断言 JSON.parse 的结果符合 R 类型
    // 在运行时无法完全保证 R 的结构，这依赖于调用者的契约
    eventData.data = JSON.parse(rawDataString) as R
  } catch {
    // 如果解析 JSON 失败（比如是普通字符串），则回退
    // 如果 R 本身是 string，这里也是安全的
    eventData.data = rawDataString as unknown as R
  }

  // 必须确保 data 存在（根据 SSE 规范，data 可能为空字符串，但也算存在）
  if (eventData.data === undefined) {
    // 如果只有 event 没有 data，视业务需求决定是否返回
    // 这里为了严谨，如果没有解析出 data，我们返回 null
    // 或者你可以给一个默认值
    return null
  }

  return eventData as SseEvent<R>
}
