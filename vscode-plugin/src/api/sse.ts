/**
 * SSE 事件语义解析（移植自 idea-plugin 的 SseEventParser.java）。
 * 把后端原始 SSE 事件转换成 UI 渲染所需的统一结构。纯逻辑，无 IO，可单测。
 */

export type SseEventKind = 'thought' | 'messageDelta' | 'end' | 'askUser' | 'error' | 'ignore' | 'localToolCall'

export interface ParsedEvent {
  kind: SseEventKind
  content: string
  taskId?: string
  raw?: Record<string, unknown>
  conversationId?: string
  messageId?: string
  runId?: string
}

function getString(obj: Record<string, unknown> | null | undefined, key: string): string | null {
  if (!obj) return null
  const v = obj[key]
  return typeof v === 'string' ? v : null
}

function tryParseObject(data: string): Record<string, unknown> | null {
  if (!data || !data.trim()) return null
  try {
    const e: unknown = JSON.parse(data)
    return e && typeof e === 'object' && !Array.isArray(e) ? (e as Record<string, unknown>) : null
  } catch {
    return null
  }
}

/**
 * 从 agent_message 数据中提取增量文本。
 * 后端真实结构：助手回复的增量在 answer 字段（逐事件累加拼接即完整回复）；
 * message 数组是完整会话历史（system 预设 + human 提问），不能作为回复文本。
 * 注意：answer 即使为空白（如 "\n\n"）也是有效增量，必须原样返回。
 */
function extractMessageContent(obj: Record<string, unknown> | null): string {
  if (!obj) return ''
  if (typeof obj['answer'] === 'string') return obj['answer'] as string
  // 兼容旧结构: { message: [{ content }] } / { message: [{ data: { content } }] } / { message: "..." } / { llm_output }
  const msg = obj['message']
  if (Array.isArray(msg)) {
    const parts: string[] = []
    for (const item of msg) {
      if (item && typeof item === 'object') {
        const it = item as Record<string, unknown>
        const content = it['content']
        if (typeof content === 'string') {
          parts.push(content)
          continue
        }
        const data = it['data']
        if (data && typeof data === 'object' && !Array.isArray(data)) {
          const nested = (data as Record<string, unknown>)['content']
          if (typeof nested === 'string') parts.push(nested)
        }
      } else if (typeof item === 'string') {
        parts.push(item)
      }
    }
    return parts.join('')
  }
  if (typeof msg === 'string') return msg
  return getString(obj, 'llm_output') ?? ''
}

export function parseSseEvent(eventName: string, data: string): ParsedEvent {
  const obj = tryParseObject(data)
  const taskId = getString(obj, 'task_id') ?? undefined
  const runId = getString(obj, 'run_id') ?? undefined
  const conversationId = getString(obj, 'conversation_id') ?? undefined
  const messageId = getString(obj, 'message_id') ?? undefined
  const raw = obj ?? undefined

  switch (eventName) {
    case 'agent_message': {
      const content = extractMessageContent(obj)
      return { kind: 'messageDelta', content, taskId, runId, raw, conversationId, messageId }
    }
    case 'agent_thought': {
      const text = getString(obj, 'thought') || getString(obj, 'llm_output') || ''
      return { kind: 'thought', content: text, taskId, runId, raw, conversationId, messageId }
    }
    case 'agent_end':
      return { kind: 'end', content: '', taskId, runId, raw, conversationId, messageId }
    case 'ask_user': {
      const question = getString(obj, 'question') ?? ''
      return { kind: 'askUser', content: question, taskId, runId, raw, conversationId, messageId }
    }
    case 'local_tool_call': {
      // 本地工具运行时：把原始 payload 整体交给 bridge 解析执行（tool/tool_input/tool_call_id/task_id）
      return { kind: 'localToolCall', content: '', taskId, runId, raw, conversationId, messageId }
    }
    case 'error': {
      // 后端 error 事件把原因放在 observation（部分场景用 message）；优先取 observation
      const text = getString(obj, 'observation') || getString(obj, 'message') || ''
      return { kind: 'error', content: text, taskId, runId, raw, conversationId, messageId }
    }
    case 'stop':
    case 'timeout':
      return { kind: 'end', content: '', taskId, runId, raw, conversationId, messageId }
    case 'ping':
    default:
      return { kind: 'ignore', content: '', taskId, runId, raw, conversationId, messageId }
  }
}
