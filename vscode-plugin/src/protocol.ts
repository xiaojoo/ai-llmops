/**
 * 纯逻辑层（不依赖 vscode，可单测）——对应 Java 侧 WebAppBridge 中的 static 纯函数。
 * 协议解析、消息/会话映射、SSE 事件数据构建、项目文件路径安全解析。
 */
import * as fs from 'node:fs'
import * as path from 'node:path'
import type { ParsedEvent } from './api/sse'

// ===== 常量（与 Java 侧一致） =====

export const MAX_MENTION_FILES = 2000
export const MAX_TOTAL_FILE_IDS = 5
export const MAX_PROJECT_FILE_BYTES = 10 * 1024 * 1024
export const CHAT_TIMEOUT_MS = 60_000

// ===== 协议类型 =====

export interface BridgeReply {
  ok: boolean
  data?: unknown
  error?: string
}

/** 前端 ChatMessage 的最小形状（与 src/components/agent-chat/types.ts 对应） */
export interface ChatMessageLike {
  id: string
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  conversationId?: string
  messageId?: string
  taskId?: string
  feedback?: '' | 'like' | 'dislike'
  latency?: number
  totalTokenCount?: number
  files?: { id: string; label: string }[]
  /** 消息状态投影：normal / stop / timeout / error */
  status?: string
  /** 最新 run 终态：succeeded / cancelled / timed_out / failed / ''(无 run) */
  runStatus?: string
  /** 可断点续跑：显示"继续执行"按钮 */
  canResume?: boolean
}

/** 前端 ChatSession 的最小形状 */
export interface ChatSessionLike {
  id: string
  title: string
  time: string
  dialogRound?: number
}

// ===== 响应构造 =====

export function ok(data?: unknown): BridgeReply {
  return { ok: true, data }
}

export function err(error: string): BridgeReply {
  return { ok: false, error }
}

// ===== 请求解析 =====

export interface ParsedRequest {
  action: string
  payload: Record<string, unknown>
}

/** 解析 JS 传来的 JSON，提取 action + payload；畸形返回空 action */
export function parseRequest(json: string): ParsedRequest {
  if (!json || !json.trim()) return { action: '', payload: {} }
  try {
    const obj = JSON.parse(json) as Record<string, unknown>
    const action = typeof obj['action'] === 'string' ? obj['action'] : ''
    const payload =
      obj['payload'] && typeof obj['payload'] === 'object' && !Array.isArray(obj['payload'])
        ? (obj['payload'] as Record<string, unknown>)
        : {}
    return { action, payload }
  } catch {
    return { action: '', payload: {} }
  }
}

export function strField(payload: Record<string, unknown>, field: string): string | null {
  const v = payload[field]
  if (typeof v === 'string') return v
  if (typeof v === 'boolean' || typeof v === 'number') return String(v)
  return null
}

export function arrField(payload: Record<string, unknown>, field: string): unknown[] {
  const v = payload[field]
  return Array.isArray(v) ? v : []
}

// ===== 消息/会话映射 =====

/** 后端消息行 → 前端 ChatMessage 数组（移植 WebAppBridge.toChatMessages） */
export function toChatMessages(rows: Record<string, unknown>[], conversationId: string): ChatMessageLike[] {
  const ordered = [...rows].reverse() // 后端倒序返回，页面按正序渲染
  const arr: ChatMessageLike[] = []
  for (const m of ordered) {
    const id = typeof m['id'] === 'string' ? m['id'] : ''
    const query = typeof m['query'] === 'string' ? m['query'] : ''
    const answer = typeof m['answer'] === 'string' ? m['answer'] : ''
    if (query && query.trim()) {
      const user: ChatMessageLike = { id: id + '-u', role: 'user', content: query, conversationId }
      const fileUrls = m['file_urls']
      if (Array.isArray(fileUrls) && fileUrls.length > 0) {
        const files: { id: string; label: string }[] = []
        for (const fe of fileUrls) {
          if (!fe || typeof fe !== 'object') continue
          const fo = fe as Record<string, unknown>
          const fid = typeof fo['id'] === 'string' ? fo['id'] : ''
          const name = typeof fo['name'] === 'string' ? fo['name'] : ''
          if (!fid && !name) continue
          files.push({ id: fid, label: name || fid })
        }
        if (files.length > 0) user.files = files
      }
      arr.push(user)
    }
    // 终态（stop/timeout/error）即使 answer 为空也渲染——它们是"发生过、可查看/可续跑"的一轮，
    // 且 can_resume 需透传给前端显示"继续执行"按钮。
    const isTerminal = ['stop', 'timeout', 'error'].includes(String(m['status'] ?? ''))
    if ((answer && answer.trim()) || isTerminal) {
      const assistant: ChatMessageLike = {
        id,
        messageId: id,
        conversationId,
        role: 'assistant',
        content: answer,
      }
      if (typeof m['latency'] === 'number') assistant.latency = m['latency']
      if (typeof m['total_token_count'] === 'number') assistant.totalTokenCount = m['total_token_count']
      if (typeof m['feedback'] === 'string') assistant.feedback = m['feedback'] as ChatMessageLike['feedback']
      if (typeof m['status'] === 'string') assistant.status = m['status']
      if (typeof m['run_status'] === 'string') assistant.runStatus = m['run_status']
      if (typeof m['can_resume'] === 'boolean') assistant.canResume = m['can_resume']
      arr.push(assistant)
    }
  }
  return arr
}

/** 会话列表行 → 前端 ChatSession 数组 */
export function toChatSessions(convs: Record<string, unknown>[]): ChatSessionLike[] {
  return convs.map((c) => {
    const item: ChatSessionLike = {
      id: typeof c['id'] === 'string' ? c['id'] : '',
      title: typeof c['name'] === 'string' ? c['name'] : '',
      time: typeof c['created_at'] === 'string' ? c['created_at'] : '',
    }
    if (typeof c['dialog_round'] === 'number') item.dialogRound = c['dialog_round']
    return item
  })
}

/** 应用信息 → 前端 getWebApp/switchWebApp 返回结构 */
export function toWebAppInfo(info: Record<string, unknown> | null, token: string): Record<string, unknown> {
  const result: Record<string, unknown> = {
    name: info && typeof info['name'] === 'string' ? info['name'] : '',
    icon: info && typeof info['icon'] === 'string' ? info['icon'] : '',
    token,
  }
  // dialog_round 由后端放在 app_config 内（GetWebAppResp.process_data），不是顶层。
  // 之前读顶层 info['dialog_round'] 恒为 undefined，导致插件永远显示默认 3 轮，
  // 而 Web 端读 web_app.app_config.dialog_round 是对的。
  const appConfig = info && (info['app_config'] as Record<string, unknown> | undefined)
  if (appConfig && typeof appConfig['dialog_round'] === 'number') {
    result['dialogRound'] = appConfig['dialog_round']
  }
  // v1 未实现语音转文字：强制隐藏麦克风按钮（对应 readSpeechToTextEnabled 置 false）
  result['speechToTextEnabled'] = false
  return result
}

// ===== SSE 事件数据构建 =====

/** messageDelta 事件数据 */
export function deltaJson(evt: ParsedEvent): Record<string, unknown> {
  const o: Record<string, unknown> = { content: evt.content }
  if (evt.taskId) o['taskId'] = evt.taskId
  if (evt.runId) o['runId'] = evt.runId
  if (evt.conversationId) o['conversationId'] = evt.conversationId
  if (evt.messageId) o['messageId'] = evt.messageId
  return o
}

/** ask_user 事件数据（下划线 → 驼峰转换，与 Java askUserJson 一致） */
export function askUserJson(evt: ParsedEvent): Record<string, unknown> {
  const o: Record<string, unknown> = { taskId: evt.taskId ?? '' }
  if (evt.runId) o['runId'] = evt.runId
  const raw = evt.raw
  if (raw) {
    if (typeof raw['id'] === 'string') o['eventId'] = raw['id']
    if (typeof raw['question'] === 'string') o['question'] = raw['question']
    if (typeof raw['choice'] === 'string') o['choice'] = raw['choice']
    if (typeof raw['allow_custom'] === 'boolean') o['allowCustom'] = raw['allow_custom']
    if (Array.isArray(raw['options'])) o['options'] = raw['options']
    const subTasks = raw['sub_task_options']
    const isPlan = Array.isArray(subTasks) && subTasks.length > 0
    if (isPlan) o['subTaskOptions'] = subTasks
    o['mode'] = isPlan ? 'plan' : 'option'
  }
  if (!('eventId' in o)) o['eventId'] = ''
  if (!('allowCustom' in o)) o['allowCustom'] = true
  return o
}

export function errorJson(message: string): Record<string, unknown> {
  return { message: message ?? '' }
}

// ===== 项目文件路径安全解析 =====

/** 只能读工作区内文件（移植 WebAppBridge.resolveProjectPath） */
export function resolveProjectPath(basePath: string, relPath: string): string | null {
  if (!basePath || !relPath || !relPath.trim()) return null
  const base = path.resolve(basePath)
  const candidate = path.resolve(base, relPath)
  if (!candidate.startsWith(base + path.sep) && candidate !== base) return null
  try {
    const realBase = fs.realpathSync(base)
    const real = fs.realpathSync(candidate) // 解析符号链接；不存在会抛异常
    if (!real.startsWith(realBase + path.sep) && real !== realBase) return null
    if (!fs.statSync(real).isFile()) return null
    return real
  } catch {
    return null
  }
}
