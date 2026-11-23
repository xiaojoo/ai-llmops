import type { BasePaginatorRequest, BasePaginatorResponse, BaseResponse } from '@/models/base.ts'
import type { ChatFileItem } from '@/models/chat-file.ts'

// 获取应用信息响应结构
export type GetAppResponse = BaseResponse<{
  id: string
  debug_conversation_id: string
  name: string
  icon: string
  description: string
  status: string
  app_type?: string
  draft_updated_at: number
  updated_at: number
  created_at: number
}>

// 新增应用请求结构
export type CreateAppRequest = {
  name: string
  icon: string
  description: string
  app_type?: string
  orchestrator_config?: OrchestratorConfig
}

// 编排型应用配置结构
export type OrchestratorConfig = {
  enable: boolean
  max_sub_tasks: number
  max_parallel: number
  sub_task_timeout: number
  resume_mode: 'auto' | 'manual'
}

// 获取特定应用的草稿配置响应结构
export type GetDraftAppConfigResponse = BaseResponse<{
  id: string
  model_config: {
    provider: string
    model: string
    parameters: Record<string, unknown>
  }
  dialog_round: number
  preset_prompt: string
  tools: {
    type: string
    provider: {
      id: string
      name: string
      label: string
      icon: string
      description: string
    }
    tool: {
      id: string
      name: string
      label: string
      description: string
      params: Record<string, unknown>
    }
  }[]
  skills: {
    id: string
    name: string
    icon: string
    description: string
  }[]
  workflows: {
    id: string
    name: string
    icon: string
    description: string
  }[]
  datasets: {
    id: string
    name: string
    icon: string
    description: string
  }[]
  retrieval_config: {
    retrieval_strategy: string
    k: number
    score: number
  }
  long_term_memory: {
    enable: boolean
    provider?: string
    team_id?: string
    agent_id?: string
    user_id?: string
  }
  opening_statement: string
  opening_questions: string[]
  speech_to_text: {
    enable: boolean
  }
  text_to_speech: {
    enable: boolean
    voice: string
    auto_play: boolean
  }
  suggested_after_answer: { enable: boolean }
  review_config: {
    enable: boolean
    keywords: string[]
    inputs_config: {
      enable: boolean
      preset_response: string
    }
    outputs_config: {
      enable: boolean
    }
  }
  orchestrator_config?: OrchestratorConfig
  updated_at: number
  created_at: number
}>

// 更新特定应用的草稿配置请求结构
export type UpdateDraftAppConfigRequest = {
  model_config?: {
    provider: string
    model: string
    parameters: Record<string, unknown>
  }
  dialog_round?: number
  preset_prompt?: string
  tools?: {
    type: string
    provider_id: string
    tool_id: string
    params: Record<string, unknown>
  }[]
  skills?: string[]
  workflows?: string[]
  datasets?: string[]
  retrieval_config?: {
    retrieval_strategy: string
    k: number
    score: number
  }
  long_term_memory?: {
    enable: boolean
    provider?: string
  }
  opening_statement?: string
  opening_questions?: string[]
  speech_to_text?: {
    enable: boolean
  }
  text_to_speech?: {
    enable: boolean
    voice: string
    auto_play: boolean
  }
  suggested_after_answer?: { enable: boolean }
  review_config?: {
    enable: boolean
    keywords: string[]
    inputs_config: {
      enable: boolean
      preset_response: string
    }
    outputs_config: {
      enable: boolean
    }
  }
  orchestrator_config?: OrchestratorConfig
}

// 获取应用的调试会话消息列表响应结构
export type GetDebugConversationMessagesWithPageResponse = BasePaginatorResponse<{
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
    model_name?: string
    thought: string
    observation: string
    llm_output?: string
    tool_calls?: {
      name?: string
      args?: Record<string, unknown>
      id?: string
      type?: string
    }[]
    message?: unknown[]
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
    total_token_count?: number
    total_price?: number
    created_at: number
    sub_task_id?: string | null
    sub_task_title?: string
  }[]
  is_archived: boolean
  can_resume?: boolean
  status?: string      // 消息状态投影：normal / stop / timeout / error
  run_status?: string  // 最新 run 终态：succeeded / cancelled / timed_out / failed / ''(无 run)
  created_at: number
}>

// 获取应用的发布历史配置列表分页响应结构
export type GetPublishHistoriesWithPageResponse = BasePaginatorResponse<{
  id: string
  version: number
  created_at: number
}>

// 更新应用请求结构
export type UpdateAppRequest = { name: string; icon: string; description: string }

// 获取应用分页列表数据请求
export type GetAppsWithPageRequest = BasePaginatorRequest & { search_word: string }

// 获取应用分页列表数据响应
export type GetAppsWithPageResponse = BasePaginatorResponse<{
  id: string
  name: string
  icon: string
  description: string
  preset_prompt: string
  model_config: {
    provider: string
    model: string
    /** 后端解析的提供商展示名（本地端点 →「本地离线模型」），缺失回退 provider key */
    provider_label?: string
    /** 后端解析的模型展示名（本地端点取 LOCAL_LLM_MODEL 实际值），缺失回退 model key */
    model_label?: string
  }
  status: string
  /** WebApp 凭证标识（/web_apps/{token} 路径中的 token） */
  token: string
  updated_at: number
  created_at: number
}>

// 获取应用发布配置响应结构
export type GetPublishedConfigResponse = BaseResponse<{
  web_app: {
    token: string
    status: string
  }
}>

// 重新生成WebApp凭证标识响应结构
export type RegenerateWebAppTokenResponse = BaseResponse<{
  token: string
}>
