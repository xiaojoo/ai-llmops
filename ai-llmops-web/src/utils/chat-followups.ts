/**
 * 本轮回答是否可以发起"后续动作"（推荐问题 / 语音自动播报）。
 *
 * 三个聊天界面（web-apps、调试预览、首页助手）共用这一条规则。之前是各自抄一遍，
 * 结果抄漏了：语音播报那两处压根没判失败标记，模型空回答时气泡还空着就已经
 * 长出三个推荐问题、并开始播一段没有内容的语音。
 */
export function followupsAllowed(opts: {
  /** 本轮以 error / stop / timeout 收尾，或用户点了停止 */
  failed: boolean
  /** 本轮已累加的回答正文 */
  answer?: string
  /** 本轮回答的消息 id（空则说明连接/服务异常，压根没建起来） */
  messageId?: string
}): boolean {
  if (opts.failed) return false
  if (!opts.messageId) return false
  // 只判 messageId 非空不够：模型空回答时消息 id 已经有了，但没有任何可推荐/可播报的内容
  return (opts.answer ?? '').trim() !== ''
}
