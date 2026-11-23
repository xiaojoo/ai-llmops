import type { BaseResponse } from '@/models/base.ts'

export type GetCollectionsResponse = BaseResponse<{
  collections: string[]
}>

export type DocumentItem = {
  document_id: string
  dataset_id: string
  name?: string
  segment_count: number
}

export type GetDocumentsByCollectionResponse = BaseResponse<{
  collection: string
  document_count: number
  page: number
  page_size: number
  documents: DocumentItem[]
  is_memory_collection?: boolean
}>

export type SegmentItem = {
  id: string
  segment_id: string
  dataset_id: string
  document_id: string
  position: number
  keywords: string[]
  text: string
}

export type GetSegmentsByDocumentResponse = BaseResponse<{
  document_id: string
  total: number
  limit: number
  offset: number
  items: SegmentItem[]
}>

export type MetadataItem = {
  id: string
  segment_id: string
  document_id: string
  dataset_id: string
  position: number
  keywords: string[]
  content_length: number
}

export type GetMetadataResponse = BaseResponse<{
  total: number
  limit: number
  offset: number
  items: MetadataItem[]
}>

export type GetAllResponse = BaseResponse<{
  collection: string
  total: number
  limit: number
  offset: number
  items: SegmentItem[]
}>

export type RecallResult = {
  segment_id: string
  document_id: string
  content: string
  keywords: string[]
  position: number
  score: number
  distance: number
}

export type RecallTestResponse = BaseResponse<RecallResult[]>

export type RecallReq = {
  dataset_id: string
  document_id?: string
  query: string
  top_k?: number
  score_threshold?: number
}

export type DeleteDocumentReq = {
  dataset_id: string
}

export type DeleteMemoryReq = {
  collection_name: string
  app_id: string
}

export type GetMetadataReq = {
  dataset_id: string
  document_id?: string | null
  limit?: number
  offset?: number
}

export type GetAllReq = {
  collection_name?: string
  dataset_id?: string
  app_id?: string
  limit?: number
  offset?: number
}
