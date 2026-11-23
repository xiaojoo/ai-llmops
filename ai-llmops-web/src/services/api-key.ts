import { http } from '@/utils/http'
import type { BasePaginatorRequest, BaseResponse } from '@/models/base.ts'
import type {
  CreateApiKeyRequest,
  GetApiKeysWithPageResponse,
  UpdateApiKeyRequest,
} from '@/models/api-key.ts'

enum API {
  OPEN_API_BASE = '/openapi',
}

export const getApiKeysWithPage = (req: BasePaginatorRequest) =>
  http.get<GetApiKeysWithPageResponse>(API.OPEN_API_BASE + `/api_keys`, req)

export const createApiKey = (req: CreateApiKeyRequest) =>
  http.post<BaseResponse<unknown>>(API.OPEN_API_BASE + `/api_keys`, req)

export const deleteApiKey = (api_key_id: string) =>
  http.post<BaseResponse<unknown>>(API.OPEN_API_BASE + `/api_keys/${api_key_id}/delete_api_key`)

export const updateApiKey = (api_key_id: string, req: UpdateApiKeyRequest) =>
  http.post<BaseResponse<unknown>>(API.OPEN_API_BASE + `/api_keys/${api_key_id}`, req)

export const updateApiKeyIsActive = (api_key_id: string, is_active: boolean) =>
  http.post<BaseResponse<unknown>>(API.OPEN_API_BASE + `/api_keys/${api_key_id}/is_active`, {
    is_active,
  })
