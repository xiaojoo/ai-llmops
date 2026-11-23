import { ref } from 'vue'
import { useRoute } from 'vue-router'
import type {
  CreateApiKeyRequest,
  GetApiKeysWithPageResponse,
  UpdateApiKeyRequest,
} from '@/models/api-key.ts'
import {
  createApiKey,
  deleteApiKey,
  getApiKeysWithPage,
  updateApiKey,
  updateApiKeyIsActive,
} from '@/services/api-key.ts'
import { Message, Modal } from '@arco-design/web-vue'

export const useGetApiKeysWithPage = () => {
  const route = useRoute()
  const loading = ref(false)
  // const api_keys = ref<GetApiKeysWithPageResponse['data']['list']>([])
  const api_keys = ref<GetApiKeysWithPageResponse['data']['list']>([])
  const defaultPaginator = {
    current_page: 1,
    page_size: 20,
    total_page: 0,
    total_record: 0,
  }

  const paginator = ref({ ...defaultPaginator })

  const loadApiKeys = async (init: boolean = false) => {
// 判断是否超过总页数，如果是则返回
    if (!init && paginator.value.current_page > paginator.value.total_page) {
      return
    }

    try {
      loading.value = true
      const resp = await getApiKeysWithPage({
        current_page: (route.query?.current_page || 1) as number,
        page_size: (route.query?.page_size || 20) as number,
      })
      const data = resp.data

      paginator.value = data.paginator

// 对于表格式+分页器实现的分页，可以直接填充数据进行替换
      api_keys.value = data.list
    } finally {
      loading.value = false
    }
  }

  return { loading, api_keys, paginator, loadApiKeys }
}

export const useDeleteApiKey = () => {
  const handleDeleteApiKey = (api_key_id: string, callback?: () => void) => {
    Modal.warning({
      title: '要删除该API秘钥吗？',
      content:
        '删除秘钥后，无法使用该秘钥访问 LLMOps 个人空间中的所有 Agent,并且无法恢复，如果临时关闭请使用禁用',
      hideCancel: false,
      onOk: async () => {
        try {
// 点击确定后向API接口发起请求
          const resp = await deleteApiKey(api_key_id)
          Message.success(resp.message)
        } finally {
// 调用callback函数指定回调功能
          callback?.()
        }
      },
    })
  }

  return { handleDeleteApiKey }
}

export const useUpdateApiKey = () => {
  const loading = ref<boolean>(false)

  const handleUpdateApiKey = async (api_key_id: string, req: UpdateApiKeyRequest) => {
    try {
      loading.value = true
      const resp = await updateApiKey(api_key_id, req)
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleUpdateApiKey }
}

export const useUpdateApiKeyIsActive = () => {
  const loading = ref<boolean>(false)

  const handleUpdateApiKeyIsActive = async (
    api_key_id: string,
    is_active: boolean,
    callback?: () => void,
  ): Promise<void> => {
    try {
      loading.value = true
      const resp = await updateApiKeyIsActive(api_key_id, is_active)
      Message.success(resp.message)
    } finally {
      loading.value = false
      callback?.()
    }
  }

  return { handleUpdateApiKeyIsActive }
}

export const useCreateApiKey = () => {
  const loading = ref<boolean>(false)

  const handleCreateApiKey = async (req: CreateApiKeyRequest): Promise<void> => {
    try {
      loading.value = true
      const resp = await createApiKey(req)
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleCreateApiKey }
}
