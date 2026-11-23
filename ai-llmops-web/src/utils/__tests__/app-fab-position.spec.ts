import { describe, expect, it } from 'vitest'

import { defaultFabPosition, resolveFabPosition } from '../app-fab-position'

const SIZE = 44
const MARGIN = 16
const SNAP = 24

/** 小窗（500x500）→ 最大化（1900x1000）：贴右的按钮必须跟着右边走 */
const small = { w: 500, h: 500 }
const big = { w: 1900, h: 1000 }

const resolve = (over: Partial<Parameters<typeof resolveFabPosition>[0]>) =>
  resolveFabPosition({
    x: 0,
    y: 0,
    prev: small,
    current: big,
    size: SIZE,
    margin: MARGIN,
    snap: SNAP,
    dragged: false,
    ...over,
  })

describe('resolveFabPosition', () => {
  it('没拖过时回到默认锚点：贴右 + 垂直居中', () => {
    const p = resolve({ x: 440, y: 228, dragged: false })
    expect(p).toEqual({ x: big.w - SIZE - MARGIN, y: (big.h - SIZE) / 2 })
  })

  it('贴右且拖动过：视口变宽后仍贴右，并保持原间距', () => {
    const gap = 16
    const x = small.w - SIZE - gap
    expect(resolve({ x, y: 100, dragged: true })).toEqual({ x: big.w - SIZE - gap, y: 100 })
  })

  it('贴左且拖动过：留在左边，不被拽到右边', () => {
    expect(resolve({ x: 8, y: 100, dragged: true })).toEqual({ x: 8, y: 100 })
  })

  it('拖到屏幕中间：绝对位置不动（用户自己停的那儿）', () => {
    expect(resolve({ x: 250, y: 250, dragged: true })).toEqual({ x: 250, y: 250 })
  })

  it('视口变窄时贴边的按钮被拉回屏内，不留在屏外', () => {
    const p = resolve({
      x: big.w - SIZE - 16,
      y: big.h - SIZE - 10,
      prev: big,
      current: small,
      dragged: true,
    })
    expect(p.x).toBe(small.w - SIZE - 16)
    expect(p.y).toBe(small.h - SIZE - 10)
    expect(p.x + SIZE).toBeLessThanOrEqual(small.w)
  })

  it('贴底且拖动过：视口变高后跟着下边走', () => {
    const y = small.h - SIZE - 6
    expect(resolve({ x: 250, y, dragged: true }).y).toBe(big.h - SIZE - 6)
  })

  it('贴顶且拖动过：留在顶部', () => {
    expect(resolve({ x: 250, y: 12, dragged: true }).y).toBe(12)
  })

  it('默认位置本身就在右边缘外时不会算成负数（超窄视口）', () => {
    const p = defaultFabPosition({ w: 30, h: 30 }, SIZE, MARGIN)
    expect(p.x).toBe(0)
    expect(p.y).toBe(MARGIN)
  })
})
