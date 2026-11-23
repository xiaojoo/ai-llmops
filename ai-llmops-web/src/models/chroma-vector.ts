import type { BaseResponse } from '@/models/base.ts'

// 向量记录
export type VectorItem = {
  id: string
  content: string
  metadata: Record<string, unknown>
  embedding_dims: number
  embedding_preview: number[]
}

// 向量记录详情（含完整向量）
export type VectorDetail = VectorItem & {
  embedding: number[]
}

// 分页响应
export type ListVectorsResponse = BaseResponse<{
  list: VectorItem[]
  paginator: {
    total_count: number
    total_pages: number
    current_page: number
    page_size: number
  }
}>

export type GetVectorResponse = BaseResponse<VectorDetail>
export type AddVectorResponse = BaseResponse<VectorItem>
export type UpdateVectorResponse = BaseResponse<VectorItem>

// 召回测试
export type RecallResult = {
  id: string
  content: string
  metadata: Record<string, unknown>
  score: number
  relevant: boolean
}

export type RecallTestResponse = BaseResponse<{
  query: string
  total: number
  results: RecallResult[]
}>

// 请求体
export type AddVectorReq = {
  id: string
  content: string
  metadata?: Record<string, unknown>
}

export type UpdateVectorReq = {
  content: string
  metadata?: Record<string, unknown>
}

export type RecallTestReq = {
  query: string
  top_k?: number
  search_type?: 'similarity' | 'mmr'
  score_threshold?: number | null
}
