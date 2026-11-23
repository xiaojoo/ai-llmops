import {
  cancelPublish,
  copyApp,
  createApp,
  debugApp,
  deleteApp,
  deleteDebugConversation,
  fallbackHistoryToDraft,
  getApp,
  getAppsWithPage,
  getDebugConversationMessagesWithPage,
  getDebugConversationSummary,
  getDraftAppConfig,
  getPublishedConfig,
  getPublishHistoriesWithPage,
  publish,
  regenerateWebAppToken,
  stopDebugChat,
  updateApp,
  updateDebugConversationSummary,
  updateDraftAppConfig,
} from '@/services/app.ts'
import { onMounted, reactive, ref } from 'vue'
import { Message, Modal } from '@arco-design/web-vue'
import type {
  CreateAppRequest,
  GetAppResponse,
  GetAppsWithPageResponse,
  GetDebugConversationMessagesWithPageResponse,
  GetDraftAppConfigResponse,
  GetPublishedConfigResponse,
  GetPublishHistoriesWithPageResponse,
  UpdateAppRequest,
  UpdateDraftAppConfigRequest,
} from '@/models/app.ts'
import { useRoute, useRouter } from 'vue-router'

export const useGetApp = () => {
// 定义hooks所需的基础数据
  // 注意：初始值用空对象而非 null——下游组件（DetailView 等）的 app prop 是
  // required: true，null 会触发 Vue 的 prop 类型检查警告
  const loading = ref(false)
  const app = ref<Partial<GetAppResponse['data']>>({})

  const loadApp = async (app_id: string) => {
    try {
      loading.value = true
      const resp = await getApp(app_id)
      app.value = resp.data
    } finally {
      loading.value = false
    }
  }
  return { loading, app, loadApp }
}

export const useGetAppsWithPage = () => {
  const route = useRoute()
  const loading = ref(false)
  const apps = ref<GetAppsWithPageResponse['data']['list']>([])
  const defaultPaginator = {
    current_page: 1,
    page_size: 20,
    total_page: 0,
    total_record: 0,
  }

  const paginator = ref({ ...defaultPaginator })

  const loadApps = async (init: boolean = false) => {
// 判断是否是初始化，如果是的话则先初始化分页器
    if (init) {
      paginator.value = { ...defaultPaginator }
    } else if (paginator.value.current_page > paginator.value.total_page) {
      return
    }
    try {
// 将loading值改为true并调用api接口获取数据
      loading.value = true
      const resp: GetAppsWithPageResponse = await getAppsWithPage({
        current_page: paginator.value.current_page,
        page_size: paginator.value.page_size,
        search_word: String(route.query?.search_word ?? ''),
      })
      const data = resp.data

      paginator.value = data.paginator

      if (paginator.value.current_page <= paginator.value.total_page) {
        paginator.value.current_page += 1
      }
      if (init) {
        apps.value = data.list
      } else {
        apps.value.push(...data.list)
      }
    } finally {
      loading.value = false
    }
  }
  return { loading, apps, paginator, loadApps }
}

export const useCreateApp = () => {
  const router = useRouter()
  const loading = ref(false)

  const handleCreateApp = async (req: CreateAppRequest) => {
    try {
      loading.value = true
      const resp = await createApp(req)
      Message.success({ content: '新增Agent应用成功' })
      await router.push({
        name: 'space-apps-detail',
        params: { app_id: resp.data.id },
      })
    } finally {
      loading.value = false
    }
  }
  return { loading, handleCreateApp }
}

export const useUpdateApp = () => {
  const loading = ref(false)

  const handleUpdateApp = async (app_id: string, req: UpdateAppRequest) => {
    try {
      loading.value = true
      const resp = await updateApp(app_id, req)
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }
  return { loading, handleUpdateApp }
}

export const useCopyApp = () => {
  const router = useRouter()
  const loading = ref(false)

  const handleCopyApp = async (app_id: string) => {
    try {
      loading.value = true
      const resp = await copyApp(app_id)

      Message.success({ content: '创建应用副本成功' })
      await router.push({ name: 'space-apps-detail', params: { app_id: resp.data.id } })
    } finally {
      loading.value = false
    }
  }
  return { loading, handleCopyApp }
}

export const useDeleteApp = () => {
  const handleDeleteApp = async (app_id: string, callback?: () => void) => {
    Modal.warning({
      title: '要删除该应用吗？',
      content:
        '删除应用后，发布的WebApp、开放API以及关联的社交媒体平台均无法使用该Agent应用，如果需要暂停应用，可以使用禁用功能',
      hideCancel: false,
      onOk: async (): Promise<void> => {
        try {
// 点击确定后向API接口发起请求
          const resp = await deleteApp(app_id)
          Message.success(resp.message)
        } finally {
// 调用callback函数指定回调功能
          callback?.()
        }
      },
    })
  }
  return { handleDeleteApp }
}

export const usePublish = () => {
  const loading = ref(false)

  const handlePublish = async (app_id: string) => {
    try {
      loading.value = true
      const resp = await publish(app_id)
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }
  return { loading, handlePublish }
}

export const useCancelPublish = () => {
  const loading = ref(false)

  const handleCancelPublish = async (app_id: string, callback?: () => void) => {
    Modal.warning({
      title: '要取消发布该Agent应用？',
      content:
        '取消发布后，WebApp以及发布的社交平台均无法使用该Agent，如需更新WebApp地址，请使用地址重新生成功能',
      hideCancel: false,
      onOk: async () => {
        try {
          loading.value = true
          const resp = await cancelPublish(app_id)
          Message.success(resp.message)
        } finally {
          loading.value = false
          callback?.()
        }
      },
    })
  }
  return { loading, handleCancelPublish }
}

export const useGetPublishHistoriesWithPage = () => {
  const loading = ref(false)
  const defaultPaginator = {
    current_page: 1,
    page_size: 10,
    total_page: 0,
    total_record: 0,
  }
  const publishHistories = reactive<GetPublishHistoriesWithPageResponse['data']['list']>([])
  const paginator = reactive({ ...defaultPaginator })

  const loadPublishHistories = async (app_id: string, init: boolean = false) => {
    try {
      // 判断是否为初始化，如果是则先初始化分页器
      if (init) {
        Object.assign(paginator, { ...defaultPaginator })
      } else if (paginator.current_page > paginator.total_page) {
        return
      }

      loading.value = true
      const resp = await getPublishHistoriesWithPage(app_id, {
        current_page: paginator.current_page,
        page_size: paginator.page_size,
      })
      const data = resp.data

      paginator.current_page = data.paginator.current_page
      paginator.page_size = data.paginator.page_size
      paginator.total_page = data.paginator.total_page
      paginator.total_record = data.paginator.total_record

      // 是否存在更多数据
      if (paginator.current_page <= paginator.total_page) {
        paginator.current_page += 1
      }

      // 检测是追加数据还是覆盖数据
      if (init) {
        publishHistories.splice(0, publishHistories.length, ...data.list)
      } else {
        publishHistories.push(...data.list)
      }
    } finally {
      loading.value = false
    }
  }

  return { loading, publishHistories, paginator, loadPublishHistories }
}

export const useFallbackHistoryToDraft = () => {
  const loading = ref(false)
  const handleFallbackHistoryToDraft = async (
    app_id: string,
    app_config_version_id: string,
    callback?: () => void,
  ) => {
    try {
      loading.value = true
      const resp = await fallbackHistoryToDraft(app_id, app_config_version_id)
      Message.success(resp.message)
    } finally {
      loading.value = false
      callback?.()
    }
  }
  return { loading, handleFallbackHistoryToDraft }
}

export const useGetDraftAppConfig = (app_id: string) => {
  const loading = ref(false)
  const draftAppConfigForm = ref<Partial<GetDraftAppConfigResponse['data']>>({})

  const loadDraftAppConfig = async (app_id: string) => {
    try {
      loading.value = true
      const resp = await getDraftAppConfig(app_id)
      const data = resp.data

      draftAppConfigForm.value = {
        dialog_round: data.dialog_round,
        model_config: data.model_config,
        preset_prompt: data.preset_prompt,
        long_term_memory: data.long_term_memory,
        opening_statement: data.opening_statement,
        opening_questions: data.opening_questions,
        suggested_after_answer: data.suggested_after_answer,
        review_config: data.review_config,
        datasets: data.datasets,
        retrieval_config: data.retrieval_config,
        tools: data.tools,
        workflows: data.workflows,
        speech_to_text: data.speech_to_text,
        text_to_speech: data.text_to_speech,
        skills: data.skills,
        orchestrator_config: data.orchestrator_config,
        updated_at: data.updated_at,
      }
    } finally {
      loading.value = false
    }
  }
  onMounted(async () => await loadDraftAppConfig(app_id))

  return { loading, draftAppConfigForm, loadDraftAppConfig }
}

export const useUpdateDraftAppConfig = () => {
  const loading = ref(false)
  const handleUpdateDraftAppConfig = async (
    app_id: string,
    draft_app_config: UpdateDraftAppConfigRequest,
  ) => {
    try {
      loading.value = true
      const resp = await updateDraftAppConfig(app_id, draft_app_config)
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }
  return { loading, handleUpdateDraftAppConfig }
}

export const useGetDebugConversationSummary = () => {
  const loading = ref(false)
  const debug_conversation_summary = ref('')

  const loadDebugConversationSummary = async (app_id: string) => {
    try {
      loading.value = true
      const resp = await getDebugConversationSummary(app_id)
      const data = resp.data

      debug_conversation_summary.value = data.summary
    } finally {
      loading.value = false
    }
  }
  return { loading, debug_conversation_summary, loadDebugConversationSummary }
}

export const useUpdateDebugConversationSummary = () => {
  const loading = ref(false)
  const handleUpdateDebugConversationSummary = async (app_id: string, summary: string) => {
    try {
      loading.value = true
      const resp = await updateDebugConversationSummary(app_id, summary)
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }
  return { loading, handleUpdateDebugConversationSummary }
}

export const useDeleteDebugConversation = () => {
  const loading = ref<boolean>(false)

  const handleDeleteDebugConversation = async (app_id: string) => {
    try {
      loading.value = true
      const resp = await deleteDebugConversation(app_id)
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleDeleteDebugConversation }
}

export const UseGetDebugConversationMessagesWithPage = () => {
  const loading = ref(false)
  const messages = ref<GetDebugConversationMessagesWithPageResponse['data']['list']>([])
  const created_at = ref(0)
  const defaultPaginator = {
    current_page: 1,
    page_size: 5,
    total_page: 0,
    total_record: 0,
  }
  const paginator = ref({ ...defaultPaginator })

  const loadDebugConversationMessages = async (app_id: string, init: boolean = false) => {
    if (init) {
      paginator.value = { ...defaultPaginator }
      created_at.value = 0
    } else if (paginator.value.current_page > paginator.value.total_page) {
      return
    }

    try {
      loading.value = true
      const resp = await getDebugConversationMessagesWithPage(app_id, {
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
  return { loading, messages, paginator, loadDebugConversationMessages }
}

export const useDebugChat = () => {
  const loading = ref<boolean>(false)
  // 当前 SSE 请求的取消控制器：停止响应时先客户端中断，页面立即停止渲染
  let abortController: AbortController | null = null

  const handleDebugChat = async (
    app_id: string,
    query: string,
    image_urls: string[],
    file_ids: string[] = [],
    onData: (event_response: Record<string, unknown>) => void,
    resume: boolean = false,
    resume_message_id: string = '',
  ) => {
    try {
      loading.value = true
      abortController = new AbortController()
      await debugApp(app_id, query, image_urls, file_ids, onData, resume, abortController.signal, resume_message_id)
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

  return { loading, handleDebugChat, abort }
}

export const useStopDebugChat = () => {
  const loading = ref<boolean>(false)

  const handleStopDebugChat = async (app_id: string, task_id: string) => {
    try {
      loading.value = true
      await stopDebugChat(app_id, task_id)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleStopDebugChat }
}

export const useGetPublishedConfig = () => {
  const loading = ref<boolean>(false)
  const published_config = ref<Partial<GetPublishedConfigResponse['data']>>({})

  const loadPublishedConfig = async (app_id: string) => {
    try {
      loading.value = true
      const resp = await getPublishedConfig(app_id)
      published_config.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, published_config, loadPublishedConfig }
}

export const useRegenerateWebAppToken = () => {
  const loading = ref<boolean>(false)
  const token = ref<string>('')

// 定义重生成 WebAppToken 函数
  const handleRegenerateWebAppToken = async (app_id: string) => {
    try {
      loading.value = true
      const resp = await regenerateWebAppToken(app_id)
      Message.success('重新生成WebApp访问链接成功')
      token.value = resp.data.token
    } finally {
      loading.value = false
    }
  }

  return { loading, token, handleRegenerateWebAppToken }
}
