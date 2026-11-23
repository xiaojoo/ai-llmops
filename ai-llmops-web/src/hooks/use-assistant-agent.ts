import { ref } from 'vue'
import {
  assistantAgentChat,
  deleteAssistantAgentConversation,
  getAssistantAgentMessagesWithPage,
  stopAssistantAgentChat,
} from '@/services/assistant-agent.ts'
import { Message } from '@arco-design/web-vue'
import type { GetAssistantAgentMessagesWithPageResponse } from '@/models/assistant-agent.ts'

export const useAssistantAgentChat = () => {
// 定义自定义hooks所需数据
  const loading = ref(false)
  // 当前 SSE 请求的取消控制器：停止响应时先客户端中断，页面立即停止渲染
  let abortController: AbortController | null = null

// 定义辅助Agent会话处理器
  const handleAssistantAgentChat = async (
    query: string,
    image_urls: string[],
    file_ids: string[] = [],
    onData: (event_response: Record<string, unknown>) => void,
    resume: boolean = false,
  ) => {
    try {
      loading.value = true
      abortController = new AbortController()
      await assistantAgentChat(query, image_urls, file_ids, onData, resume, abortController.signal)
    } finally {
      loading.value = false
      abortController = null
    }
  }

  // 客户端立即中断 SSE 流（与后端 stop 接口双保险）
  const abort = () => {
    abortController?.abort()
    abortController = null
  }

  return { loading, handleAssistantAgentChat, abort }
}

export const useStopAssistantAgentChat = () => {
  const loading = ref(false)

// 定义停止辅助Agent会话处理器
  const handleStopAssistantAgentChat = async (task_id: string) => {
    try {
      loading.value = true
      await stopAssistantAgentChat(task_id)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleStopAssistantAgentChat }
}

export const useGetAssistantAgentMessagesWithPage = () => {
  const loading = ref(false)
  const messages = ref<GetAssistantAgentMessagesWithPageResponse['data']['list']>([])
  const created_at = ref(0)
  const defaultPaginator = {
    current_page: 1,
    page_size: 5,
    total_page: 0,
    total_record: 0,
  }
  const paginator = ref({ ...defaultPaginator })

  const loadAssistantAgentMessages = async (init: boolean = false) => {
// 判断是否是初始化，如果是则先初始化分页器
    if (init) {
      paginator.value = { ...defaultPaginator }
      created_at.value = 0
    } else if (paginator.value.current_page > paginator.value.total_page) {
      return
    }

    try {
      loading.value = true
      const resp = await getAssistantAgentMessagesWithPage({
        current_page: paginator.value.current_page,
        page_size: paginator.value.page_size,
        created_at: created_at.value,
      })

      const data = resp.data

      paginator.value = data.paginator

      if (paginator.value.current_page <= paginator.value.total_page) {
        paginator.value.current_page += 1
      }

      if (init) {
        messages.value = data.list
      } else {
        messages.value.push(...data.list)
        created_at.value = data.list[0]?.created_at ?? 0
      }
    } finally {
      loading.value = false
    }
  }

  return { loading, messages, paginator, loadAssistantAgentMessages }
}

export const useDeleteAssistantAgentConversation = () => {
  const loading = ref(false)

  const handleDeleteAssistantAgentConversation = async () => {
    try {
      loading.value = true
      const resp = await deleteAssistantAgentConversation()
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleDeleteAssistantAgentConversation }
}
