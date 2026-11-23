import { describe, it, expect } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'
import { mount } from '@vue/test-utils'
import AskUserOptions from '../AskUserOptions.vue'

// ===== 忠实模拟 IndexView 的 ask_user 数据流 =====
// messages[0].agent_thoughts：SSE 事件写入；republish 用同 event_id 替换
type Thought = {
  id: string
  event: string
  task_id?: string
  question?: string
  options?: string[]
  allow_custom?: boolean
  choice?: string
  sub_task_options?: { order: number; title: string }[]
}

// AskUserOptions 提交事件载荷（与组件 emit 的 SubmittedPayload 保持一致）
type SubmittedPayload = {
  taskId: string
  choice?: string
  skip: boolean
  eventId: string
  action?: 'confirm' | 'replan'
  keepOrders?: number[]
  custom?: string
}

const askUserThought = (thoughts: Thought[]) => {
  for (let i = thoughts.length - 1; i >= 0; i--) {
    if (thoughts[i]?.event === 'ask_user') return thoughts[i]
  }
  return null
}

const makeHarness = () => {
  const messages = ref<{ id: string; agent_thoughts: Thought[] }[]>([
    { id: 'm1', agent_thoughts: [] },
  ])
  const thoughts = messages.value[0]!.agent_thoughts

  const pushAskUser = (t: Thought) => {
    const idx = thoughts.findIndex((x) => x.id === t.id)
    if (idx === -1) thoughts.push(t)
    else thoughts[idx] = t // republish：同 id 替换
  }

  const markChoice = (taskId: string, choice: string) => {
    for (const t of thoughts) {
      if (t.event === 'ask_user' && t.task_id === taskId) t.choice = choice
    }
  }

  const Harness = defineComponent({
    components: { AskUserOptions },
    setup() {
      return () => {
        const thought = askUserThought(messages.value[0]!.agent_thoughts)
        if (!thought) return h('div', 'no ask_user')
        return h(AskUserOptions, {
          mode: thought.sub_task_options?.length ? 'plan' : 'option',
          subTaskOptions: thought.sub_task_options ?? [],
          requiresReason: true,
          question: thought.question ?? '',
          options: thought.options ?? [],
          allowCustom: thought.allow_custom ?? true,
          taskId: thought.task_id ?? '',
          eventId: thought.id ?? '',
          choice: thought.choice ?? '',
          onSubmitted: (payload: SubmittedPayload) => {
            // 与真实 IndexView 一致：plan 模式把 action 映射为回显文案（乐观回显）
            const displayChoice = payload.action
              ? payload.action === 'replan'
                ? '重新规划'
                : '确认执行'
              : (payload.choice ?? '')
            // 模拟 POST 返回后本地回写（宏任务延迟，与真实网络一致：提交后先进入"已提交"中间态）
            setTimeout(() => markChoice(payload.taskId, displayChoice), 20)
          },
        })
      }
    },
  })

  return { messages, thoughts, pushAskUser, markChoice, Harness }
}

describe('AskUserOptions 实时回显（option 模式）', () => {
  it('提交后 choice 回填 → 显示"已选"，按钮禁用', async () => {
    const { pushAskUser, Harness } = makeHarness()
    const wrapper = mount(Harness, { attachTo: document.body })

    // SSE 事件：ask_user（无 choice）
    pushAskUser({ id: 'e1', event: 'ask_user', task_id: 't1', question: '如何处理？', options: ['A', 'B'], allow_custom: true })
    await nextTick()
    expect(wrapper.text()).toContain('如何处理？')
    expect(wrapper.text()).not.toContain('已选')

    // 点击选项 A → 高亮（selected）
    const optionBtns = wrapper.findAll('button').filter((b) => ['A', 'B'].includes(b.text()))
    await optionBtns[0]!.trigger('click')
    await nextTick()
    expect(wrapper.text()).not.toContain('已提交') // 仅选中不提交

    // 点击"提交"按钮
    const submitBtn = wrapper.findAll('button').find((b) => b.text() === '提交')!
    await submitBtn.trigger('click')
    await nextTick()
    expect(wrapper.text()).toContain('已提交，继续处理中…') // POST 进行中

    // POST 完成 → markAskUserChoice → props.choice 回填 → 回显
    await new Promise((r) => setTimeout(r, 40))
    await nextTick()
    await nextTick()
    expect(wrapper.text()).toContain('已选：A')
    expect(wrapper.findAll('button')[0]!.attributes('disabled')).toBeDefined()
  })

  it('SSE republish（同 event_id 带 choice 替换）→ 显示"已选"', async () => {
    const { pushAskUser, Harness } = makeHarness()
    const wrapper = mount(Harness, { attachTo: document.body })

    pushAskUser({ id: 'e1', event: 'ask_user', task_id: 't1', question: '如何处理？', options: ['A', 'B'], allow_custom: true })
    await nextTick()

    // 后端 republish：同 event_id、带 choice（覆盖首次发布）
    pushAskUser({ id: 'e1', event: 'ask_user', task_id: 't1', question: '如何处理？', options: ['A', 'B'], allow_custom: true, choice: 'A' })
    await nextTick()
    expect(wrapper.text()).toContain('已选：A')
    expect(wrapper.findAll('button')[0]!.attributes('disabled')).toBeDefined()
  })

  it('连续两问（plan→option）后第二问回显正确', async () => {
    const { pushAskUser, Harness } = makeHarness()
    const wrapper = mount(Harness, { attachTo: document.body })

    // 第一问：plan（子任务勾选）
    pushAskUser({
      id: 'e1', event: 'ask_user', task_id: 't1', question: '请确认任务分配方案',
      options: ['子任务A'], allow_custom: true,
      sub_task_options: [{ order: 1, title: '子任务A' }],
    })
    await nextTick()
    expect(wrapper.text()).toContain('确认执行')

    // 确认后 republish 带 choice
    pushAskUser({
      id: 'e1', event: 'ask_user', task_id: 't1', question: '请确认任务分配方案',
      options: ['子任务A'], allow_custom: true,
      sub_task_options: [{ order: 1, title: '子任务A' }],
      choice: JSON.stringify({ action: 'confirm', keep_orders: [1] }),
    })
    await nextTick()
    expect(wrapper.text()).toContain('已确认执行')

    // 第二问：option 模式（同消息内新 eventId）
    pushAskUser({ id: 'e2', event: 'ask_user', task_id: 't2', question: '如何处理？', options: ['A', 'B'], allow_custom: true })
    await nextTick()
    expect(wrapper.text()).toContain('如何处理？')
    expect(wrapper.text()).not.toContain('已确认执行') // eventId watch 已复位

    // 点击 A + 提交 + POST 回填
    const optionBtns = wrapper.findAll('button').filter((b) => ['A', 'B'].includes(b.text()))
    await optionBtns[0]!.trigger('click')
    await nextTick()
    const submitBtn = wrapper.findAll('button').find((b) => b.text() === '提交')!
    await submitBtn.trigger('click')
    await nextTick()
    await new Promise((r) => setTimeout(r, 40)) // 等 mock POST 回填
    await nextTick()
    expect(wrapper.text()).toContain('已选：A')
  })

  it('连续两问（option→plan）后第二问回显正确', async () => {
    const { pushAskUser, Harness } = makeHarness()
    const wrapper = mount(Harness, { attachTo: document.body })

    // 第一问：option 模式
    pushAskUser({ id: 'e1', event: 'ask_user', task_id: 't1', question: '如何处理？', options: ['A', 'B'], allow_custom: true })
    await nextTick()
    const optionBtns = wrapper.findAll('button').filter((b) => ['A', 'B'].includes(b.text()))
    await optionBtns[0]!.trigger('click')
    await nextTick()
    const submitBtn = wrapper.findAll('button').find((b) => b.text() === '提交')!
    await submitBtn.trigger('click')
    await nextTick()
    await new Promise((r) => setTimeout(r, 40)) // 等 mock POST 回填
    await nextTick()
    expect(wrapper.text()).toContain('已选：A')

    // 第二问：plan 模式（新 eventId）
    pushAskUser({
      id: 'e2', event: 'ask_user', task_id: 't2', question: '请确认任务分配方案',
      options: ['子任务A'], allow_custom: true,
      sub_task_options: [{ order: 1, title: '子任务A' }, { order: 2, title: '子任务B' }],
    })
    await nextTick()
    expect(wrapper.text()).toContain('确认执行')
    const boxes = wrapper.findAll('input[type="checkbox"]')
    await boxes[1]!.setValue(true)
    await nextTick()
    const confirmBtn = wrapper.findAll('button').find((b) => b.text() === '确认执行')!
    await confirmBtn.trigger('click')
    await nextTick()
    // POST 回填 plan choice → 回显"已确认执行"
    await new Promise((r) => setTimeout(r, 40))
    await nextTick()
    expect(wrapper.text()).toContain('已确认执行')
  })
})

describe('AskUserOptions 计划确认（plan 模式）依赖可见', () => {
  // 后端现在按 depends_on 分批调度并把前置产出喂给后置；界面上看不见的话，
  // 用户勾掉一个前置就不知道自己同时断了后置的输入来源。
  const mountPlan = (subTaskOptions: { order: number; title: string; depends_on?: number[] }[]) =>
    mount(AskUserOptions, {
      props: {
        mode: 'plan',
        subTaskOptions,
        question: '请确认任务分配方案',
        taskId: 't1',
        eventId: 'e1',
        choice: '',
      },
    })

  it('声明了依赖的子任务显示依赖，未声明的不出现空行', () => {
    const wrapper = mountPlan([
      { order: 1, title: '检索资料' },
      { order: 2, title: '撰写报告', depends_on: [1] },
    ])
    expect(wrapper.text()).toContain('依赖：#1')
    expect(wrapper.text().match(/依赖：/g)).toHaveLength(1)
  })

  it('多个前置按声明顺序顿号连接', () => {
    const wrapper = mountPlan([
      { order: 1, title: 'A' },
      { order: 2, title: 'B' },
      { order: 3, title: 'C', depends_on: [1, 2] },
    ])
    expect(wrapper.text()).toContain('依赖：#1、#2')
  })
})
