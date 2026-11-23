import { onMounted, reactive, ref } from 'vue'
import { getBuiltinTool, getBuiltinTools, getCategories } from '@/services/builtin-tool.ts'
import type {
  GetBuiltinToolResponse,
  GetBuiltinToolsResponse,
  GetCategoriesResponse,
} from '@/models/builtin-tool.ts'

export const useGetCategories = () => {
// 定义自定义hooks所需数据
  const loading = ref(false)
  const categories = reactive<GetCategoriesResponse['data']>([])

  const loadCategories = async (): Promise<void> => {
    try {
      loading.value = true
      const resp = await getCategories()
      const data = resp.data

      categories.splice(0, categories.length, ...data)
    } finally {
      loading.value = false
    }
  }
  onMounted(async () => await loadCategories())

  return { loading, categories, loadCategories }
}

export const useGetBuiltinTool = () => {
  const loading = ref(false)
  const builtin_tool = reactive<Partial<GetBuiltinToolResponse['data']>>({})

  const loadBuiltinTool = async (provider_name: string, tool_name: string) => {
    try {
      loading.value = true
      const resp = await getBuiltinTool(provider_name, tool_name)
      const data = resp.data

      Object.assign(builtin_tool, data)
    } finally {
      loading.value = false
    }
  }

  return { loading, builtin_tool, loadBuiltinTool }
}

export const useGetBuiltinTools = () => {
// 定义自定义hooks所需数据
  const loading = ref(false)
  const builtin_tools = reactive<GetBuiltinToolsResponse['data']>([])

  const loadBuiltinTools = async (): Promise<void> => {
    try {
      loading.value = true
      const resp = await getBuiltinTools()
      const data = resp.data

      builtin_tools.splice(0, builtin_tools.length, ...data)
    } finally {
      loading.value = false
    }
  }

  return { loading, builtin_tools, loadBuiltinTools }
}
