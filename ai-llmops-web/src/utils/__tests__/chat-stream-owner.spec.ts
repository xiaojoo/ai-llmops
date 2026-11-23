import { describe, expect, it } from 'vitest'

import { resolveStreamOwnership } from '../chat-stream-owner'

/**
 * 判据形态是"事件属于哪个会话 + 界面正在显示哪个会话"，两种表面都要覆盖：
 * 带 conversationId 的是 messageDelta（宿主两端都会带），不带的是
 * messageEnd / error / askUser（endStatsJson、errorJson 里根本没这个字段）。
 */
describe('resolveStreamOwnership', () => {
  it('同一会话的增量正常接收', () => {
    expect(
      resolveStreamOwnership({
        owner: 'A',
        pendingNewConversation: false,
        viewConversationId: 'A',
        frameConversationId: 'A',
      }),
    ).toMatchObject({ visible: true, adoptViewId: '' })
  })

  it('切到别的会话后，上一轮的增量不再落到当前界面', () => {
    expect(
      resolveStreamOwnership({
        owner: 'A',
        pendingNewConversation: false,
        viewConversationId: 'B',
        frameConversationId: 'A',
      }).visible,
    ).toBe(false)
  })

  it('新会话首帧回写 id：界面落到这个新会话上', () => {
    const r = resolveStreamOwnership({
      owner: '',
      pendingNewConversation: true,
      viewConversationId: '',
      frameConversationId: 'A',
    })
    expect(r).toEqual({ visible: true, owner: 'A', adoptViewId: 'A' })
  })

  it('首帧到达前用户已切走：定主但不抢界面', () => {
    const r = resolveStreamOwnership({
      owner: '',
      pendingNewConversation: false,
      viewConversationId: 'B',
      frameConversationId: 'A',
    })
    expect(r).toEqual({ visible: false, owner: 'A', adoptViewId: '' })
  })

  it('无归属事件（end/error/askUser）按已记录的归属判', () => {
    const same = resolveStreamOwnership({
      owner: 'A',
      pendingNewConversation: false,
      viewConversationId: 'A',
    })
    const away = resolveStreamOwnership({
      owner: 'A',
      pendingNewConversation: false,
      viewConversationId: 'B',
    })
    expect(same.visible).toBe(true)
    expect(away.visible).toBe(false)
  })

  it('本轮刚发起、id 还没回来时不挡事件', () => {
    expect(
      resolveStreamOwnership({
        owner: '',
        pendingNewConversation: true,
        viewConversationId: '',
      }).visible,
    ).toBe(true)
  })

  it('事件归属与已定主不一致时丢弃（防御）', () => {
    expect(
      resolveStreamOwnership({
        owner: 'A',
        pendingNewConversation: false,
        viewConversationId: 'A',
        frameConversationId: 'B',
      }).visible,
    ).toBe(false)
  })
})
