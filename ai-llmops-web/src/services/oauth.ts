import { http } from '@/utils/http'
import type { AuthorizeResponse, ProviderResponse } from '@/models/oauth.ts'

enum API {
  OAUTH_BASE = '/oauth',
}

// 获取指定第三方授权服务的重定向地址
export const provider = (provider_name: string) =>
  http.get<ProviderResponse>(API.OAUTH_BASE + `/${provider_name}`)

// 指定第三方授权服务认证地址
export const authorize = (provider_name: string, code: string) =>
  http.post<AuthorizeResponse>(API.OAUTH_BASE + `/authorize/${provider_name}`, { code })
