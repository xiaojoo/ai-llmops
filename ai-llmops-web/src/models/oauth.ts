import type { BaseResponse } from '@/models/base.ts'

export type ProviderResponse = BaseResponse<{
  redirect_url: string
}>

export type AuthorizeResponse = BaseResponse<{
  access_token: string
  expire_at: number
}>
