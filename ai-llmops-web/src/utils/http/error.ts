// =========================
//   统一错误模型
// =========================
import { Message } from '@arco-design/web-vue'

// 同一错误文案在短时间窗口内去重：请求层(globalErrorHandler)与调用方 catch
// 经常对同一次失败重复展示同一条消息（如“服务器错误”连续弹出两次），
// 通过按文案去重让它们合并为一条。
const RECENT_ERROR_TOAST_WINDOW_MS = 3000
const recentErrorToasts = new Map<string, number>()

export function showErrorToast(text: string) {
  const now = Date.now()
  // 清理过期记录，防止 Map 无限增长
  for (const [key, ts] of recentErrorToasts) {
    if (now - ts >= RECENT_ERROR_TOAST_WINDOW_MS) recentErrorToasts.delete(key)
  }
  if (recentErrorToasts.has(text)) return
  recentErrorToasts.set(text, now)
  Message.error(text)
}

export class HttpError<T = unknown> extends Error {
  code?: string | number
  status?: number
  data?: T

  constructor(message: string, status?: number, code?: string | number, data?: T) {
    super(message)
    this.status = status
    this.code = code
    this.data = data
  }
}

// =========================
//   Response Adapter
// =========================
export interface ApiErrorResponse<T = unknown> {
  code?: number | string
  message?: string
  msg?: string
  data?: T
}

export function errorAdapter<T = unknown>(res: ApiErrorResponse<T>): HttpError<T> {
  return new HttpError<T>(res.message || res.msg || '未知错误', undefined, res.code, res.data)
}

// =========================
//    全局错误处理器
// =========================
export function globalErrorHandler<T>(err: HttpError<T>) {
  void err
  const msg = err.message

  if (!msg) {
    // 无有效错误信息时兜底
    showErrorToast('服务器异常，请稍后重试！！！')
  } else if (msg === 'Failed to fetch') {
    showErrorToast('网络连接失败，请检查网络后重试')
  } else {
    // 展示真实错误信息（业务错误如"账号不存在或者密码错误"、后端 5xx 错误信息等）
    showErrorToast(msg)
  }
}
