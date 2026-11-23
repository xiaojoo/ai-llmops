import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'

import AgentChatEmbed from '../../agent-chat-embed/AgentChatEmbed.vue'

/**
 * 插件端"切会话不打断"的落点判据（VSCode 与 IDEA 共用这一个 embed）。
 *
 * 现象：SSE 由宿主持有，切会话不会掐后端连接，上一轮的增量事件会继续到达；
 * 而 appendDelta 只看"最后一条 assistant"，于是 A 会话的正文会写进 B 会话的气泡。
 * 这里按真实的宿主协议驱动（window.__agentChatEvent + 面板 selectConversation 事件），
 * 只把 AgentChatPanel 换成一个渲染正文的壳：要证的归属判定在 embed 这一侧。
 */
const PanelStub = defineComponent({
  name: 'AgentChatPanel',
  props: {
    messages: { type: Array, default: () => [] },
    sending: { type: Boolean, default: false },
  },
  emits: ['selectConversation'],
  setup(props) {
    return () =>
      h(
        'div',
        (props.messages as Array<{ content: string; askUser?: { question?: string } }>).map((m, i) =>
          h('p', { key: i }, `${m.content}${m.askUser ? `ask:${m.askUser.question}` : ''}`),
        ),
      )
  },
})

const A = 'conv-aaaaaaaa'
const B = 'conv-bbbbbbbb'

/** 宿主桥：按真实 action 名回数据，未列出的 action 一律回 null */
function stubHost(loadMessages: (id: string) => unknown[]) {
  window.agentChatHost = (arg) => {
    const { request, onSuccess } = arg
    let action = ''
    let conversationId = ''
    try {
      const parsed = JSON.parse(String(request)) as { action: string; payload?: { conversationId?: string } }
      action = parsed.action
      conversationId = parsed.payload?.conversationId || ''
    } catch {
      /* 畸形请求：按未知 action 处理 */
    }
    const data: Record<string, unknown> = {
      authStatus: { loggedIn: true },
      listWebApps: [{ token: 'wt-1', name: '测试应用', icon: '' }],
      getWebApp: { name: '测试应用', icon: '', token: 'wt-1', speechToTextEnabled: false },
      getLastConversation: { conversationId: A },
      loadMessages: loadMessages(conversationId),
      listSessions: [{ id: A, title: 'A' }, { id: B, title: 'B' }],
      listWorkspaces: [],
    }
    onSuccess?.(JSON.stringify({ ok: true, data: data[action] ?? null }))
  }
}

const msg = (id: string, role: 'user' | 'assistant', content: string) => ({ id, role, content })

function hostEvent(type: string, data: unknown) {
  window.__agentChatEvent?.({ type, data })
}

async function mountEmbed(loadMessages: (id: string) => unknown[]) {
  stubHost(loadMessages)
  const wrapper = mount(AgentChatEmbed, {
    global: { stubs: { AgentChatPanel: PanelStub, SessionSettingsDialog: true } },
  })
  // onMounted 里 bootstrap 是 setTimeout(300) 起跳的，登录后才会渲染面板
  await new Promise((r) => setTimeout(r, 400))
  await flushPromises()
  expect(wrapper.text()).not.toContain('WebApp 登录')
  return wrapper
}

const selectConversation = async (wrapper: ReturnType<typeof mount>, id: string) => {
  await wrapper.findComponent(PanelStub).vm.$emit('selectConversation', id)
  await flushPromises()
}

describe('插件端流事件归属', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    delete window.agentChatHost
    delete window.__agentChatEvent
  })

  it('未切走时增量正常落到当前会话', async () => {
    const wrapper = await mountEmbed((id) =>
      id === A ? [msg('u1', 'user', 'A 的提问'), msg('a1', 'assistant', '')] : [],
    )
    await selectConversation(wrapper, A)

    hostEvent('messageDelta', { content: '前半段', conversationId: A, messageId: 'a1' })
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('前半段')
  })

  it('切到别的会话后，上一轮的增量不再写进当前界面', async () => {
    const wrapper = await mountEmbed((id) =>
      id === A
        ? [msg('u1', 'user', 'A 的提问'), msg('a1', 'assistant', '前半段')]
        : [msg('u2', 'user', 'B 的提问'), msg('a2', 'assistant', 'B 的旧回答')],
    )
    await selectConversation(wrapper, A)
    hostEvent('messageDelta', { content: '后半段', conversationId: A, messageId: 'a1' })
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('后半段')

    await selectConversation(wrapper, B)
    expect(wrapper.text()).toContain('B 的旧回答')

    // A 那一轮还在跑：宿主的连接没断，事件照样到达
    hostEvent('messageDelta', { content: '串味的尾巴', conversationId: A, messageId: 'a1' })
    hostEvent('messageEnd', { latency: 3 })
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).not.toContain('串味的尾巴')
    expect(wrapper.text()).not.toContain('后半段')
    expect(wrapper.text()).toContain('B 的旧回答')
  })

  it('切回仍在生成的会话时，后续增量重新落到它上面', async () => {
    const wrapper = await mountEmbed((id) =>
      id === A
        ? [msg('u1', 'user', 'A 的提问'), msg('a1', 'assistant', '已收到的部分')]
        : [msg('u2', 'user', 'B 的提问'), msg('a2', 'assistant', 'B 的旧回答')],
    )
    await selectConversation(wrapper, A)
    await selectConversation(wrapper, B)
    hostEvent('messageDelta', { content: '在别处丢弃的', conversationId: A, messageId: 'a1' })
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).not.toContain('在别处丢弃的')

    await selectConversation(wrapper, A)
    hostEvent('messageDelta', { content: '切回来继续收', conversationId: A, messageId: 'a1' })
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('切回来继续收')
  })

  it('切回来时把这一轮已生成的正文接回气泡（此刻库里只有空占位行）', async () => {
    const wrapper = await mountEmbed((id) =>
      id === A
        ? [msg('u1', 'user', 'A 的提问'), msg('a1', 'assistant', '')]
        : [msg('u2', 'user', 'B 的提问'), msg('a2', 'assistant', 'B 的旧回答')],
    )
    await selectConversation(wrapper, A)
    hostEvent('messageDelta', { content: '开头', conversationId: A, messageId: 'a1' })
    await wrapper.vm.$nextTick()

    await selectConversation(wrapper, B)
    hostEvent('messageDelta', { content: '中段', conversationId: A, messageId: 'a1' })
    await wrapper.vm.$nextTick()

    await selectConversation(wrapper, A)
    expect(wrapper.findAll('p')[1]!.text()).toBe('开头中段')

    hostEvent('messageDelta', { content: '结尾', conversationId: A, messageId: 'a1' })
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('p')[1]!.text()).toBe('开头中段结尾')
  })

  it('切走时到达的 ask_user 不挂到别的会话上，切回来补挂', async () => {
    const wrapper = await mountEmbed((id) =>
      id === A
        ? [msg('u1', 'user', 'A 的提问'), msg('a1', 'assistant', 'A 已生成的部分')]
        : [msg('u2', 'user', 'B 的提问'), msg('a2', 'assistant', 'B 的旧回答')],
    )
    await selectConversation(wrapper, A)
    // 先让这一轮定主到 A 上（宿主在 delta 里带 conversationId）
    hostEvent('messageDelta', { content: '接着写', conversationId: A, messageId: 'a1' })
    await wrapper.vm.$nextTick()

    await selectConversation(wrapper, B)
    // ask_user 不带会话 id（宿主只推 taskId/question/options），按归属判
    hostEvent('askUser', { taskId: 't1', question: '要哪个方案？', options: ['甲', '乙'] })
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).not.toContain('要哪个方案？')
    expect(wrapper.text()).toContain('B 的旧回答')

    await selectConversation(wrapper, A)
    expect(wrapper.text()).toContain('要哪个方案？')
  })
})
