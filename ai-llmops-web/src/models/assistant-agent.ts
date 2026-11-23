// 获取辅助Agent会话消息分页列表请求结构
import type { BasePaginatorRequest, BasePaginatorResponse } from '@/models/base.ts'
import type { ChatFileItem } from '@/models/chat-file.ts'

export type { ChatFileItem } from '@/models/chat-file.ts'

export type GetAssistantAgentMessagesWithPageRequest = BasePaginatorRequest & {
  created_at?: number
}

// 获取辅助Agent会话消息分页列表响应结构
export type GetAssistantAgentMessagesWithPageResponse = BasePaginatorResponse<{
  id: string
  conversation_id: string
  query: string
  image_urls: string[]
  file_urls: ChatFileItem[]
  answer: string
  total_token_count: number
  latency: number
  feedback: string
  error: string
  agent_thoughts: {
    id: string
    position: number
    event: string
    thought: string
    observation: string
    tool: string
    tool_input: Record<string, unknown>
    trace?: {
      round: number
      strategy: string
      query: string
      k: number
      hits: number
      sufficient: boolean
      score: number
      missing: string
    }[]
    latency: number
    created_at: number
    sub_task_id?: string | null
    sub_task_title?: string
  }[]
  can_resume?: boolean
  status?: string      // 消息状态投影：normal / stop / timeout / error
  run_status?: string  // 最新 run 终态：succeeded / cancelled / timed_out / failed / ''(无 run)
  created_at: number
}>
