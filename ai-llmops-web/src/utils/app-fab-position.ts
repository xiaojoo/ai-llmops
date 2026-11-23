/**
 * 右侧悬浮 App 切换按钮的位置计算。
 *
 * 这个按钮默认贴右、垂直居中，可以拖到任意位置。窗口尺寸变化时不能只"拉回视口内"：
 * 视口变大后原来的 x 已经不在右边了，只夹取会让贴右的按钮停在屏幕中间
 * （小窗→最大化就是这个现象）。所以按"它原本贴哪条边"重算：
 *  - 没拖过 → 回到默认锚点；
 *  - 拖过 → 保持它贴住那条边的间距，其余情况只保证不出屏。
 */

export interface FabViewport {
  w: number
  h: number
}

export interface FabPositionInput {
  x: number
  y: number
  /** 上一次布局用的视口尺寸（判断贴边必须用它：变化后到右边的距离已经不是原来的了） */
  prev: FabViewport
  /** 当前视口尺寸 */
  current: FabViewport
  /** 按钮边长 */
  size: number
  /** 默认位置距右/上/下边的间距 */
  margin: number
  /** 距边不超过这个数算"贴边" */
  snap: number
  /** 用户是否拖动过 */
  dragged: boolean
}

const clamp = (v: number, min: number, max: number) => Math.max(min, Math.min(v, max))

/** 默认位置：贴右、垂直居中。 */
export function defaultFabPosition(current: FabViewport, size: number, margin: number) {
  return {
    x: Math.max(0, current.w - size - margin),
    y: Math.max(margin, (current.h - size) / 2),
  }
}

export function resolveFabPosition(input: FabPositionInput): { x: number; y: number } {
  const { x, y, prev, current, size, margin, snap, dragged } = input
  if (!dragged) return defaultFabPosition(current, size, margin)

  const maxX = current.w - size
  const maxY = current.h - size

  const gapRight = prev.w - (x + size)
  const gapBottom = prev.h - (y + size)
  let nextX = x
  if (gapRight <= snap) nextX = current.w - size - gapRight
  else if (x <= snap) nextX = x
  else nextX = clamp(x, 0, maxX)

  let nextY = y
  if (gapBottom <= snap) nextY = current.h - size - gapBottom
  else if (y <= snap) nextY = y
  else nextY = clamp(y, 0, maxY)

  return { x: Math.max(0, nextX), y: Math.max(0, nextY) }
}
