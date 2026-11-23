import type { BaseResponse } from '@/models/base.ts'

// 单个文件信息
export type ChromaFileItem = {
  name: string
  size: number
  modified: string
  path: string
}

// 文件列表响应
export type GetChromaFilesResponse = BaseResponse<{
  files: ChromaFileItem[]
}>

// 上传文件响应
export type UploadChromaFileResponse = BaseResponse<{
  file: ChromaFileItem
}>

// 删除文件请求
export type DeleteChromaFileRequest = {
  path: string
}
