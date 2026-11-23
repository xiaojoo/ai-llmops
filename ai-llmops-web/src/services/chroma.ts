import { http, httpUpload } from '@/utils/http'
import type { BaseResponse } from '@/models/base.ts'
import type {
  DeleteChromaFileRequest,
  GetChromaFilesResponse,
  UploadChromaFileResponse,
} from '@/models/chroma.ts'

enum API {
  BASE_CHROMA_URL = '/chroma',
}

// 获取文件列表
export const getChromaFiles = () => http.get<GetChromaFilesResponse>(API.BASE_CHROMA_URL + '/list')

// 上传文件
export const uploadChromaFile = (file: File) => {
  const formData = new FormData()
  formData.append('file', file)
  return httpUpload.post<UploadChromaFileResponse>(API.BASE_CHROMA_URL + '/upload', formData)
}

// 下载文件
export const downloadChromaFile = async (path: string): Promise<Blob> => {
  const { useCredentialStore } = await import('@/stores/credential.ts')
  const { apiPrefix } = await import('@/config')
  const credentialStore = useCredentialStore()
  const credential = credentialStore.credential

  const url = `${apiPrefix}${API.BASE_CHROMA_URL}/download?path=${encodeURIComponent(path)}`
  const headers = new Headers()
  if (credential?.access_token) {
    headers.set('Authorization', `Bearer ${credential.access_token}`)
  }

  const response = await fetch(url, { method: 'GET', headers })
  if (!response.ok) throw new Error(`下载失败: ${response.status}`)
  return response.blob()
}

// 删除文件
export const deleteChromaFile = (req: DeleteChromaFileRequest) =>
  http.post<BaseResponse<unknown>>(API.BASE_CHROMA_URL + '/delete', req)
