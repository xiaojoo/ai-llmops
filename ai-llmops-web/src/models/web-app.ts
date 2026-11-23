// 获取WebApp基础信息响应结构
import type { BasePaginatorResponse, BaseResponse } from '@/models/base.ts'
import type { ChatFileItem } from '@/models/chat-file.ts'

export type GetWebAppResponse = BaseResponse<{
  id: string
  icon: string
  name: string
  description: string
  app_config: {
    opening_statement: string
    opening_questions: string[]
    suggested_after_answer: {
      enable: boolean
    }
    dialog_round?: number
  }
}>

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

// 获取WebApp会话消息列表响应结构
export type GetWebAppConversationsResponse = BaseResponse<
  {
    id: string
    name: string
    summary: string
    created_at: number
    dialog_round?: number | null
  }[]
>

// 与WebApp对话请求结构
export type WebAppChatRequest = {
  conversation_id?: string
  query: string
  image_urls?: string[]
  file_ids?: string[]
  resume?: boolean
  // 断点续跑时被恢复的原始消息 id（后端按 message_id 定位断点）
  resume_message_id?: string
}
