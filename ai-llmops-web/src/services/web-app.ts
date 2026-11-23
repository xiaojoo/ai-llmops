import { http } from '@/utils/http'
import { stream } from '@/utils/http/stream.ts'
import type {
  GetWebAppConversationsResponse,
  GetWebAppResponse,
  WebAppChatRequest,
} from '@/models/web-app.ts'
import type { BaseResponse } from '@/models/base.ts'

enum API {
  WEB_APPS = '/web_apps',
}

// 根据标识获取指定WebApp基础信息
export const getWebApp = (token: string) => http.get<GetWebAppResponse>(API.WEB_APPS + `/${token}`)

// SSE 回调载荷：lastEventId 是后端帧的 `id:` 序号，断流重连时作为 last_event_id 回传
export type WebAppSseFrame = {
  event: string
  data: unknown
  lastEventId?: string
}

// 与指定WebApp进行对话
export const webAppChat = (
  token: string,
  req: WebAppChatRequest,
  onData: (event_response: WebAppSseFrame) => void,
  signal?: AbortSignal,
) => {
  return stream({
    url: API.WEB_APPS + `/${token}/chat`,
    body: req,
    signal,
    onMessage: (data, event) => {
      onData({ event: event.event, data, lastEventId: event.id })
    },
  })
}

// 断流重连续传：按 last_event_id 重放已缓冲帧后订阅该 run 的实时队列。
// 刷新/切走页面后重新进入会话时用它接回仍在生成的回答（run_id 来自消息列表的 run_id 字段）。
export const resumeWebAppChat = (
  token: string,
  run_id: string,
  last_event_id: number,
  onData: (event_response: WebAppSseFrame) => void,
  signal?: AbortSignal,
) => {
  return stream({
    url: API.WEB_APPS + `/${token}/chat/${run_id}/resume`,
    method: 'GET',
    signal,
    onMessage: (data, event) => {
      onData({ event: event.event, data, lastEventId: event.id })
    },
  })
}

// 停止与指定 WebApp 进行对话
export const stopWebAppChat = (token: string, task_id: string) =>
  http.post<BaseResponse<unknown>>(API.WEB_APPS + `/${token}/chat/${task_id}/stop`)

// 提交 WebApp 对话中 ask_user 交互式选项的选择结果（跳过时 choice 传 ''、skip 传 true）
export const submitWebAppChoice = (
  token: string,
  task_id: string,
  body: { choice: string; skip: boolean; event_id?: string },
) =>
  http.post<BaseResponse<unknown>>(API.WEB_APPS + `/${token}/chat/${task_id}/choice`, body)

// 获取指定应用的会话列表
export const getWebAppConversations = (token: string, is_pinned: boolean) =>
  http.get<GetWebAppConversationsResponse>(API.WEB_APPS + `/${token}/conversations`, {
    is_pinned,
  })

// 更新指定会话的设置（短期记忆窗口轮数；dialog_round=null 恢复应用默认）
export const updateWebAppConversationSettings = (
  token: string,
  conversationId: string,
  body: { dialog_round: number | null },
) => http.post<BaseResponse<unknown>>(API.WEB_APPS + `/${token}/conversations/${conversationId}/settings`, body)
