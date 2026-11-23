import { http } from '@/utils/http'
import type { GetCurrentUserResponse } from '@/models/account.ts'
import type { BaseResponse } from '@/models/base.ts'

enum API {
  ACCOUNT_BASE = '/account',
}

// 获取当前登录账号信息
export const getCurrentUser = () => http.get<GetCurrentUserResponse>(API.ACCOUNT_BASE)

// 修改当前登录账号密码
export const updatePasswordService = (password: string) =>
  http.post<BaseResponse<unknown>>(API.ACCOUNT_BASE + `/password`, { password })

// 修改当前登录账号名称
export const updateNameService = (name: string) =>
  http.post<BaseResponse<unknown>>(API.ACCOUNT_BASE + `/name`, { name })

// 修改当前登录账号头像
export const updateAvatar = (avatar: string) =>
  http.post<BaseResponse<unknown>>(API.ACCOUNT_BASE + `/avatar`, { avatar })
