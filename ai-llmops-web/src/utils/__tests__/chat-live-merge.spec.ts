import { describe, expect, it } from 'vitest'

import { planLiveMerge } from '../chat-live-merge'

type Row = { id: string; answer?: string }

// 复现的实测场景：切走会话时 SSE 仍在后台推送，切回来服务端返回的那一行
// id 相同但 answer 还是空占位（落库要到流结束才发生）。旧实现按 id 判重直接跳过合并，
// 于是界面渲染那条空气泡（0.00s / 0 Tokens），真实回答还在往一个没渲染的对象里写。
describe('planLiveMerge（切回会话时不能把在流式的回答丢成空气泡）', () => {
  it('没有在流式的消息时不动列表', () => {
    expect(planLiveMerge([{ id: 'm1', answer: 'x' }], null)).toEqual({ action: 'none' })
  })

  it('服务端还没有这一行（首轮 temp id）→ 插到最前', () => {
    const live: Row = { id: 'temp_123', answer: '正在生成' }
    expect(planLiveMerge([{ id: 'm1', answer: '上一轮' }], live)).toEqual({ action: 'unshift' })
  })

  it('服务端那行是空占位、在流式的已有内容 → 替换成在流式的', () => {
    const list: Row[] = [
      { id: 'm9', answer: '' },
      { id: 'm1', answer: '上一轮完整回答' },
    ]
    const live: Row = { id: 'm9', answer: '番茄炒蛋先焯水' }
    expect(planLiveMerge(list, live)).toEqual({ action: 'replace', index: 0 })
  })

  it('替换要命中正确的那一行，不是永远换第一条', () => {
    const list: Row[] = [
      { id: 'm1', answer: '较早的一轮' },
      { id: 'm9', answer: '' },
    ]
    const live: Row = { id: 'm9', answer: '正在生成的内容' }
    expect(planLiveMerge(list, live)).toEqual({ action: 'replace', index: 1 })
  })

  it('服务端已落库完整答案（比在途对象更长）→ 不覆盖，避免把完成态退回半截', () => {
    const list: Row[] = [{ id: 'm9', answer: '完整的 581 字回答内容' }]
    const live: Row = { id: 'm9', answer: '半截' }
    expect(planLiveMerge(list, live)).toEqual({ action: 'none' })
  })

  it('两边一样长 → 不动', () => {
    const list: Row[] = [{ id: 'm9', answer: 'same' }]
    expect(planLiveMerge(list, { id: 'm9', answer: 'same' })).toEqual({ action: 'none' })
  })

  it('answer 字段缺失时按空串处理，不能抛错', () => {
    const list: Row[] = [{ id: 'm9' }]
    expect(planLiveMerge(list, { id: 'm9', answer: '有内容了' })).toEqual({
      action: 'replace',
      index: 0,
    })
  })
})
