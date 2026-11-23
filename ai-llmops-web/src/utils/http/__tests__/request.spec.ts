import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// =========================
//  Mock 依赖：Message / Pinia store / router
// =========================
vi.mock('@arco-design/web-vue', () => ({
  Message: { error: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

vi.mock('@/stores/credential.ts', () => ({
  useCredentialStore: () => ({
    credential: { access_token: '' },
    clear: vi.fn(),
  }),
}))

vi.mock('@/router', () => ({
  default: { replace: vi.fn() },
}))

import { Message } from '@arco-design/web-vue'
import request from '@/utils/http/request'
import { showErrorToast } from '@/utils/http/error'

describe('request 错误提示（单次请求不应重复弹窗）', () => {
  // 每个用例使用递增的假时钟，使上一个用例写入的去重记录过期，保证用例隔离
  let fakeNow = 0

  beforeEach(() => {
    fakeNow += 10000
    vi.useFakeTimers()
    vi.setSystemTime(fakeNow)
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('HTTP 500 无业务消息时，请求层与调用方 catch 重复展示的兜底文案只弹一次', async () => {
    // 后端返回 500 且 body 是 HTML 错误页/空 -> 请求层兜底文案（见 request.ts 的 502/503/504 分支之外一支）
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        headers: { get: () => 'text/html' },
        text: vi.fn().mockResolvedValue(''),
        json: vi.fn(),
      }),
    )

    // 模拟调用方（如 AuthorizeView.vue）catch 后再展示 err.message 的写法
    try {
      await request('/some/api')
    } catch (err) {
      showErrorToast(err instanceof Error ? err.message : String(err))
    }

    // 请求层 + 调用方各触发一次展示，但同文案去重后只弹一条
    expect(Message.error).toHaveBeenCalledTimes(1)
    expect(Message.error).toHaveBeenCalledWith('服务器异常，请稍后重试')
  })

  it('不同错误文案各自弹出一次，不做过度合并', async () => {
    // 第一次：500 -> 兜底文案
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce({
        ok: false,
        status: 500,
        headers: { get: () => 'text/html' },
        text: vi.fn().mockResolvedValue(''),
        json: vi.fn(),
      }),
    )
    try {
      await request('/a')
    } catch (err) {
      showErrorToast(err instanceof Error ? err.message : String(err))
    }

    // 第二次：后端返回业务错误文案
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce({
        ok: false,
        status: 400,
        headers: { get: () => 'application/json' },
        json: vi.fn().mockResolvedValue({ message: '参数不合法' }),
        text: vi.fn(),
      }),
    )
    try {
      await request('/b')
    } catch (err) {
      showErrorToast(err instanceof Error ? err.message : String(err))
    }

    expect(Message.error).toHaveBeenCalledTimes(2)
    expect(Message.error).toHaveBeenNthCalledWith(1, '服务器异常，请稍后重试')
    expect(Message.error).toHaveBeenNthCalledWith(2, '参数不合法')
  })

  it('去重窗口过后，相同文案再次出现时仍会弹出', () => {
    showErrorToast('服务器错误')
    showErrorToast('服务器错误')
    expect(Message.error).toHaveBeenCalledTimes(1)

    // 窗口（3s）过后相同文案再次出现 -> 重新弹出
    vi.setSystemTime(fakeNow + 10000)
    showErrorToast('服务器错误')
    expect(Message.error).toHaveBeenCalledTimes(2)
  })
})
