import type {
  DeleteSkillResponse,
  GetSkillDetailResponse,
  GetSkillListWithPageRequest,
  GetSkillListWithPageResponse,
  GetSkillResponse,
  UploadSkillResponse,
} from '@/models/skill.ts'
import { http, httpUpload } from '@/utils/http'

enum API {
  SKILLS_BASE = '/skill',
}

// 上传技能（支持 .md 或 .zip）
export const uploadSkill = (file: File, icon: string = '') => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('icon', icon)
  return httpUpload.post<UploadSkillResponse>(API.SKILLS_BASE + '/upload', formData, {
    onProgress(percent) {
      console.log('上传进度:', percent)
    },
  })
}

// 获取技能分页列表
export const getSkillListWithPage = (req?: GetSkillListWithPageRequest) =>
  http.get<GetSkillListWithPageResponse>(API.SKILLS_BASE + '/skills', req)

// 获取技能详情
export const getSkill = (skill_id: string) =>
  http.get<GetSkillResponse>(API.SKILLS_BASE + `/${skill_id}`)

// 获取技能详情
export const getSkills = (skill_id: string) =>
  http.get<GetSkillDetailResponse>(API.SKILLS_BASE + `/skill_detail/${skill_id}`)

// 删除技能
export const deleteSkill = (skill_id: string) =>
  http.post<DeleteSkillResponse>(API.SKILLS_BASE + `/${skill_id}` + '/delete')

// 切换技能可见性（独占 <-> 分享）
export const toggleSkillVisibility = (skill_id: string) =>
  http.post<DeleteSkillResponse>(API.SKILLS_BASE + `/${skill_id}` + '/visibility')

// 下载技能
export const downloadSkill = async (skill_id: string): Promise<Blob> => {
  const { useCredentialStore } = await import('@/stores/credential.ts')
  const { apiPrefix } = await import('@/config')
  const credentialStore = useCredentialStore()
  const credential = credentialStore.credential

  const url = `${apiPrefix}/skill/${skill_id}/download`
  const headers = new Headers()
  if (credential?.access_token) {
    headers.set('Authorization', `Bearer ${credential.access_token}`)
  }
  const response = await fetch(url, {
    method: 'GET',
    headers,
  })

  if (!response.ok) {
    throw new Error(`下载失败: ${response.status}`)
  }

  return await response.blob()
}
