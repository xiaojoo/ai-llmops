import { http } from '@/utils/http'
import type { BaseResponse } from '@/models/base.ts'
import type {
  DeleteDocumentReq,
  DeleteMemoryReq,
  GetAllReq,
  GetAllResponse,
  GetCollectionsResponse,
  GetDocumentsByCollectionResponse,
  GetSegmentsByDocumentResponse,
  RecallReq,
  RecallTestResponse,
} from '@/models/weaviate-vector.ts'

enum API {
  BASE = '/weaviate/vector',
}

/** 获取所有 Collection 名称列表 */
export const getCollections = () => http.get<GetCollectionsResponse>(`${API.BASE}/collections`)

/** 获取指定 Collection 下的文档及分块数（支持分页，不需要 dataset_id） */
export const getDocumentsByCollection = (
  collection_name?: string,
  page = 1,
  page_size = 8,
) =>
  http.get<GetDocumentsByCollectionResponse>(`${API.BASE}/documents`, {
    ...(collection_name ? { collection_name } : {}),
    page,
    page_size,
  })

/** 获取指定文档下的所有分块（含原文，按 position 排序） */
export const getSegmentsByDocument = (
  dataset_id: string,
  document_id: string,
  limit = 100,
  offset = 0,
) =>
  http.get<GetSegmentsByDocumentResponse>(`${API.BASE}/all/dataset`, {
    dataset_id,
    document_id,
    limit,
    offset,
  })

/** 查询指定 Collection 下全量分块（含原文） */
export const getAll = (req: GetAllReq = {}) => {
  const params = Object.fromEntries(Object.entries(req).filter(([, v]) => v != null)) as Record<
    string,
    string | number | boolean
  >
  return http.get<GetAllResponse>(`${API.BASE}/all`, params)
}

/** 向量召回测试 */
export const recallTest = (req: RecallReq) =>
  http.post<RecallTestResponse>(`${API.BASE}/recall`, req)

/** 删除指定文档在 Weaviate 中的所有向量数据 */
export const deleteDocument = (req: DeleteDocumentReq) =>
  http.post<BaseResponse<{ message: string }>>(`${API.BASE}/delete`, req)

/** 按 app_id 清空记忆集合（EpisodicMemory 等）中的向量数据 */
export const deleteMemory = (req: DeleteMemoryReq) =>
  http.post<BaseResponse<{ message: string }>>(`${API.BASE}/memory/delete`, req)
