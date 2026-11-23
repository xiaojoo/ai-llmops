import { reactive, ref } from 'vue'
import { getApiTool, getApiToolProvidersWithPage } from '@/services/api-tools.ts'
import type {
  GetApiToolProvidersWithPageResponse,
  GetApiToolResponse,
} from '@/models/api-tool.ts'
import type { PaginatorData } from './use-paginator'

export const useGetApiTool = () => {
  const loading = ref(false)
  const api_tool = reactive<Partial<GetApiToolResponse['data']>>({})

  const loadApiTool = async (provider_id: string, tool_name: string) => {
    try {
      loading.value = true
      const resp = await getApiTool(provider_id, tool_name)
      const data = resp.data

      Object.assign(api_tool, data)
    } finally {
      loading.value = false
    }
  }
  return { loading, api_tool, loadApiTool }
}

export const useGetApiToolProvidersWithPage = () => {
  const loading = ref(false)
  const api_tool_providers = reactive<GetApiToolProvidersWithPageResponse['data']['list']>([])
  const defaultPaginator = {
    current_page: 1,
    page_size: 20,
    total_page: 0,
    total_record: 0,
  }
  const paginator = reactive({ ...defaultPaginator })

  const loadApiToolProviders = async (init: boolean = false) => {
// 判断是否是初始化，如果是的话则先初始化分页器
    if (init) {
      Object.assign(paginator, { ...defaultPaginator })
    } else if (paginator.current_page > paginator.total_page) {
      return
    }
    try {
      loading.value = true
      const resp = await getApiToolProvidersWithPage(
        paginator.current_page,
        paginator.page_size,
        '',
      )
      const data = resp.data
      updatePagination(data)
      if (paginator.current_page <= paginator.total_page) {
        paginator.current_page += 1
      }
      if (init) {
        api_tool_providers.splice(0, api_tool_providers.length, ...data.list)
      } else {
        api_tool_providers.push(...data.list)
      }
    } finally {
      loading.value = false
    }
  }
  const updatePagination = (data: { paginator: PaginatorData }): void => {
    paginator.current_page = data.paginator.current_page
    paginator.page_size = data.paginator.page_size
    paginator.total_page = data.paginator.total_page
    paginator.total_record = data.paginator.total_record
  }

  return { loading, api_tool_providers, paginator, loadApiToolProviders }
}
