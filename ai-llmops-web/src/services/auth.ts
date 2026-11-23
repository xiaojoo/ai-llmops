import { http } from '@/utils/http'
import type { PasswordLoginResponse } from '@/models/auth.ts'
import type { BaseResponse } from '@/models/base.ts'

enum API {
  AUTH_BASE = '/auth',
}

// 账号密码登录请求
export const passwordLogin = (email: string, password: string) =>
  http.post<PasswordLoginResponse>(API.AUTH_BASE + `/password_login`, { email, password })

// 退出登录请求
export const logout = () => http.post<BaseResponse<unknown>>(API.AUTH_BASE + `/logout`)
