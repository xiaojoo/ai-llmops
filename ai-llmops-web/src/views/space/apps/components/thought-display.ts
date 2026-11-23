// 运行流程 / 任务详情 共用的事件展示工具（保证两侧步骤名、徽章、摘要完全一致）
import { QueueEvent } from '@/config'

export type ThoughtLike = {
  id?: string
  position?: number
  event: string
  thought?: string
  observation?: string
  llm_output?: string
  tool_calls?: { name?: string; args?: Record<string, unknown>; id?: string; type?: string }[]
  tool?: string
  tool_input?: Record<string, unknown>
  trace?: unknown[]
  latency?: number
  total_token_count?: number
  total_price?: number
  model_name?: string
  created_at?: number
  sub_task_id?: string | null
  sub_task_title?: string
}

// 类型徽章：model=紫 / tool=橙 / ctx=绿
export const typeClassOf = (t: ThoughtLike): 'model' | 'tool' | 'ctx' => {
  if (t.event === QueueEvent.agentMessage || t.event === QueueEvent.agentThought) return 'model'
  if (t.event === QueueEvent.agentAction || t.event === QueueEvent.datasetRetrieval) return 'tool'
  return 'ctx'
}
export const typeLabelOf = (t: ThoughtLike): string =>
  typeClassOf(t) === 'model' ? 'MODEL' : typeClassOf(t) === 'tool' ? 'TOOL' : 'CONTEXT'

// 步骤中文名（LangSmith 风格：每一步大模型做了什么）
export const stepLabelOf = (t: ThoughtLike): string => {
  switch (t.event) {
    case QueueEvent.longTermMemoryRecall:
      return '长期记忆召回'
    case QueueEvent.agentThought:
      return 'LLM 调用'
    case QueueEvent.agentMessage:
      return 'LLM 输出'
    case QueueEvent.agentAction:
      return '调用工具'
    case QueueEvent.datasetRetrieval:
      return '搜索知识库'
    case QueueEvent.subTaskPlan:
      return '任务分解计划'
    case QueueEvent.subTaskStart:
      return '子任务开始'
    case QueueEvent.subTaskEnd:
      return '子任务完成'
    case QueueEvent.askUser:
      return '询问用户'
    case QueueEvent.error:
      return '执行出错'
    case QueueEvent.timeout:
      return '执行超时'
    case QueueEvent.stop:
      return '已停止'
    default:
      return t.event
  }
}

export const isErrorEvent = (t: ThoughtLike): boolean =>
  [QueueEvent.error, QueueEvent.timeout, QueueEvent.stop].includes(t.event)

// 工具事件中文名
export const toolEventLabel = (event: string): string =>
  event === QueueEvent.datasetRetrieval ? '知识库检索' : '工具调用'

// 工具输入单行摘要（列表行内展示用）
export const compactInput = (input: Record<string, unknown> | undefined): string => {
  if (input === null || input === undefined) return ''
  let s = ''
  try {
    s = typeof input === 'string' ? input : JSON.stringify(input)
  } catch {
    return ''
  }
  return s.length > 90 ? `${s.slice(0, 90)}…` : s
}

// 超长文本截断（suffix 指定尾部省略号：详情用单 …，其余默认 ……
export const truncateWithDots = (s: unknown, max = 90, suffix = '……'): string => {
  const text = String(s ?? '').replace(/\s+/g, ' ').trim()
  return text.length > max ? `${text.slice(0, max)}${suffix}` : text
}

// 步骤行右侧命令胶囊（运行流程 / 任务详情共用）：
// 工具调用 → 工具名；LLM 调用/输出 → 模型名 + 耗时 + tokens；子任务完成 → 耗时 + tokens；
// 失败/超时/停止 → 状态文案；其余 → 耗时
export const stepAmountOf = (t: ThoughtLike): string => {
  const lat = (t.latency || 0).toFixed(2)
  if (t.event === QueueEvent.error) return '失败'
  if (t.event === QueueEvent.timeout) return '超时'
  if (t.event === QueueEvent.stop) return '已停止'
  if (t.event === QueueEvent.subTaskStart) return '进行中'
  if (t.event === QueueEvent.agentAction || t.event === QueueEvent.datasetRetrieval)
    return t.tool || `${lat}s`
  if (t.event === QueueEvent.subTaskEnd) {
    let s = `${lat}s`
    if (t.total_token_count) s += ` · ${t.total_token_count} Tokens`
    return s
  }
  if (t.event === QueueEvent.agentThought || t.event === QueueEvent.agentMessage) {
    let s = ''
    if (t.model_name) s += t.model_name
    if (t.latency) s += `${s ? ' · ' : ''}${lat}s`
    if (t.total_token_count) s += ` · ${t.total_token_count} Tokens`
    return s || `${lat}s`
  }
  const text = (t.thought || t.observation || '').replace(/\s+/g, ' ').trim()
  if (text) return truncateWithDots(text, 16)
  return `${lat}s`
}

// 步骤行下方详情（内容部分信息，运行流程 / 任务详情共用）：
// LLM 步骤 → 输出/思考摘要；工具步骤 → 输入摘要；其余 → 原文摘要。均截断为 ……
export const stepDetailOf = (t: ThoughtLike): string => {
  switch (t.event) {
    case QueueEvent.agentThought:
      return truncateWithDots(t.llm_output || t.thought || '', 90, '…')
    case QueueEvent.agentMessage:
      return truncateWithDots(t.thought || t.llm_output || '', 90, '…')
    case QueueEvent.agentAction:
    case QueueEvent.datasetRetrieval:
      return compactInput(t.tool_input)
    case QueueEvent.longTermMemoryRecall:
      return truncateWithDots(t.thought || t.observation || '', 90, '…')
    case QueueEvent.subTaskStart:
      return t.sub_task_title ? `开始执行：${t.sub_task_title}` : ''
    case QueueEvent.subTaskEnd:
      return t.observation ? truncateWithDots(t.observation, 90, '…') : ''
    case QueueEvent.error:
    case QueueEvent.timeout:
    case QueueEvent.stop:
      return truncateWithDots(t.observation || t.thought || '', 90, '…')
    default:
      return truncateWithDots(t.thought || t.observation || '', 90, '…')
  }
}

// 任务详情列表行内容（HTML，含工具名高亮）
export const rowContentOf = (t: ThoughtLike): string => {
  switch (t.event) {
    case QueueEvent.agentThought: {
      // LLM 调用：优先展示输出全文（工具调用轮含工具声明）
      const out = t.llm_output || t.thought || ''
      if (t.tool_calls?.length) {
        const names = t.tool_calls.map((c) => c.name || '').filter(Boolean).join(', ')
        return names ? `${out || '调用工具'} → ${names}` : out
      }
      return out
    }
    case QueueEvent.agentMessage:
      return t.thought || t.llm_output || ''
    case QueueEvent.agentAction:
    case QueueEvent.datasetRetrieval: {
      const name = t.tool || toolEventLabel(t.event)
      const input = compactInput(t.tool_input)
      const nameHtml = `<span class="tool-name">${escapeHtml(name)}</span>`
      return input ? `${nameHtml} <span class="tool-in">${escapeHtml(input)}</span>` : nameHtml
    }
    case QueueEvent.subTaskStart:
      return `开始执行：${t.sub_task_title || ''}`
    case QueueEvent.subTaskEnd: {
      let text = `执行完成 · 耗时 ${(t.latency || 0).toFixed(2)}s`
      if (t.total_token_count) text += ` · ${t.total_token_count} Tokens`
      return text
    }
    case QueueEvent.subTaskPlan:
      return '生成任务分解计划'
    case QueueEvent.error:
    case QueueEvent.timeout:
    case QueueEvent.stop:
      return t.observation || t.thought || t.event
    default:
      return t.thought || t.event
  }
}

export const escapeHtml = (s: unknown): string =>
  String(s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c,
  )
