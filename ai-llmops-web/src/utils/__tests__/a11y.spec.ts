import { afterEach, describe, expect, it, vi } from 'vitest'
import { fixA11y, setupA11yAutoFix } from '@/utils/a11y'

/**
 * jsdom 中所有元素的 getBoundingClientRect 都是 0×0，无法反映真实布局。
 * 这里按"祖先带 data-hidden（模拟 v-show 隐藏区块）"返回 0×0，其余返回 32×32，
 * 以此模拟可见/隐藏两种尺寸状态。
 */
function stubRects(): void {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    return this.closest('[data-hidden]')
      ? { width: 0, height: 0, top: 0, left: 0, right: 0, bottom: 0, x: 0, y: 0, toJSON: () => ({}) }
      : { width: 32, height: 32, top: 0, left: 0, right: 32, bottom: 32, x: 0, y: 0, toJSON: () => ({}) }
  })
}

afterEach(() => {
  vi.restoreAllMocks()
  document.body.innerHTML = ''
})

describe('fixA11y 隐藏辅助控件标记', () => {
  it('Arco InputTag 真实输入框即使处于隐藏区块且无名，也不标记 aria-hidden（回归：聚焦告警）', () => {
    stubRects()
    document.body.innerHTML = `
      <div data-hidden>
        <input class="arco-input-tag-input" />
      </div>
    `
    fixA11y(document)

    const input = document.querySelector<HTMLInputElement>('.arco-input-tag-input')!
    expect(input.hasAttribute('aria-hidden')).toBe(false)
    expect(input.getAttribute('tabindex')).not.toBe('-1')
  })

  it('Arco InputTag 可见输入框不标记 aria-hidden', () => {
    stubRects()
    document.body.innerHTML = `<input class="arco-input-tag-input" />`
    fixA11y(document)

    const input = document.querySelector<HTMLInputElement>('.arco-input-tag-input')!
    expect(input.hasAttribute('aria-hidden')).toBe(false)
  })

  it('Arco Select 隐藏值载体（0 尺寸且无名）仍被移出无障碍树与 Tab 顺序', () => {
    stubRects()
    document.body.innerHTML = `
      <div data-hidden>
        <input class="arco-select-view-input-hidden" />
      </div>
    `
    fixA11y(document)

    const input = document.querySelector<HTMLInputElement>('.arco-select-view-input-hidden')!
    expect(input.getAttribute('aria-hidden')).toBe('true')
    expect(input.getAttribute('tabindex')).toBe('-1')
  })

  it('已标记控件恢复尺寸后自愈：清除残留 aria-hidden 与 tabindex=-1', () => {
    stubRects()
    document.body.innerHTML = `
      <div data-hidden id="wrap">
        <input class="arco-select-view-input-hidden" />
      </div>
    `
    fixA11y(document)

    const input = document.querySelector<HTMLInputElement>('.arco-select-view-input-hidden')!
    expect(input.getAttribute('aria-hidden')).toBe('true')

    // 模拟 v-show 重新显示：去掉隐藏标记后再次修复
    document.getElementById('wrap')!.removeAttribute('data-hidden')
    fixA11y(document)

    expect(input.hasAttribute('aria-hidden')).toBe(false)
    expect(input.hasAttribute('tabindex')).toBe(false)
  })
})

describe('focusin 兜底清除 aria-hidden', () => {
  it('获得焦点的控件若残留 aria-hidden，立即清除并恢复 tabindex', () => {
    stubRects()
    setupA11yAutoFix()
    document.body.innerHTML = `<input id="f" aria-hidden="true" tabindex="-1" />`

    const input = document.getElementById('f')!
    input.dispatchEvent(new FocusEvent('focusin', { bubbles: true }))

    expect(input.hasAttribute('aria-hidden')).toBe(false)
    expect(input.hasAttribute('tabindex')).toBe(false)
  })
})
