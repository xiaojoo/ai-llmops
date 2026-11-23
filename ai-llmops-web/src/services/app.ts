import { stream } from '@/utils/http/stream.ts'
import { http } from '@/utils/http'
import type {
  CreateAppRequest,
  GetAppResponse,
  GetAppsWithPageRequest,
  GetAppsWithPageResponse,
  GetDebugConversationMessagesWithPageResponse,
  GetDraftAppConfigResponse,
  GetPublishedConfigResponse,
  GetPublishHistoriesWithPageResponse,
  RegenerateWebAppTokenResponse,
  UpdateAppRequest,
  UpdateDraftAppConfigRequest,
} from '@/models/app.ts'
import type {
  BasePaginatorRequest,
  BaseResponse,
  GetDebugConversationMessagesWithPageRequest,
} from '@/models/base.ts'

enum API {
  APP = '/apps',
}

export const debugApp = (
  app_id: string,
  query: string,
  image_urls: string[] = [],
  file_ids: string[] = [],
  onData: (event_response: Record<string, unknown>) => void,
  resume: boolean = false,
  signal?: AbortSignal,
  resume_message_id: string = '',
) => {
  return stream({
    url: API.APP + `/${app_id}/conversations`,
    body: { query, image_urls, file_ids, resume, resume_message_id },
    signal,
    onMessage: (data, event) => {
      onData({ event: event.event, data })
    },
  })
}

// 获取应用基础信息
export const getApp = (app_id: string) => http.get<GetAppResponse>(API.APP + `/${app_id}`)

// 在个人空间下新增应用
export const createApp = (req: CreateAppRequest) =>
  http.post<BaseResponse<{ id: string }>>(API.APP, req)

// 修改指定应用
export const updateApp = (app_id: string, req: UpdateAppRequest) =>
  http.post<BaseResponse<unknown>>(API.APP + `/${app_id}`, req)

// 删除指定应用
export const deleteApp = (app_id: string) =>
  http.post<BaseResponse<unknown>>(API.APP + `/${app_id}/delete`)

// 拷贝指定的应用
export const copyApp = (app_id: string) =>
  http.post<BaseResponse<{ id: string }>>(API.APP + `/${app_id}/copy`)

// 获取应用分页列表数据
export const getAppsWithPage = (req: GetAppsWithPageRequest) =>
  http.get<GetAppsWithPageResponse>(API.APP, req)

// 获取特定应用的草稿配置信息
export const getDraftAppConfig = (app_id: string) =>
  http.get<GetDraftAppConfigResponse>(API.APP + `/${app_id}/draft_app_config`)

// 更新特定应用的草稿配置信息
export const updateDraftAppConfig = (app_id: string, req: UpdateDraftAppConfigRequest) =>
  http.post<BaseResponse<unknown>>(API.APP + `/${app_id}/draft_app_config`, req)

// 获取应用的调试长记忆
export const getDebugConversationSummary = (app_id: string) =>
  http.get<BaseResponse<{ summary: string }>>(API.APP + `/${app_id}/summary`)

// 更新应用的调试记忆
export const updateDebugConversationSummary = (app_id: string, summary: string) =>
  http.post<BaseResponse<unknown>>(API.APP + `/${app_id}/summary`, { summary })

// 停止某次应用的调试会话
export const stopDebugChat = (app_id: string, task_id: string) =>
  http.post<BaseResponse<unknown>>(API.APP + `/${app_id}/conversations/tasks/${task_id}/stop`)

// 提交应用调试会话中 ask_user 交互式选项的选择结果（跳过时 choice 传 ''、skip 传 true）
export const submitDebugChoice = (
  app_id: string,
  task_id: string,
  body: { choice: string; skip: boolean; event_id?: string },
) =>
  http.post<BaseResponse<unknown>>(
    API.APP + `/${app_id}/conversations/tasks/${task_id}/choice`,
    body,
  )

// 获取应用的调试会话消息列表
export const getDebugConversationMessagesWithPage = (
  app_id: string,
  req?: GetDebugConversationMessagesWithPageRequest,
) =>
  http.get<GetDebugConversationMessagesWithPageResponse>(
    API.APP + `/${app_id}/conversations/messages`,
    req,
  )

// 清空应用的调试会话记录
export const deleteDebugConversation = (app_id: string) =>
  http.post<BaseResponse<unknown>>(API.APP + `/${app_id}/conversations/delete_debug_conversation`)

// 更新/发布应用的配置信息
export const publish = (app_id: string) =>
  http.post<BaseResponse<unknown>>(API.APP + `/${app_id}/publish`)

// 取消指定应用的发布
export const cancelPublish = (app_id: string) =>
  http.post<BaseResponse<unknown>>(API.APP + `/${app_id}/cancel_publish`)

// 获取应用的发布历史列表消息
export const getPublishHistoriesWithPage = (app_id: string, req: BasePaginatorRequest) =>
  http.get<GetPublishHistoriesWithPageResponse>(API.APP + `/${app_id}/publish_histories`, req)

// 回退指定的历史配置到草稿
export const fallbackHistoryToDraft = (app_id: string, app_config_version_id: string) =>
  http.post<BaseResponse<unknown>>(API.APP + `/${app_id}/fallback_history`, {
    app_config_version_id,
  })

// 获取指定应用的发布配置信息
export const getPublishedConfig = (app_id: string) =>
  http.get<GetPublishedConfigResponse>(API.APP + `/${app_id}/published_config`)

// 重新生成WebApp的凭证标识
export const regenerateWebAppToken = (app_id: string) =>
  http.post<RegenerateWebAppTokenResponse>(
    API.APP + `/${app_id}/published_config/regenerate_web_app_token`,
  )
