import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import AskUserOptions from '../AskUserOptions.vue'

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

describe('AskUserOptions', () => {
  it('渲染问题与选项', () => {
    const wrapper = mount(AskUserOptions, {
      props: {
        question: '选择授权模型？',
        options: ['RBAC', 'ABAC'],
        allowCustom: true,
        taskId: 't1',
        eventId: 'e1',
        choice: '',
      },
    })
    expect(wrapper.text()).toContain('选择授权模型？')
    expect(wrapper.text()).toContain('RBAC')
    expect(wrapper.text()).toContain('ABAC')
  })

  it('提交选择后进入已提交状态并 emit submitted', async () => {
    const wrapper = mount(AskUserOptions, {
      props: { question: 'q', options: ['A'], allowCustom: false, taskId: 't1', eventId: 'e1', choice: '' },
    })
    const buttons = wrapper.findAll('button')
    // 按钮顺序（option 模式）：[选项..., 跳过, 提交]——点选项仅选中，点最右"提交"才提交
    await buttons[0]!.trigger('click') // 选项 A
    await buttons[buttons.length - 1]!.trigger('click') // 提交
    expect(wrapper.emitted('submitted')).toBeTruthy()
    expect(wrapper.emitted('submitted')![0]).toEqual([
      { taskId: 't1', choice: 'A', skip: false, eventId: 'e1' },
    ])
  })

  it('跳过时 emit submitted 携带 eventId', async () => {
    const wrapper = mount(AskUserOptions, {
      props: { question: 'q', options: ['A'], allowCustom: false, taskId: 't1', eventId: 'e1', choice: '' },
    })
    const buttons = wrapper.findAll('button')
    await buttons[buttons.length - 2]!.trigger('click') // 跳过（提交左侧）
    expect(wrapper.emitted('submitted')![0]).toEqual([
      { taskId: 't1', choice: '', skip: true, eventId: 'e1' },
    ])
  })

  it('choice 非空时回显已选', () => {
    const wrapper = mount(AskUserOptions, {
      props: { question: 'q', options: ['A'], allowCustom: false, taskId: 't1', eventId: 'e1', choice: 'A' },
    })
    expect(wrapper.text()).toContain('已选：A')
  })
})

describe('AskUserOptions plan 模式', () => {
  it('渲染子任务勾选列表，默认全不选', () => {
    const wrapper = mount(AskUserOptions, {
      props: {
        mode: 'plan',
        question: '请确认任务分配方案',
        subTaskOptions: [
          { order: 1, title: '检索资料' },
          { order: 2, title: '撰写报告' },
        ],
        requiresReason: true,
        taskId: 't1',
        eventId: 'e1',
        choice: '',
      },
    })
    expect(wrapper.text()).toContain('检索资料')
    expect(wrapper.text()).toContain('撰写报告')
    expect(wrapper.findAll('input[type="checkbox"]').length).toBe(2)
    expect(wrapper.findAll('input[type="checkbox"]:checked').length).toBe(0)
  })

  it('确认执行 emit keepOrders 且 custom 恒为空（即使填了原因，避免后端误判重新规划）', async () => {
    const wrapper = mount(AskUserOptions, {
      props: { mode: 'plan', question: 'q', subTaskOptions: [{ order: 1, title: 'A' }, { order: 2, title: 'B' }], requiresReason: false, taskId: 't1', eventId: 'e1', choice: '' },
    })
    await wrapper.findAll('input[type="checkbox"]')[0]!.setValue(true)
    // 填了原因仍点"确认执行"：custom 必须为 ''（Fix 4：custom 非空会被后端静默转重拆）
    const customInput = wrapper
      .findAll('input')
      .find((i) => (i.attributes('placeholder') || '').includes('原因'))!
    await customInput.setValue('其实我想全保留')
    await wrapper.findAll('button')[1]!.trigger('click') // 确认执行（最右）
    const emitted = wrapper.emitted('submitted')![0]![0] as SubmittedPayload
    expect(emitted).toMatchObject({ taskId: 't1', action: 'confirm', keepOrders: [1], custom: '', skip: false, eventId: 'e1' })
  })

  it('重新规划携带原因 custom', async () => {
    const wrapper = mount(AskUserOptions, {
      props: { mode: 'plan', question: 'q', subTaskOptions: [{ order: 1, title: 'A' }], requiresReason: false, taskId: 't1', eventId: 'e1', choice: '' },
    })
    const customInput = wrapper
      .findAll('input')
      .find((i) => (i.attributes('placeholder') || '').includes('原因'))!
    await customInput.setValue('第二个子任务改用ABAC')
    await wrapper.findAll('button')[0]!.trigger('click') // 重新规划（最左）
    const emitted = wrapper.emitted('submitted')![0]![0] as SubmittedPayload
    expect(emitted).toMatchObject({ taskId: 't1', action: 'replan', keepOrders: [], custom: '第二个子任务改用ABAC', skip: false, eventId: 'e1' })
  })

  it('plan 历史回显：choice JSON 解析保留项并还原勾选态、只读', () => {
    const wrapper = mount(AskUserOptions, {
      props: {
        mode: 'plan',
        question: 'q',
        subTaskOptions: [{ order: 1, title: 'A' }, { order: 2, title: 'B' }, { order: 3, title: 'C' }],
        requiresReason: false,
        taskId: 't1',
        eventId: 'e1',
        choice: JSON.stringify({ action: 'confirm', keep_orders: [1, 3] }),
      },
    })
    expect(wrapper.text()).toContain('已确认执行')
    expect(wrapper.text()).toContain('保留项：1、3')
    const boxes = wrapper.findAll('input[type="checkbox"]')
    expect(boxes.length).toBe(3)
    expect((boxes[0]!.element as HTMLInputElement).checked).toBe(true)
    expect((boxes[1]!.element as HTMLInputElement).checked).toBe(false)
    expect((boxes[2]!.element as HTMLInputElement).checked).toBe(true)
    expect(wrapper.findAll('button')[0]!.attributes('disabled')).toBeDefined()
  })

  it('重新规划无原因时按钮禁用', async () => {
    const wrapper = mount(AskUserOptions, {
      props: { mode: 'plan', question: 'q', subTaskOptions: [{ order: 1, title: 'A' }], requiresReason: true, taskId: 't1', eventId: 'e1', choice: '' },
    })
    const replanBtn = wrapper.findAll('button')[0]! // 重新规划（最左；确认执行在最右）
    expect(replanBtn.attributes('disabled')).toBeDefined()
  })
})
