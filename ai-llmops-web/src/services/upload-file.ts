import { http, httpUpload } from '@/utils/http'
import type { UploadFileResponse, UploadImageResponse } from '@/models/upload-file.ts'

enum API {
  UPLOAD_BASE = '/upload-files',
}

// 获取内置分类列表信息
export const uploadImage = (image: File) => {
  const formData = new FormData()
  formData.append('file', image)

  return httpUpload.post<UploadImageResponse>(API.UPLOAD_BASE + '/image', formData, {
    onProgress(percent) {
      console.log('上传进度:', percent)
    },
  })
}

// 上传文件服务
export const uploadFile = (file: File) => {
  const formData = new FormData()
  formData.append('file', file)

  return httpUpload.post<UploadFileResponse>(API.UPLOAD_BASE + '/file', formData, {
    onProgress(percent) {
      console.log('上传进度:', percent)
    },
  })
}

// 查询已上传但尚未创建文档（孤儿）的文件列表
export const getPendingUploadFiles = () =>
  http.get<UploadFileResponse & { data: UploadFileResponse['data'][] }>(
    API.UPLOAD_BASE + '/pending',
  )

// 删除已上传但未创建文档的文件（同步删除 OSS 对象）
export const deletePendingUploadFile = (uploadFileId: string) =>
  http.post<{ code: string; message: string }>(API.UPLOAD_BASE + `/${uploadFileId}/delete`)

// 按需获取文件可访问 URL（历史附件链接过期后刷新用）
export const getUploadFileUrl = (uploadFileId: string) =>
  http.get<{ code: string; message: string; data: { url: string } }>(
    API.UPLOAD_BASE + `/${uploadFileId}/url`,
  )
