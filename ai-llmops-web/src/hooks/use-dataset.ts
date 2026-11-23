import { computed, onMounted, reactive, ref, watch } from 'vue'
import {
  createDataset,
  deleteDataset,
  deleteDocument,
  deleteSegment,
  getDataset,
  getDatasetsWithPage,
  getDocument,
  getDocumentsWithPage,
  getSegmentsWithPage,
  updateDataset,
  updateDocumentEnable,
  updateSegmentEnabled,
} from '@/services/dataset.ts'
import { useRoute } from 'vue-router'
import { type FormInstance, Message, Modal } from '@arco-design/web-vue'
import type { FormState } from '@/models/upload-file.ts'
import type {
  GetDatasetResponse,
  GetDatasetsWithPageResponse,
  GetDocumentResponse,
  GetDocumentsWithPageResponse,
  GetSegmentsWithPageResponse,
} from '@/models/dataset.ts'
import type { PaginatorData } from './use-paginator'

// 分页响应 data 结构（含 list 与 paginator）
type PaginatedData = { list: unknown[]; paginator: PaginatorData }

export const useGetDatasetsWithPage = () => {
// 定义数据，涵盖数据是否加载，知识库列表以及分页器
  const route = useRoute()

  const loading = ref<boolean>(false)
  const datasets = reactive<GetDatasetsWithPageResponse['data']['list']>([])
  const defaultPaginator = {
    current_page: 1,
    page_size: 20,
    total_page: 0,
    total_record: 0,
  }
  const paginator = reactive({ ...defaultPaginator })

  const searchWord = computed(() => {
    return Array.isArray(route.query.search_word)
      ? (route.query.search_word[0] ?? '')
      : (route.query.search_word ?? '')
  })

  const loadDatasets = async (init: boolean = false) => {
// 判断是否是初始化，如果是则先初始化分页器
    if (init) {
      initPaginator()
    } else if (paginator.current_page > paginator.total_page) {
      return
    }

    try {
      loading.value = true
      const resp = await getDatasetsWithPage(
        paginator.current_page,
        paginator.page_size,
        searchWord.value,
      )
      const data = resp.data

      updatePaginator(data)

      if (paginator.current_page <= paginator.total_page) {
        paginator.current_page += 1
      }

      if (init) {
        datasets.splice(0, datasets.length, ...data.list)
      } else {
        datasets.push(...data.list)
      }
    } finally {
      loading.value = false
    }
  }

  const initPaginator = () => {
    Object.assign(paginator, { ...defaultPaginator })
  }

  const updatePaginator = (data: PaginatedData) => {
    paginator.current_page = data.paginator.current_page
    paginator.page_size = data.paginator.page_size
    paginator.total_page = data.paginator.total_page
    paginator.total_record = data.paginator.total_record
  }

  onMounted(async () => {
    await loadDatasets(true)
  })

  watch(searchWord, async () => {
    await loadDatasets(true)
  })

  return { loading, datasets, paginator, loadDatasets }
}

export const useDeleteDataset = () => {
  // 删除知识库

  const handleDelete = (dataset_id: string, callback?: () => void) => {
    Modal.warning({
      title: '确认删除这个知识库？',
      content: '删除知识库是不可逆的，关联该知识库的应用将无法再使用该知识库',
      hideCancel: false,
      onOk: async () => {
        try {
          const resp = await deleteDataset(dataset_id)
          Message.success(resp.message)
        } finally {
          callback?.()
        }
      },
    })
  }

  return { handleDelete }
}

export const useCreateOrUpdateDataset = () => {
// 定义新增和更新需要使用的数据
  const loading = ref(false)
  const defaultForm: FormState = {
    // icon: '/api/default-app-icon',
    fileList: [],
    icon: '',
    name: '',
    description: '',
  }
  const form = reactive({ ...defaultForm })
  const formRef = ref<FormInstance | null>(null)
  const showUpdateModal = ref<boolean>(false)

// 定义更新showUpdateModal函数
  const updateShowUpdateModal = (new_value: boolean, callback?: () => void) => {
    showUpdateModal.value = new_value
    callback?.()
  }

  const saveDataset = async (dataset_id?: string) => {
    try {
      loading.value = true
      if (dataset_id !== undefined && dataset_id !== '') {
        const resp = await updateDataset(dataset_id, {
          icon: form.icon,
          name: form.name,
          description: form.description,
        })
        Message.success(resp.message)
      } else {
        const resp = await createDataset({
          icon: form.icon,
          name: form.name,
          description: form.description,
        })
        Message.success(resp.message)
      }
    } finally {
      loading.value = false
    }
  }

  return { loading, form, formRef, showUpdateModal, updateShowUpdateModal, saveDataset }
}

export const useGetDataset = (dataset_id: string) => {
  const loading = ref(false)
  const dataset = reactive<Partial<GetDatasetResponse['data']>>({})

  const loadDataset = async (dataset_id: string) => {
    try {
      loading.value = true
      const resp = await getDataset(dataset_id)
      const data = resp.data
      Object.assign(dataset, { ...data })
    } finally {
      loading.value = false
    }
  }

  onMounted(() => loadDataset(dataset_id))

  return { loading, dataset, loadDataset }
}

export const useGetDocumentsWithPage = (dataset_id: string) => {
// 定义数据，涵盖数据是否加载，知识库列表以及分页器
  const route = useRoute()

  const loading = ref<boolean>(false)
  const documents = reactive<GetDocumentsWithPageResponse['data']['list']>([])
  const defaultPaginator = {
    current_page: 1,
    page_size: 10,
    total_page: 0,
    total_record: 0,
  }

  const paginator = reactive({ ...defaultPaginator })

  const loadDocuments = async (init: boolean = false) => {
// 判断是否是初始化页分页器的逻辑
    if (!init && paginator.current_page > paginator.total_page) return

    try {
      loading.value = true
      const resp = await getDocumentsWithPage(dataset_id, {
        current_page: Number(route.query?.current_page) || 1,
        page_size: Number(route.query?.page_size) || 20,
        search_word: String(route.query?.search_word ?? ''),
      })
      const data = resp.data

      updatePaginator(data)

      documents.splice(0, documents.length, ...data.list)
    } finally {
      loading.value = false
    }
  }

  onMounted(async () => {
    await loadDocuments(true)
  })

  // 定义初始化分页器函数
  const initPaginator = () => {
    Object.assign(paginator, { ...defaultPaginator })
  }

  // 定义更新分页器
  const updatePaginator = (data: PaginatedData) => {
    paginator.current_page = data.paginator.current_page
    paginator.page_size = data.paginator.page_size
    paginator.total_page = data.paginator.total_page
    paginator.total_record = data.paginator.total_record
  }

  watch(
    () => route.query,
    async (newQuery, oldQuery) => {
      if (newQuery.search_word !== oldQuery.search_word) {
        initPaginator()
        await loadDocuments(true)
      } else if (newQuery.current_page != oldQuery.current_page) {
        await loadDocuments()
      }
    },
  )

  return { loading, documents, paginator, loadDocuments }
}

export const useDeleteDocument = () => {
  // 删除文档
  const handleDelete = (dataset_id: string, document_id: string, callback?: () => void) => {
    Modal.warning({
      title: '确认删除这个文档？',
      content:
        '删除文档是不可逆的，，知识库/向量数据库将无法检索到该文档，如需暂时关闭该文档的检索，可以选择禁用功能',
      hideCancel: false,
      onOk: async () => {
        try {
          const resp = await deleteDocument(dataset_id, document_id)
          Message.success(resp.message)
        } finally {
          callback?.()
        }
      },
    })
  }

  return { handleDelete }
}

export const useUpdateDocumentEnable = () => {
  // 修改文档状态
  const handleUpdateEnable = async (
    dataset_id: string,
    document_id: string,
    enabled: boolean,
    callback?: () => void,
  ) => {
    try {
      const resp = await updateDocumentEnable(dataset_id, document_id, enabled)
      Message.success(resp.message)
    } finally {
      callback?.()
    }
  }

  return { handleUpdateEnable }
}

export const useGetDocument = (dataset_id: string, document_id: string) => {
  const loadingSegment = ref(false)
  const document = reactive<Partial<GetDocumentResponse['data']>>({})

  // 加载文档
  const loadDocument = async (dataset_id: string, document_id: string) => {
    try {
      loadingSegment.value = true
      const resp = await getDocument(dataset_id, document_id)
      const data = resp.data

      Object.assign(document, { ...data })
    } finally {
      loadingSegment.value = false
    }
  }

  onMounted(async () => await loadDocument(dataset_id, document_id))

  return { loadingSegment, document, loadDocument }
}

export const useGetSegmentsWithPage = (dataset_id: string, document_id: string) => {
  const route = useRoute()
  const loading = ref(false)
  const segments = reactive<GetSegmentsWithPageResponse['data']['list']>([])
  const defaultPaginator = {
    current_page: 1,
    page_size: 20,
    total_page: 0,
    total_record: 0,
  }
  const paginator = reactive({ ...defaultPaginator })

  // 按指定页码加载（分页模式）：每次替换列表，而不是追加
  const loadSegmentsByPage = async (page: number = 1) => {
    try {
      loading.value = true
      const resp = await getSegmentsWithPage(dataset_id, document_id, {
        current_page: page,
        page_size: paginator.page_size,
        search_word: String(route.query?.search_word ?? ''),
      })
      const data = resp.data
      updatePaginator(data)
      segments.splice(0, segments.length, ...data.list)
    } finally {
      loading.value = false
    }
  }

  // 兼容旧签名：init=true 重置到第一页并加载；无参调用等价于加载第一页
  const loadSegments = async (init: boolean = false) => {
    if (init) {
      Object.assign(paginator, { ...defaultPaginator })
    }
    await loadSegmentsByPage(1)
  }

  onMounted(async () => {
    await loadSegments(true)
  })

  // 定义更新分页器
  const updatePaginator = (data: PaginatedData) => {
    paginator.current_page = data.paginator.current_page
    paginator.page_size = data.paginator.page_size
    paginator.total_page = data.paginator.total_page
    paginator.total_record = data.paginator.total_record
  }

  watch(
    () => route.query?.search_word,
    async () => {
      await loadSegments(true)
    },
  )

  return { loading, segments, paginator, loadSegments, loadSegmentsByPage }
}

export const useDeleteSegment = () => {
  const handleDelete = async (
    dataset_id: string,
    document_id: string,
    segment_id: string,
    callback?: () => void,
  ) => {
    Modal.warning({
      title: '确定删除文档片段吗？',
      content:
        '删除文档文档后，知识库/向量数据库将无法检索到该文档，如需暂时关闭该文档的检索，可以选择禁用功能',
      hideCancel: false,
      onOk: async () => {
        try {
          const resp = await deleteSegment(dataset_id, document_id, segment_id)
          Message.success(resp.message)
        } finally {
          {
            callback?.()
          }
        }
      },
    })
  }

  return { handleDelete }
}

export const useUpdateSegmentEnabled = () => {
  const handleUpdate = async (
    dataset_id: string,
    document_id: string,
    segment_id: string,
    enabled: boolean,
    callback?: () => void,
  ) => {
    try {
      const resp = await updateSegmentEnabled(dataset_id, document_id, segment_id, enabled)
      Message.success(resp.message)
    } finally {
      callback?.()
    }
  }

  return { handleUpdate }
}
