import { http } from '@/utils/http'
import type { BaseResponse } from '@/models/base.ts'
import type {
  AddVectorReq,
  AddVectorResponse,
  GetVectorResponse,
  ListVectorsResponse,
  RecallTestReq,
  RecallTestResponse,
  UpdateVectorReq,
  UpdateVectorResponse,
} from '@/models/chroma-vector.ts'

enum API {
  BASE = '/chroma',
}

export const listVectors = (page = 1, pageSize = 20) =>
  http.get<ListVectorsResponse>(`${API.BASE}/vector`, { page, page_size: pageSize })

export const getVector = (docId: string) =>
  http.get<GetVectorResponse>(`${API.BASE}/${docId}/vectors`)

export const addVector = (req: AddVectorReq) =>
  http.post<AddVectorResponse>(`${API.BASE}/vector/add_vector`, req)

export const updateVector = (docId: string, req: UpdateVectorReq) =>
  http.post<UpdateVectorResponse>(`${API.BASE}/${docId}/update_vector`, req)

export const deleteVector = (docId: string) =>
  http.post<BaseResponse<unknown>>(`${API.BASE}/${docId}/delete_vector`)

export const clearVectors = () =>
  http.post<BaseResponse<{ deleted: number }>>(`${API.BASE}/vector/clear`)

export const recallTest = (req: RecallTestReq) =>
  http.post<RecallTestResponse>(`${API.BASE}/vector/recall`, req)

export const syncDocuments = () =>
  http.post<BaseResponse<{ before: number; after: number; added: number }>>(
    `${API.BASE}/vector/sync`,
  )
