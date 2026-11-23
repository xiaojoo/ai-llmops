import type { BaseResponse } from '@/models/base'

// 获取内置应用分类响应结构体
export type GetBuiltinAppCategoriesResponse = BaseResponse<
  {
    category: string
    name: string
  }[]
>

// 获取内置应用列表响应结构体
export type GetBuiltinAppsResponse = BaseResponse<
  {
    id: string
    category: string
    name: string
    icon: string
    description: string
    model_config: {
      provider: string
      model: string
      /** 后端解析的提供商/模型展示名（本地端点模型取 LOCAL_LLM_MODEL 实际值） */
      provider_label?: string
      model_label?: string
    }
    created_at: number
  }[]
>
