import { http } from '@/utils/http'
import type {
  CreateWorkflowRequest,
  GetDraftGraphResponse,
  GetWorkflowResponse,
  GetWorkflowsWithPageRequest,
  GetWorkflowsWithPageResponse,
  UpdateDraftGraphRequest,
  UpdateWorkflowRequest,
} from '@/models/workflow.ts'
import type { BaseResponse } from '@/models/base.ts'
import { stream } from '@/utils/http/stream.ts'

enum API {
  WORKFLOWS = '/workflows',
}

// 获取工作流分页列表数据
export const getWorkflowsWithPage = (req: GetWorkflowsWithPageRequest) =>
  http.get<GetWorkflowsWithPageResponse>(API.WORKFLOWS, req)

// 在当前账号下新增工作流
export const createWorkflow = (req: CreateWorkflowRequest) =>
  http.post<BaseResponse<{ id: string }>>(API.WORKFLOWS, req)

// 修改工作流基础信息
export const updateWorkflow = (workflow_id: string, req: UpdateWorkflowRequest) =>
  http.post<BaseResponse<unknown>>(API.WORKFLOWS + `/${workflow_id}`, req)

// 获取工作流基础信息
export const getWorkflow = (workflow_id: string) =>
  http.get<GetWorkflowResponse>(API.WORKFLOWS + `/${workflow_id}`)

// 删除指定的工作流
export const deleteWorkflow = (workflow_id: string) =>
  http.post<BaseResponse<unknown>>(API.WORKFLOWS + `/${workflow_id}/delete`)

// 获取指定工作流的graph图草稿配置
export const getDraftGraph = (workflow_id: string) =>
  http.get<GetDraftGraphResponse>(API.WORKFLOWS + `/${workflow_id}/draft_graph`)

// 更新指定工作流的graph图草稿配置
export const updateDraftGraph = (workflow_id: string, req: UpdateDraftGraphRequest) =>
  http.post<BaseResponse<unknown>>(API.WORKFLOWS + `/${workflow_id}/draft_graph`, req)

// 发布指定的工作流
export const publishWorkflow = (workflow_id: string) =>
  http.post<BaseResponse<unknown>>(API.WORKFLOWS + `/${workflow_id}/publish`)

// 取消发布指定的工作流
export const cancelPublishWorkflow = (workflow_id: string) =>
  http.post<BaseResponse<unknown>>(API.WORKFLOWS + `/${workflow_id}/cancel_publish`)

// 工作流调试（支持 node_ids 指定单/多节点调试；无 node_ids 时兼容旧格式整图运行）
export const debugWorkflow = (
  workflow_id: string,
  inputs: Record<string, unknown>,
  onData: (event_response: Record<string, unknown>) => void,
  onError?: (event_response: Record<string, unknown>) => void,
  opts?: { node_ids?: string[] },
) => {
  const body: Record<string, unknown> =
    opts?.node_ids && opts.node_ids.length > 0
      ? { inputs, node_ids: opts.node_ids }
      : inputs
  return stream({
    url: API.WORKFLOWS + `/${workflow_id}/debug`,
    body,
    onMessage: (data, event) => {
      if (event.event === 'error') {
        onError?.({ event: event.event, data })
      } else {
        onData({ event: event.event, data })
      }
    },
  })
}
