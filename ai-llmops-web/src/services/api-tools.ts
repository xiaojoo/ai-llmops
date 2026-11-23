import { http } from '@/utils/http'
import type {
  CreateApiToolProviderRequest,
  GetApiToolProviderResponse,
  GetApiToolProvidersWithPageResponse,
  GetApiToolResponse,
  UpdateApiToolProviderRequest,
} from '@/models/api-tool.ts'
import type { BaseResponse } from '@/models/base.ts'

enum API {
  API_TOOLS = '/api_tools',
  API_TOOLS_VALIDATE = '/api_tools/validate_openapi_schema',
}

// 获取自定义API列表分页数据
export const getApiToolProvidersWithPage = (
  current_page: number = 1,
  page_size: number = 20,
  search_word: string = '',
) =>
  http.get<GetApiToolProvidersWithPageResponse>(API.API_TOOLS, {
    current_page,
    page_size,
    search_word,
  })

// 校检OpenApi Schema数据
export const validateOpenAPISchema = (openapi_schema: string) =>
  http.post<BaseResponse<unknown>>(API.API_TOOLS_VALIDATE, {
    openapi_schema,
  })

// 创建自定义API工具提供者
export const createApiToolProvider = (req: CreateApiToolProviderRequest) =>
  http.post<BaseResponse<unknown>>(API.API_TOOLS, req)

// 删除自定义API工具提供者
export const deleteApiToolProvider = (provider_id: string) =>
  http.post<BaseResponse<unknown>>(API.API_TOOLS + `/${provider_id}/delete`)

// 更新自定义API工具提供者
export const updateApiToolProvider = (provider_id: string, req: UpdateApiToolProviderRequest) =>
  http.post<BaseResponse<unknown>>(API.API_TOOLS + `/${provider_id}`, req)

// 查看自定义API工具提供者
export const getApiToolProvider = (provider_id: string) =>
  http.get<GetApiToolProviderResponse>(API.API_TOOLS + `/${provider_id}`)

// 获取API工具详情信息
export const getApiTool = (provider_id: string, tool_name: string) =>
  http.get<GetApiToolResponse>(API.API_TOOLS + `/${provider_id}/tools/${tool_name}`)

// 调试API工具（传参数调用接口）
export const debugApiTool = (provider_id: string, tool_name: string, arguments_: Record<string, unknown>) =>
  http.post<BaseResponse<{ result: string }>>(
    API.API_TOOLS + `/${provider_id}/tools/${tool_name}/debug`,
    { arguments: arguments_ },
  )
