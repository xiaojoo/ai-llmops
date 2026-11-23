import { type MaybeRefOrGetter, ref, toValue, watch } from 'vue'
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router'
import { usePagination } from '@/hooks/use-paginator.ts'
import { getDocumentsWithPage } from '@/services/dataset.ts'
import type { GetDocumentsWithPageResponse } from '@/models/dataset.ts'

export const useGetDocumentsWithPage = (datasetIdRef: MaybeRefOrGetter<string>) => {
  const route = useRoute()
  const router = useRouter()

  const { pagination, updatePagination } = usePagination()
  const loading = ref(false)
  const documents = ref<GetDocumentsWithPageResponse['data']['list']>([])

  const loadDocuments = async () => {
    const id = toValue(datasetIdRef)
    if (!id || id === 'undefined') return

    loading.value = true
    try {
      const currentPage = Number(route.query.current_page) || 1
      const pageSize = Number(route.query.page_size) || 20
      const searchWord = String(route.query.search_word || '')

      const resp = await getDocumentsWithPage(id, {
        current_page: currentPage,
        page_size: pageSize,
        search_word: searchWord,
      })

      const data = resp.data
      documents.value = data.list
      updatePagination(data.paginator)
    } catch (error) {
      console.error('Failed to load documents', error)
    } finally {
      loading.value = false
    }
  }

// 处理页码改变 (对应 @page-change)
  const onPageChange = async (current: number) => {
    const query: LocationQueryRaw = {
      ...route.query,
      current_page: current,
    }
    await router.push({ query })
  }

// 处理每页条数改变 (对应 @page-size-change)
  const onPageSizeChange = async (pageSize: number) => {
    const query: LocationQueryRaw = {
      ...route.query,
      current_page: 1, // 改变每页大小时，通常重置回第一页
      page_size: pageSize,
    }
    await router.push({ query })
  }

  const handleSearch = async (word: string) => {
    const query: LocationQueryRaw = {
      ...route.query,
      current_page: 1,
      search_word: word,
    }
    if (!word) delete query.search_word
    await router.push({ query })
  }

  watch(
    [() => route.query, () => toValue(datasetIdRef)],
    async () => {
      await loadDocuments()
    },
    { immediate: true },
  )

  return {
    loading,
    documents,
    pagination,
    onPageChange,
    onPageSizeChange,
    handleSearch,
    loadDocuments,
  }
}
