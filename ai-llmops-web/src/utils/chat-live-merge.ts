/**
 * 切回会话时，如何把"仍在流式的那条消息"合进服务端返回的快照列表。
 *
 * 关键：id 相同不代表内容相同。服务端那一行可能是 answer 仍为空的占位
 * （回答要到流结束时才落库），而正在流式的对象里内容已经在增长。
 * 这时若按 id 判重直接跳过合并，用户切回来看到的就是一个空气泡
 * （0.00s / 0 Tokens），真实回答还在往一个没被渲染的对象里写。
 */
export function planLiveMerge<T extends { id: string; answer?: string }>(
  list: T[],
  live: T | null | undefined,
): { action: 'none' } | { action: 'unshift' } | { action: 'replace'; index: number } {
  if (!live) return { action: 'none' }

  const index = list.findIndex((m) => m.id === live.id)
  // 服务端还没有这一行（首轮刚发出、或还是 temp_ 临时 id）：插到最前面
  if (index === -1) return { action: 'unshift' }

  const serverLen = (list[index]?.answer ?? '').length
  const liveLen = (live.answer ?? '').length
  // 只有流式对象内容更多时才替换：反向情况说明服务端已落库完整答案，
  // 用较短的在途对象去覆盖会把已完成的回答改回半截
  return liveLen > serverLen ? { action: 'replace', index } : { action: 'none' }
}
