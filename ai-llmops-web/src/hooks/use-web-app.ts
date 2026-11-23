import { ref } from 'vue'
import {
  getWebApp,
  getWebAppConversations,
  resumeWebAppChat,
  stopWebAppChat,
  webAppChat,
} from '@/services/web-app.ts'
import type { WebAppSseFrame } from '@/services/web-app.ts'
import type { GetWebAppConversationsResponse, GetWebAppResponse, WebAppChatRequest } from '@/models/web-app.ts'

export const useGetWebApp = () => {
  const loading = ref<boolean>(false)
  const web_app = ref<Partial<GetWebAppResponse['data']>>({})

  const loadWebApp = async (token: string) => {
    try {
      loading.value = true
      const resp = await getWebApp(token)
      web_app.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, web_app, loadWebApp }
}

export const useWebAppChat = () => {
  const loading = ref<boolean>(false)
  // 当前 SSE 请求的取消控制器：**只在用户显式「停止响应」时 abort**。
  // 切会话/离开页面不再走这里——后端 run 与事件队列独立于本条 HTTP 连接存在，
  // 连接断了不等于任务终止，回来按 run_id 重连即可接上。
  let abortController: AbortController | null = null

  // 两条流（首次提问 / 断流重连）共用同一份 loading 与控制器生命周期
  const withStream = async (invoke: (signal: AbortSignal) => Promise<unknown>) => {
    try {
      loading.value = true
      abortController = new AbortController()
      await invoke(abortController.signal)
    } finally {
      loading.value = false
      abortController = null
    }
  }

// 定义 WebApp 对话处理器
  const handleWebAppChat = (
    token: string,
    req: WebAppChatRequest,
    onData: (event_response: WebAppSseFrame) => void,
  ) => withStream((signal) => webAppChat(token, req, onData, signal))

  // 断流重连：刷新或重新进入页面后，按 run_id 接回仍在生成的 run（不新建 run，只重挂事件流）
  const handleResumeWebAppChat = (
    token: string,
    runId: string,
    lastEventId: number,
    onData: (event_response: WebAppSseFrame) => void,
  ) => withStream((signal) => resumeWebAppChat(token, runId, lastEventId, onData, signal))

  // 客户端立即中断 SSE 流（与后端 stop 接口双保险：即使后端停止传播延迟，
  // 前端也立刻停止接收/渲染新的流式内容）
  const abort = () => {
    abortController?.abort()
    abortController = null
  }

  return { loading, handleWebAppChat, handleResumeWebAppChat, abort }
}

export const useStopWebAppChat = () => {
  const loading = ref<boolean>(false)

// 定义停止 WebApp 对话处理器
  const handleStopWebAppChat = async (token: string, task_id: string) => {
    try {
      loading.value = true
      await stopWebAppChat(token, task_id)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleStopWebAppChat }
}

export const useGetAppConversations = () => {
  const loading = ref<boolean>(false)
  const pinned_conversations = ref<GetWebAppConversationsResponse['data']>([])
  const unpinned_conversations = ref<GetWebAppConversationsResponse['data']>([])

  const loadWebAppConversations = async (token: string) => {
    try {
      loading.value = true

      const [pinned_resp, unpinned_resp] = await Promise.all([
        getWebAppConversations(token, true),
        getWebAppConversations(token, false),
      ])

      pinned_conversations.value = pinned_resp.data
      unpinned_conversations.value = unpinned_resp.data
    } finally {
      loading.value = false
    }
  }

  return {
    loading,
    pinned_conversations,
    unpinned_conversations,
    loadWebAppConversations,
  }
}
