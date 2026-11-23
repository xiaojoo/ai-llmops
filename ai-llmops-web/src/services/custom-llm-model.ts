import { http } from '@/utils/http'
import type {
  CreateCustomLlmModelPayload,
  GetCustomLlmModelProtocolsResponse,
  GetCustomLlmModelResponse,
  GetCustomLlmModelsResponse,
  UpdateCustomLlmModelPayload,
} from '@/models/custom-llm-model.ts'
import type { BaseResponse } from '@/models/base.ts'

enum API {
  CUSTOM_LLM_MODELS = '/custom_llm_models',
}

// 获取当前账号下全部自定义 API LLM 模型列表
export const getCustomLlmModels = () =>
  http.get<GetCustomLlmModelsResponse>(API.CUSTOM_LLM_MODELS)

// 获取指定自定义模型的详细信息
export const getCustomLlmModel = (id: string) =>
  http.get<GetCustomLlmModelResponse>(API.CUSTOM_LLM_MODELS + `/${id}`)

// 新增自定义 API LLM 模型
export const createCustomLlmModel = (payload: CreateCustomLlmModelPayload) =>
  http.post<BaseResponse<unknown>, CreateCustomLlmModelPayload>(API.CUSTOM_LLM_MODELS, payload)

// 更新自定义 API LLM 模型（api_key 为空时后端保持原值）
export const updateCustomLlmModel = (id: string, payload: UpdateCustomLlmModelPayload) =>
  http.put<BaseResponse<unknown>, UpdateCustomLlmModelPayload>(
    API.CUSTOM_LLM_MODELS + `/${id}`,
    payload,
  )

// 删除自定义 API LLM 模型（逻辑删除）
export const deleteCustomLlmModel = (id: string) =>
  http.delete<BaseResponse<unknown>>(API.CUSTOM_LLM_MODELS + `/${id}`)

// 获取协议下拉选项
export const getCustomLlmModelProtocols = () =>
  http.get<GetCustomLlmModelProtocolsResponse>(API.CUSTOM_LLM_MODELS + '/protocols')
