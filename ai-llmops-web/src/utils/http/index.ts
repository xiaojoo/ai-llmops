import request from './request'
import { xhrUpload } from '@/utils/http/xhrUpload'

// 支持泛型返回和请求 body
export const http = {
  get<T>(url: string, params?: Record<string, string | number | boolean>) {
    const query = params ? `?${new URLSearchParams(params as Record<string, string>)}` : ''
    return request<T>(url + query, { method: 'GET' })
  },

  post<T, B = unknown>(url: string, body?: B) {
    return request<T>(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    })
  },

  put<T, B = unknown>(url: string, body?: B) {
    return request<T>(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    })
  },

  delete<T, B = unknown>(url: string, body?: B) {
    return request<T>(url, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    })
  },
}

// xhr上传文件
export const httpUpload = {
  post<T>(url: string, formData: FormData, options?: Parameters<typeof xhrUpload<T>>[2]) {
    return xhrUpload<T>(url, formData, options)
  },
}
