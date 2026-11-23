import type { ApiErrorResponse } from './error'
import { errorAdapter, globalErrorHandler, HttpError } from './error'
import { apiPrefix, httpCode } from '@/config'
import { useCredentialStore } from '@/stores/credential.ts'
import router from '@/router'

const TIME_OUT = 150000

// =========================
//   Fetch 超时封装
// =========================
const fetchWithTimeout = async (
  url: string,
  options: RequestInit,
  timeout = TIME_OUT,
): Promise<Response> => {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeout)

  try {
    return await fetch(url, { ...options, signal: controller.signal })
  } finally {
    clearTimeout(timer)
  }
}

// =========================
//   响应处理逻辑
// =========================
async function handleResponse<T>(res: Response): Promise<T> {
  const contentType = res.headers.get('Content-Type') || ''
  let parsed: ApiErrorResponse<T> | T | string

  if (contentType.includes('application/json')) {
    parsed = await res.json()
  } else {
    parsed = (await res.text()) as string
  }

  // HTTP 层错误
  if (!res.ok) {
    let message: string
    if (typeof parsed === 'object' && parsed !== null && 'message' in parsed) {
      message = (parsed as ApiErrorResponse<T>).message || `请求失败（${res.status}）`
    } else {
      const raw = String(parsed ?? '').trim()
      // nginx/网关返回的 HTML 错误页（502/504 等）不进弹框，替换为简短提示
      const isHtml = contentType.includes('text/html') || raw.startsWith('<')
      if (isHtml || raw === '') {
        message =
          res.status === 502 || res.status === 503 || res.status === 504
            ? '服务暂不可用，请稍后重试'
            : '服务器异常，请稍后重试'
      } else {
        message = raw
      }
    }
    throw new HttpError(message || '服务器错误', res.status)
  }

  // 类型保护：判断是否是 ApiErrorResponse<T>
  function isApiErrorResponse(obj: unknown): obj is ApiErrorResponse<T> {
    return typeof obj === 'object' && obj !== null && 'code' in obj
  }

  if (isApiErrorResponse(parsed)) {
    const code = parsed.code
    if (code === undefined || code !== httpCode.success) {
      throw errorAdapter(parsed)
    }
    return parsed as T
  }

  return parsed as T
}

// =========================
//   默认导出 request()
// =========================
export default async function request<T>(url: string, config: RequestInit = {}): Promise<T> {
  const credentialStore = useCredentialStore()
  const { credential, clear: clearCredential } = credentialStore

  try {
    // 拼接统一前缀
    const normalizedUrl = url.startsWith('/') ? url : `/${url}`
    const fullUrl = `${apiPrefix}${normalizedUrl}`

    // ===== 注入 Authorization =====
    const headers = new Headers(config.headers)

    if (credential?.access_token) {
      headers.set('Authorization', `Bearer ${credential.access_token}`)
    }

    const res = await fetchWithTimeout(fullUrl, {
      ...config,
      headers,
    })
    return await handleResponse<T>(res)
  } catch (err) {
    const httpErr = err instanceof HttpError ? err : new HttpError((err as Error).message)

    // ===== token 失效统一处理 =====
    if (httpErr.status === 401) {
      clearCredential()
      // 跳转登录页
      await router.replace('/auth/login')
    }
    globalErrorHandler(httpErr)
    throw httpErr
  }
}
