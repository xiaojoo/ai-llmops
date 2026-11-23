import { http } from '@/utils/http'
import type {
  GetBuiltinAppCategoriesResponse,
  GetBuiltinAppsResponse,
} from '@/models/builtin-app.ts'
import type { BaseResponse } from '@/models/base.ts'

enum API {
  BUILTIN_APPS_BASE = '/builtin_apps',
}

// 获取内置应用分类列表
export const getBuiltinAppCategories = () =>
  http.get<GetBuiltinAppCategoriesResponse>(API.BUILTIN_APPS_BASE + `/categories`)

// 获取内置应用列表信息
export const getBuiltinApps = () => http.get<GetBuiltinAppsResponse>(API.BUILTIN_APPS_BASE)

// 将指定 Agent 模板添加到工作区
export const addBuiltinAppToSpace = (builtin_app_id: string) =>
  http.post<BaseResponse<{ id: string }>>(API.BUILTIN_APPS_BASE + `/add_builtin_app_to_space`, {
    builtin_app_id,
  })
