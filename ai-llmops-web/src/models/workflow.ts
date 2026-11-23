// 获取工作流分页列表请求
import type { BasePaginatorRequest, BasePaginatorResponse, BaseResponse } from '@/models/base.ts'

export type GetWorkflowsWithPageRequest = BasePaginatorRequest & {
  search_word?: string
  status?: string
}

// 获取工作流分页列表响应
export type GetWorkflowsWithPageResponse = BasePaginatorResponse<{
  id: string
  name: string
  tool_call_name: string
  icon: string
  description: string
  status: string
  is_debug_passed: boolean
  node_count: number
  published_at: number
  updated_at: number
}>

// 新增工作流请求
export type CreateWorkflowRequest = {
  name: string
  tool_call_name: string
  icon: string
  description: string
}

// 修改工作流基础信息请求
export type UpdateWorkflowRequest = {
  name: string
  tool_call_name: string
  icon: string
  description: string
}

// 获取工作流基础信息响应
export type GetWorkflowResponse = BaseResponse<{
  id: string
  name: string
  tool_call_name: string
  icon: string
  description: string
  status: string
  is_debug_passed: boolean
  node_count: number
  published_at: number
  updated_at: number
  created_at: number
}>

// 工作流图画布节点（后端存储结构，含扩展属性）
export type DraftGraphNode = {
  id: string
  node_type: string
  position: { x: number; y: number }
  [key: string]: unknown
}

// 工作流图画布边（后端存储结构，含扩展属性）
export type DraftGraphEdge = {
  id: string
  source: string
  target: string
  [key: string]: unknown
}

// 获取指定工作流图草稿配置
export type GetDraftGraphResponse = BaseResponse<{
  nodes: DraftGraphNode[]
  edges: DraftGraphEdge[]
}>

// 更新指定工作流图草稿配置
export type UpdateDraftGraphRequest = {
  nodes: DraftGraphNode[]
  edges: DraftGraphEdge[]
}
