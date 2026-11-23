import { apiPrefix, httpCode } from '@/config'
import type { ApiErrorResponse } from './error'
import { errorAdapter, globalErrorHandler, HttpError } from './error'
import { getAccessToken } from './auth'

const TIME_OUT = 150000

export interface XhrUploadOptions {
  headers?: Record<string, string>
  withCredentials?: boolean
  timeout?: number
  onProgress?: (percent: number, event: ProgressEvent<EventTarget>) => void
}

/**
 * XHR 文件上传（支持进度）
 */
export function xhrUpload<T = unknown>(
  url: string,
  formData: FormData,
  options: XhrUploadOptions = {},
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()

    const normalizedUrl = url.startsWith('/') ? url : `/${url}`
    const fullUrl = `${apiPrefix}${normalizedUrl}`

    xhr.open('POST', fullUrl, true)

    xhr.timeout = options.timeout ?? TIME_OUT
    xhr.withCredentials = !!options.withCredentials

    // 设置请求头（不要手动设置 Content-Type）
    if (options.headers) {
      Object.entries(options.headers).forEach(([key, value]) => {
        xhr.setRequestHeader(key, value)
      })
    }

    // ===== 添加认证信息 =====
    const accessToken = getAccessToken()
    if (accessToken) {
      xhr.setRequestHeader('Authorization', `Bearer ${accessToken}`)
    }

    // 上传进度
    if (xhr.upload && options.onProgress) {
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          const percent = Math.round((event.loaded / event.total) * 100)
          options.onProgress?.(percent, event)
        }
      }
    }

    xhr.onload = () => {
      try {
        const contentType = xhr.getResponseHeader('Content-Type') || ''
        let parsed: ApiErrorResponse<T> | T | string

        if (contentType.includes('application/json')) {
          parsed = JSON.parse(xhr.responseText)
        } else {
          parsed = xhr.responseText
        }

        // HTTP 状态错误
        if (xhr.status < 200 || xhr.status >= 300) {
          throw new HttpError(
            typeof parsed === 'object' && parsed !== null && 'message' in parsed
              ? (parsed as ApiErrorResponse<T>).message || '服务器错误'
              : String(parsed),
            xhr.status,
          )
        }

        // 业务错误判断
        if (typeof parsed === 'object' && parsed !== null && 'code' in parsed) {
          const code = (parsed as ApiErrorResponse<T>).code
          if (code === undefined || code !== httpCode.success) {
            throw errorAdapter(parsed as ApiErrorResponse<T>)
          }
          resolve(parsed as T)
          return
        }

        resolve(parsed as T)
      } catch (err) {
        const httpErr = err instanceof HttpError ? err : new HttpError((err as Error).message)
        globalErrorHandler(httpErr)
        reject(httpErr)
      }
    }

    xhr.onerror = () => {
      const err = new HttpError('网络错误或跨域失败')
      globalErrorHandler(err)
      reject(err)
    }

    xhr.ontimeout = () => {
      const err = new HttpError('请求超时')
      globalErrorHandler(err)
      reject(err)
    }

    xhr.send(formData)
  })
}
