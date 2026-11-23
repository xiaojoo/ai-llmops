import type { BaseResponse } from '@/models/base.ts'

// 自定义 API LLM 模型协议
export type CustomLlmModelProtocol = 'openai' | 'responses' | 'anthropic'

// 自定义 API LLM 模型（对应后端 GetCustomLlmModelResp）
export type CustomLlmModel = {
  id: string
  name: string
  protocol: string
  model_id: string
  base_url: string
  api_key: string
  features: string[]
  context_window: number
  max_output_tokens: number
  remark: string
  icon: string
  created_at: number
}

// 新增自定义 API LLM 模型请求结构（对应后端 CreateCustomLlmModelReq）
export type CreateCustomLlmModelPayload = {
  name: string
  protocol: string
  model_id: string
  base_url: string
  api_key: string
  features: string[]
  context_window: number
  max_output_tokens: number
  remark: string
  icon: string
}

// 更新自定义 API LLM 模型请求结构（对应后端 UpdateCustomLlmModelReq；
// api_key 为空时后端视为「保持原值」，不覆盖）
export type UpdateCustomLlmModelPayload = {
  name: string
  protocol: string
  model_id: string
  base_url: string
  api_key: string
  features: string[]
  context_window: number
  max_output_tokens: number
  remark: string
  icon: string
}

// 获取全部自定义模型列表响应
export type GetCustomLlmModelsResponse = BaseResponse<CustomLlmModel[]>

// 获取单个自定义模型详情响应
export type GetCustomLlmModelResponse = BaseResponse<CustomLlmModel>

// 协议下拉选项响应（对应后端 PROTOCOL_OPTIONS）
export type GetCustomLlmModelProtocolsResponse = BaseResponse<
  { label: string; value: string }[]
>
