import { type BaseResponse } from '@/models/base'

// 获取内置插件分类接口响应接口
export type GetCategoriesResponse = BaseResponse<
  Array<{
    category: string
    icon: string
    name: string
  }>
>

// 获取所有内置插件列表
export type GetBuiltinToolsResponse = BaseResponse<
  Array<{
    background: string
    category: string
    created_at: number
    description: string
    label: string
    name: string
    tools: Array<unknown>
  }>
>

// 获取指定内置插件详情
export type GetBuiltinToolResponse = BaseResponse<{
  name: string
  label: string
  description: string
  provider: {
    name: string
    label: string
    category: string
    background: string
    description: string
  }
  params: {
    name: string
    label: string
    type: string
    required: boolean
    default: unknown
    min: number
    max: number
    options: { value: string; label: string }[]
  }
}>

export interface ApiToolProvider {
  id: string
  name: string
}

export interface ToolItem {
  type: 'builtin_tool' | 'api_tool'
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
}

export interface ToolMeta {
  type: 'api_tool' | 'builtin_tool'
  provider: {
    id: string
    name: string
    label: string
    icon?: string
    description?: string
  }
  tool: {
    id: string
    name: string
    label: string
    description?: string
    params?: Record<string, unknown>
  }
}
