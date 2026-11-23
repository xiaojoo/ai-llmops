import { http } from '@/utils/http'
import type {
  GetBuiltinToolResponse,
  GetBuiltinToolsResponse,
  GetCategoriesResponse,
} from '@/models/builtin-tool.ts'

enum API {
  BUILTIN_TOOLS_CATEGORIES = '/builtin_tools/categories',
  BUILTIN_TOOLS = '/builtin_tools',
}

// 获取内置分类列表信息
export const getCategories = () => http.get<GetCategoriesResponse>(API.BUILTIN_TOOLS_CATEGORIES)

// 获取所有内置工具提供者列表
export const getBuiltinTools = () => http.get<GetBuiltinToolsResponse>(API.BUILTIN_TOOLS)

// 获取内置工具详情
export const getBuiltinTool = (provider_name: string, tool_name: string) =>
  http.get<GetBuiltinToolResponse>(API.BUILTIN_TOOLS + `/${provider_name}/tools/${tool_name}`)
