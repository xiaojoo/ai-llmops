import { describe, expect, it } from 'vitest'

import { followupsAllowed } from '../chat-followups'

// 后续动作 = 推荐问题 / 语音自动播报。这条规则原来在三个聊天界面各抄一遍，
// 结果抄漏了：语音播报那两处压根没判失败标记，模型空回答时气泡还空着就已经
// 长出三个推荐问题、并开始播一段没有内容的语音。
describe('followupsAllowed（LLM 空回答/中断时不得发起推荐问题与播报）', () => {
  it('正常产出正文时放行', () => {
    expect(
      followupsAllowed({ failed: false, answer: '番茄炒蛋先焯水……', messageId: 'm1' }),
    ).toBe(true)
  })

  it('模型空回答时拦住：截图里那条 0 Tokens 的空气泡', () => {
    expect(followupsAllowed({ failed: false, answer: '', messageId: 'm1' })).toBe(false)
  })

  it('只有空白字符也算空回答', () => {
    expect(followupsAllowed({ failed: false, answer: ' \n\t ', messageId: 'm1' })).toBe(false)
  })

  it('answer 缺字段时拦住', () => {
    expect(followupsAllowed({ failed: false, answer: undefined, messageId: 'm1' })).toBe(false)
  })

  it.each([
    ['error 事件', true],
    ['stop 事件（后端停止）', true],
    ['timeout 事件（监听超时）', true],
    ['用户点停止（客户端 abort，收不到 stop 事件）', true],
  ])('%s 时即使已有部分正文也拦住', (_why, failed) => {
    expect(followupsAllowed({ failed, answer: '说到一半被打断', messageId: 'm1' })).toBe(false)
  })

  it('没有 message_id（连接压根没建起来）时拦住', () => {
    expect(followupsAllowed({ failed: false, answer: '有内容', messageId: '' })).toBe(false)
    expect(followupsAllowed({ failed: false, answer: '有内容', messageId: undefined })).toBe(false)
  })
})
