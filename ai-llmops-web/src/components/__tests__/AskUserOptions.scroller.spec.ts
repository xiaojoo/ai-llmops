import { describe, it, expect } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { DynamicScroller, DynamicScrollerItem } from 'vue-virtual-scroller'
import AskUserOptions from '../AskUserOptions.vue'

// ===== 模拟 IndexView：DynamicScroller + ask_user 卡片 =====
// 关键差异：真实页面里 ask_user 卡片渲染在 dynamic-scroller-item 的 slot 里
type Thought = {
  id: string
  event: string
  task_id?: string
  question?: string
  options?: string[]
  allow_custom?: boolean
  choice?: string
}

type MessageLike = { id: string; agent_thoughts: Thought[] }

const makeScrollerHarness = () => {
  const messages = ref<{ id: string; agent_thoughts: Thought[] }[]>([
    { id: 'm1', agent_thoughts: [] },
  ])

  const pushAskUser = (t: Thought) => {
    const thoughts = messages.value[0]!.agent_thoughts
    const idx = thoughts.findIndex((x) => x.id === t.id)
    if (idx === -1) thoughts.push(t)
    else thoughts[idx] = t
  }

  const getAskUserThought = (item: { agent_thoughts: Thought[] }) => {
    const ts = item.agent_thoughts
    for (let i = ts.length - 1; i >= 0; i--) {
      if (ts[i]?.event === 'ask_user') return ts[i]
    }
    return null
  }

  const Harness = defineComponent({
    components: { DynamicScroller, DynamicScrollerItem, AskUserOptions },
    setup() {
      return () =>
        h(DynamicScroller, {
          ref: 'scroller',
          items: messages.value.slice().reverse(),
          minItemSize: 1,
        }, {
          default: ({ item, active }: { item: MessageLike; active: boolean }) =>
            h(DynamicScrollerItem, { item, active, 'data-index': item.id }, {
              default: () => {
                const thought = getAskUserThought(item)
                return h('div', { class: 'max-w-[976px] mx-auto px-6' }, [
                  h('div', { class: 'flex flex-col gap-2 py-4' }, [
                    thought
                      ? h(AskUserOptions, {
                          mode: 'option',
                          question: thought.question ?? '',
                          options: thought.options ?? [],
                          allowCustom: thought.allow_custom ?? true,
                          taskId: thought.task_id ?? '',
                          eventId: thought.id ?? '',
                          choice: thought.choice ?? '',
                        })
                      : h('div', 'no ask_user'),
                  ]),
                ])
              },
            }),
        })
    },
  })

  return { messages, pushAskUser, Harness }
}

describe('AskUserOptions × DynamicScroller 渲染链路', () => {
  it('thought.choice 变化后 slot 内的 AskUserOptions 收到新 props 并回显', async () => {
    const { pushAskUser, Harness } = makeScrollerHarness()
    const wrapper = mount(Harness, { attachTo: document.body })

    pushAskUser({ id: 'e1', event: 'ask_user', task_id: 't1', question: '如何处理？', options: ['A', 'B'], allow_custom: true })
    await nextTick()
    await nextTick()
    const text1 = wrapper.text()
    expect(text1).toContain('如何处理？')
    expect(text1).not.toContain('已选')

    // 模拟后端 republish：同 event_id 带 choice（等价于 markAskUserChoice 的结果）
    pushAskUser({ id: 'e1', event: 'ask_user', task_id: 't1', question: '如何处理？', options: ['A', 'B'], allow_custom: true, choice: 'A' })
    await nextTick()
    await nextTick()
    const text2 = wrapper.text()
    console.log('AFTER choice set, text:', JSON.stringify(text2.slice(0, 200)))
    expect(text2).toContain('已选：A')
  })

  it('原地改 choice（markAskUserChoice 等价路径）后 slot 内卡片回显', async () => {
    const { messages, pushAskUser, Harness } = makeScrollerHarness()
    const wrapper = mount(Harness, { attachTo: document.body })

    pushAskUser({ id: 'e1', event: 'ask_user', task_id: 't1', question: '如何处理？', options: ['A', 'B'], allow_custom: true })
    await nextTick()
    await nextTick()
    expect(wrapper.text()).toContain('如何处理？')

    // ===== IndexView.markAskUserChoice 的等价实现：原地改 t.choice（不替换数组元素） =====
    const markChoice = (taskId: string, choice: string) => {
      for (const msg of messages.value) {
        for (const thought of msg.agent_thoughts) {
          if (thought.event === 'ask_user' && thought.task_id === taskId) {
            thought.choice = choice
          }
        }
      }
    }
    markChoice('t1', 'A')
    await nextTick()
    await nextTick()
    const text = wrapper.text()
    console.log('AFTER in-place choice mutation, text:', JSON.stringify(text.slice(0, 200)))
    expect(text).toContain('已选：A')
  })
})
