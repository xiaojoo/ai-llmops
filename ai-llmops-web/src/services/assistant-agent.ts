import { stream } from '@/utils/http/stream.ts'
import { http } from '@/utils/http'
import type { BaseResponse } from '@/models/base.ts'
import type {
  GetAssistantAgentMessagesWithPageRequest,
  GetAssistantAgentMessagesWithPageResponse,
} from '@/models/assistant-agent.ts'

enum API {
  BASE_ASSISTANT_AGENT_URL = '/assistant_agent',
}

// 与辅助Agent进行对话
export const assistantAgentChat = (
  query: string,
  image_urls: string[] = [],
  file_ids: string[] = [],
  onData: (event_response: Record<string, unknown>) => void,
  resume: boolean = false,
  signal?: AbortSignal,
) => {
  return stream({
    url: API.BASE_ASSISTANT_AGENT_URL + `/chat`,
    body: { query, image_urls, file_ids, resume },
    signal,
    onMessage: (data, event) => {
      onData({ event: event.event, data })
    },
  })
}

// 停止与辅助Agent进行对话
export const stopAssistantAgentChat = (task_id: string) =>
  http.post<BaseResponse<unknown>>(API.BASE_ASSISTANT_AGENT_URL + `/chat/${task_id}/stop`)

// 提交辅助 Agent 对话中 ask_user 交互式选项的选择结果（跳过时 choice 传 ''、skip 传 true）
export const submitAssistantAgentChoice = (
  task_id: string,
  body: { choice: string; skip: boolean; event_id?: string },
) =>
  http.post<BaseResponse<unknown>>(
    API.BASE_ASSISTANT_AGENT_URL + `/chat/${task_id}/choice`,
    body,
  )

// 获取当前登录账号的辅助 Agent 对话历史列表
export const getAssistantAgentMessagesWithPage = (req?: GetAssistantAgentMessagesWithPageRequest) =>
  http.get<GetAssistantAgentMessagesWithPageResponse>(
    API.BASE_ASSISTANT_AGENT_URL + '/messages',
    req,
  )

// 清空当前登录账号与辅助 Agent 的对话列表
export const deleteAssistantAgentConversation = () =>
  http.post<BaseResponse<unknown>>(API.BASE_ASSISTANT_AGENT_URL + '/delete_conversation')
