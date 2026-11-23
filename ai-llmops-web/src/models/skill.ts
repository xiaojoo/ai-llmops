// 获取技能列表分页响应结构
import type { BasePaginatorResponse, BaseResponse } from '@/models/base.ts'

// 获取技能详情响应结构
export type GetSkillResponse = BaseResponse<{
  id: string
  name: string
  description: string
  icon: string
  visibility: string
  file_content: string | null
  created_at: number
  updated_at: number
}>

export type GetSkillDetailResponse = BaseResponse<{
  id: string
  name: string
  description: string
  icon: string
  visibility: string
  files: SkillFile[]
  created_at: number
  updated_at: number
}>

// 获取技能分页列表响应结构
export type GetSkillListWithPageResponse = BasePaginatorResponse<{
  id: string
  name: string
  description: string
  icon: string
  visibility: string
  is_owner: boolean
  created_at: number
  updated_at: number
}>

// 上传技能响应结构
export type UploadSkillResponse = BaseResponse<null>

// 删除技能响应结构
export type DeleteSkillResponse = BaseResponse<null>

// 上传技能请求结构
export type UploadSkillRequest = {
  file: File
}

// 获取技能分页列表请求结构
export type GetSkillListWithPageRequest = {
  current_page?: number
  page_size?: number
  search_word?: string
}

export type SkillFile = {
  path: string
  content: string | null
  is_binary: boolean
}
