import { http } from '@/utils/http'
import type { BaseResponse } from '@/models/base.ts'

enum API {
  SYSTEM_CONFIG = '/settings/config',
  MEMORY_TEST = '/memory/test',
}

// 读取系统配置（敏感项脱敏为 '********'）
export const getSystemConfig = () => http.get<BaseResponse<Record<string, string>>>(API.SYSTEM_CONFIG)

// 保存系统配置（{config_key: value}，空字符串清空该项）
export const saveSystemConfig = (configs: Record<string, string>) =>
  http.put<BaseResponse<null>>(API.SYSTEM_CONFIG, configs)

// 测试腾讯记忆连通性（可选 app_id 叠加应用作用域覆盖；
// endpoint/api_key/service_id/admin_key 非空时覆盖系统已保存配置，供保存前测试）
export const testMemoryConfig = (payload: {
  app_id?: string
  team_id?: string
  agent_id?: string
  user_id?: string
  endpoint?: string
  api_key?: string
  service_id?: string
  admin_key?: string
}) => http.post<BaseResponse<{ ok: boolean; message: string }>>(API.MEMORY_TEST, payload)
