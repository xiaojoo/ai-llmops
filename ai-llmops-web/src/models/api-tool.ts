import type { BasePaginatorResponse, BaseResponse } from '@/models/base.ts'

export type HeaderItem = {
  key: string
  value: string
}

export type ToolInput = {
  name: string
  type: string
  required: boolean
  description: string
}

export type ToolItem = {
  name: string
  description: string
  method: string
  path: string
  inputs: ToolInput[]
}

// 获取自定义API插件响应接口
export type GetApiToolProvidersWithPageResponse = BasePaginatorResponse<{
  id: string
  name: string
  icon: string
  description: string
  headers: HeaderItem[]
  tools: ToolItem[]
  created_at: number
}>

// 新增自定义API插件提供者请求结构（请求体）
export type CreateApiToolProviderRequest = {
  name: string
  icon: string
  openapi_schema: string
  headers: HeaderItem[]
}

// 更新自定义API工具提供者请求结构（请求体）
export type UpdateApiToolProviderRequest = {
  name: string
  icon: string
  openapi_schema: string
  headers: HeaderItem[]
}

// 获取自定义API工具提供者响应结构
export type GetApiToolProviderResponse = BaseResponse<{
  name: string
  icon: string
  openapi_schema: string
  headers: HeaderItem[]
  created_at: number
}>

// 获取自定义API工具详情
export type GetApiToolResponse = BaseResponse<{
  id: string
  name: string
  description: string
  provider: {
    id: string
    name: string
    icon: string
    headers: { key: string; value: string }[]
    description: string
  }
  inputs: {
    type: string
    name: string
    required: boolean
    description: string
  }
}>
