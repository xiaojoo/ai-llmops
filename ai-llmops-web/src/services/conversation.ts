import { http } from '@/utils/http'
import type {
  GetConversationMessagesWithPageRequest,
  GetConversationMessagesWithPageResponse,
} from '@/models/conversation.ts'
import type { BaseResponse } from '@/models/base.ts'

enum API {
  CONVERSATIONS = '/conversations',
}

// 获取指定会话的消息列表
export const getConversationMessages = (
  conversation_id: string,
  req: GetConversationMessagesWithPageRequest,
) =>
  http.get<GetConversationMessagesWithPageResponse>(
    API.CONVERSATIONS + `/${conversation_id}/messages`,
    req,
  )

// 删除特定的会话
export const deleteConversation = (conversation_id: string) =>
  http.post<BaseResponse<unknown>>(API.CONVERSATIONS + `/${conversation_id}/delete`)

// 删除特定会话下的指定消息
export const deleteMessage = (conversation_id: string, message_id: string) =>
  http.post<BaseResponse<unknown>>(API.CONVERSATIONS + `/${conversation_id}/messages/${message_id}`)

// 获取指定会话的名称
export const getConversationName = (conversation_id: string) =>
  http.get<BaseResponse<{ name: string }>>(API.CONVERSATIONS + `/${conversation_id}/name`)

// 修改指定会话的名称
export const updateConversationName = (conversation_id: string, name: string) =>
  http.post<BaseResponse<unknown>>(API.CONVERSATIONS + `/${conversation_id}/name`, { name })

// 置顶或取消置顶某个会话
export const updateConversationIsPinned = (conversation_id: string, is_pinned: boolean) =>
  http.post<BaseResponse<unknown>>(API.CONVERSATIONS + `/${conversation_id}/is_pinned`, { is_pinned })

// 更新指定消息的用户反馈（'' 取消 / like 点赞 / dislike 点踩）
export const updateMessageFeedback = (
  conversation_id: string,
  message_id: string,
  feedback: string,
) =>
  http.post<BaseResponse<unknown>>(
    API.CONVERSATIONS + `/${conversation_id}/messages/${message_id}/feedback`,
    { feedback },
  )
