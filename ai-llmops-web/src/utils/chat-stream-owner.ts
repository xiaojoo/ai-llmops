/**
 * 流事件归属判定（IDE 插件端）。
 *
 * 插件的 SSE 由宿主（VSCode 扩展 / IDEA Java）持有，切会话或重建 webview 都不会掐断后端连接，
 * 所以上一轮的增量事件会继续往这个界面里送。不判归属就会把 A 会话的正文追加到 B 会话最后一条
 * 回复上（切走时界面被清空，落点就是新加载出来的那条）。
 *
 * 判据只有一条：**事件的归属会话 === 当前界面显示的会话**。唯一的例外是"从空会话发起的这一轮"：
 * 后端还没建会话，conversation_id 要等首帧才回写得知，此时界面需要跟着落到这个新 id 上。
 */

export interface StreamOwnership {
  /** 这条事件是否该由当前界面接收 */
  visible: boolean
  /** 新的归属会话 id（'' = 仍未定主）；调用方据此覆盖自己的记录 */
  owner: string
  /** 非空 = 当前界面应当落到这个新会话 id 上（新会话首帧回写） */
  adoptViewId: string
}

export function resolveStreamOwnership(input: {
  /** 当前记录的归属会话（发起那一轮时写入；'' 表示还没定主） */
  owner: string
  /** 本轮是否从"新会话"发起（切走/新建会话时由调用方清掉，清掉后不再抢界面） */
  pendingNewConversation: boolean
  /** 当前界面正在显示的会话 id（'' = 空白的新建会话） */
  viewConversationId: string
  /** 事件自带的会话 id；messageEnd / error / askUser 这三类宿主不带，为空 */
  frameConversationId?: string
}): StreamOwnership {
  const from = input.frameConversationId || ''
  if (!from) {
    // 不带归属的事件按已记录的归属判：还没定主说明就是本视图发起的那一轮
    return {
      visible: !input.owner || input.owner === input.viewConversationId,
      owner: input.owner,
      adoptViewId: '',
    }
  }
  if (input.owner) {
    return {
      visible: input.owner === from && from === input.viewConversationId,
      owner: input.owner,
      adoptViewId: '',
    }
  }
  // 首帧定主
  if (input.pendingNewConversation) {
    return { visible: true, owner: from, adoptViewId: from }
  }
  return { visible: from === input.viewConversationId, owner: from, adoptViewId: '' }
}
