<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { Message, Modal } from '@arco-design/web-vue'
import type { DocumentItem, RecallResult, SegmentItem } from '@/models/weaviate-vector.ts'
import {
  deleteDocument,
  deleteMemory,
  getAll,
  getCollections,
  getDocumentsByCollection,
  getSegmentsByDocument,
  recallTest,
} from '@/services/weaviate-vector.ts'

defineOptions({ name: 'WeaviateVector' })

// ─── 视图模式 ────────────────────────────────────────────────
// 'collections' → 'documents' → 'segments'
type ViewMode = 'collections' | 'documents' | 'segments'
const viewMode = ref<ViewMode>('collections')

// ─── Collections 视图 ────────────────────────────────────────
const collections = ref<string[]>([])
const loadingCollections = ref(false)
const selectedCollection = ref('')
// 刷新按钮独立加载态（只有点击刷新才转，不受其他加载影响）
const refreshing = ref(false)

const fetchCollections = async () => {
  loadingCollections.value = true
  try {
    const resp = await getCollections()
    collections.value = resp.data?.collections ?? []
  } catch {
    Message.error('获取 Collection 列表失败')
  } finally {
    loadingCollections.value = false
  }
}

const enterCollection = async (name: string) => {
  selectedCollection.value = name
  // 进入新集合时文档分页回到第一页
  documentPaginator.value.current_page = 1
  // 进入文档视图：显示全屏加载动画
  enteringDocuments.value = true
  try {
    await fetchDocuments(name)
    viewMode.value = 'documents'
  } finally {
    enteringDocuments.value = false
  }
}

// ─── Documents 视图 ──────────────────────────────────────────
const documents = ref<DocumentItem[]>([])
const loadingDocuments = ref(false)
const selectedDocumentId = ref('')
const currentDatasetId = ref('')
const selectedDatasetId = ref('')
// 当前集合是否为记忆类集合（无 document_id，需按 app_id 过滤查询分块）
const isMemoryCollection = ref(false)
// 文档列表分页（默认每页 8 条）
const documentPaginator = ref({ total: 0, current_page: 1, page_size: 8 })
// 进入文档视图时的全屏加载动画
const enteringDocuments = ref(false)

const fetchDocuments = async (collectionName?: string, opts?: { force?: boolean; page?: number }) => {
  // 集合名未传时回退到当前集合（修复：刷新时误用 'Dataset' 兜底导致展示错集合数据）
  const effective = collectionName || currentDatasetId.value
  if (effective) currentDatasetId.value = effective
  const page = opts?.page ?? documentPaginator.value.current_page
  const pageSize = documentPaginator.value.page_size
  loadingDocuments.value = true
  try {
    // 页面内缓存：同一 collection+页+每页条数 30s 内不重复请求；force=true（刷新/切每页条数）时绕过缓存
    const cacheKey = `weaviate-docs:${effective || 'Dataset'}:${page}:${pageSize}`
    const now = Date.now()
    if (!opts?.force) {
      const cached = sessionStorage.getItem(cacheKey)
      if (cached) {
        const parsed = JSON.parse(cached)
        if (now - parsed.ts < 30000) {
          documents.value = parsed.list
          documentPaginator.value.total = parsed.total
          documentPaginator.value.current_page = page
          return
        }
      }
    }
    const resp = await getDocumentsByCollection(effective, page, pageSize)
    documents.value = resp.data?.documents ?? []
    documentPaginator.value.total = resp.data?.document_count ?? 0
    documentPaginator.value.current_page = page
    // 记忆类集合标记：由后端按集合属性判定（无 document_id 属性时按 app_id 分组）
    isMemoryCollection.value = Boolean(resp.data?.is_memory_collection)
    sessionStorage.setItem(
      cacheKey,
      JSON.stringify({ ts: now, list: documents.value, total: documentPaginator.value.total }),
    )
  } catch {
    Message.error('获取文档列表失败')
  } finally {
    loadingDocuments.value = false
  }
}

// 文档视图翻页
const onDocumentPageChange = (page: number) => {
  fetchDocuments(currentDatasetId.value, { page })
}

// 文档视图切换每页条数：回到第一页（force 绕过缓存，确保立即生效）
const onDocumentPageSizeChange = (size: number) => {
  documentPaginator.value.page_size = size
  fetchDocuments(currentDatasetId.value, { page: 1, force: true })
}

const enterDocument = async (dataset_id: string, document_id: string) => {
  selectedDatasetId.value = dataset_id
  selectedDocumentId.value = document_id
  // 进入分块视图：显示全屏加载动画
  enteringSegments.value = true
  try {
    await fetchSegments(dataset_id, document_id, 1)
    viewMode.value = 'segments'
  } finally {
    enteringSegments.value = false
  }
}

// ─── Segments 视图 ───────────────────────────────────────────
const segments = ref<SegmentItem[]>([])
const segmentPaginator = ref({ total: 0, current_page: 1, page_size: 8 })
const loadingSegments = ref(false)
// 进入分块视图时的全屏加载动画
const enteringSegments = ref(false)

const fetchSegments = async (
  dataset_id: string,
  document_id: string,
  page = segmentPaginator.value.current_page,
) => {
  loadingSegments.value = true
  const offset = (page - 1) * segmentPaginator.value.page_size
  try {
    // 记忆类集合（无 document_id）：按 app_id 过滤查询分块（content 即记忆正文）
    if (isMemoryCollection.value) {
      const resp = await getAll({
        collection_name: currentDatasetId.value,
        app_id: document_id,
        limit: segmentPaginator.value.page_size,
        offset,
      })
      segments.value = resp.data?.items ?? []
      segmentPaginator.value.total = resp.data?.total ?? 0
      segmentPaginator.value.current_page = page
      return
    }
    const resp = await getSegmentsByDocument(
      dataset_id,
      document_id,
      segmentPaginator.value.page_size,
      offset,
    )
    segments.value = resp.data?.items ?? []
    segmentPaginator.value.total = resp.data?.total ?? 0
    segmentPaginator.value.current_page = page
  } catch {
    Message.error('获取分块列表失败')
  } finally {
    loadingSegments.value = false
  }
}

// 切换每页条数：更新 page_size 并回到第一页
const onSegmentPageSizeChange = (size: number) => {
  segmentPaginator.value.page_size = size
  fetchSegments(selectedDatasetId.value, selectedDocumentId.value, 1)
}

// ─── 分块详情弹窗 ────────────────────────────────────────────
const segmentDetailVisible = ref(false)
const segmentDetailItem = ref<SegmentItem | null>(null)

// ─── 召回测试 ────────────────────────────────────────────────
const recallVisible = ref(false)
const recallForm = ref({ dataset_id: '', query: '', top_k: 5, score_threshold: '' })
const recallLoading = ref(false)
const recallResults = ref<RecallResult[]>([])
// 结果分页 + 展开状态（用 segment_id 作唯一 key，避免分页/复用导致状态错乱）
const recallPage = ref(1)
const recallPageSize = 3
const expandedRecallIds = ref<Set<string>>(new Set())

const pagedRecallResults = computed(() => {
  const start = (recallPage.value - 1) * recallPageSize
  return recallResults.value.slice(start, start + recallPageSize)
})

const toggleRecallExpand = (segmentId: string) => {
  const set = expandedRecallIds.value
  if (set.has(segmentId)) set.delete(segmentId)
  else set.add(segmentId)
  expandedRecallIds.value = new Set(set)
}

const isRecallExpanded = (segmentId: string) => expandedRecallIds.value.has(segmentId)

// 内容是否需要展开按钮（超过约 3 行才显示，短内容无需展开）
const needRecallExpand = (content: string) => (content || '').length > 120

// 召回测试的文档下拉选项：每个文档一条，label 显示"文档名 + document_id"
const recallDatasetOptions = computed(() => {
  return documents.value
    .filter((doc) => doc.document_id)
    .map((doc) => ({
      value: doc.document_id,
      label: doc.name ? `${doc.name}（${doc.document_id}）` : doc.document_id,
      dataset_id: doc.dataset_id,
    }))
})

// 打开召回测试：若无文档数据则先拉取（保证下拉有选项）
const openRecall = () => {
  if (documents.value.length === 0) {
    fetchDocuments(currentDatasetId.value)
  }
  recallVisible.value = true
}

const handleRecallTest = async () => {
  if (!recallForm.value.dataset_id.trim()) return Message.warning('请选择文档')
  if (!recallForm.value.query.trim()) return Message.warning('请输入查询语句')
  recallLoading.value = true
  try {
    // 从选中的 document_id 反查 dataset_id
    const selected = recallDatasetOptions.value.find(
      (opt) => opt.value === recallForm.value.dataset_id,
    )
    const resp = await recallTest({
      dataset_id: selected?.dataset_id || '',
      document_id: recallForm.value.dataset_id.trim(),
      query: recallForm.value.query.trim(),
      top_k: recallForm.value.top_k,
      score_threshold: recallForm.value.score_threshold
        ? Number(recallForm.value.score_threshold)
        : 0,
    })
    recallResults.value = resp.data ?? []
    recallPage.value = 1
    expandedRecallIds.value = new Set()
  } catch {
    Message.error('召回测试失败')
  } finally {
    recallLoading.value = false
  }
}

// ─── 删除 ────────────────────────────────────────────────────
const handleDeleteDocument = (datasetId: string, documentId: string) => {
  // 记忆类集合（EpisodicMemory 等）：按 app_id 清空（无 dataset_id，document_id 即 app_id）
  if (isMemoryCollection.value) {
    Modal.confirm({
      title: '删除记忆数据',
      content: `确认删除该应用在「${currentDatasetId.value}」集合中的全部记忆数据？`,
      onOk: async () => {
        try {
          await deleteMemory({
            collection_name: currentDatasetId.value,
            app_id: documentId,
          })
          Message.success('删除成功')
          // 清除文档列表缓存，强制刷新；若当前页删空且非第一页则回退一页
          sessionStorage.removeItem(`weaviate-docs:${currentDatasetId.value || 'Dataset'}:${documentPaginator.value.current_page}`)
          await fetchDocuments(currentDatasetId.value, { force: true })
          if (documents.value.length === 0 && documentPaginator.value.current_page > 1) {
            documentPaginator.value.current_page -= 1
            await fetchDocuments(currentDatasetId.value, { force: true })
          }
          if (viewMode.value === 'segments' && selectedDatasetId.value === datasetId) {
            viewMode.value = 'documents'
          }
        } catch {
          // 全局请求拦截器已弹出具体错误信息，此处不重复弹框
        }
      },
    })
    return
  }
  // 非记忆集合：按知识库文档删除（dataset_id 为空时拦截，避免无意义请求）
  if (!datasetId?.trim()) {
    Message.warning('该集合的数据不支持按文档删除（非知识库向量）')
    return
  }
  Modal.confirm({
    title: '删除文档向量',
    content: `确认删除文档 ${datasetId} 的所有向量数据？`,
    onOk: async () => {
      try {
        await deleteDocument({ dataset_id: datasetId })
        Message.success('删除成功')
        // 清除文档列表缓存，强制刷新；若当前页删空且非第一页则回退一页
        sessionStorage.removeItem(`weaviate-docs:${currentDatasetId.value || 'Dataset'}:${documentPaginator.value.current_page}`)
        await fetchDocuments(currentDatasetId.value, { force: true })
        if (documents.value.length === 0 && documentPaginator.value.current_page > 1) {
          documentPaginator.value.current_page -= 1
          await fetchDocuments(currentDatasetId.value, { force: true })
        }
        if (viewMode.value === 'segments' && selectedDatasetId.value === datasetId) {
          viewMode.value = 'documents'
        }
      } catch {
        // 全局请求拦截器已弹出具体错误信息，此处不重复弹框
      }
    },
  })
}

// ─── 面包屑 & 返回 ───────────────────────────────────────────
const goBack = () => {
  if (viewMode.value === 'segments') {
    viewMode.value = 'documents'
  } else if (viewMode.value === 'documents') {
    viewMode.value = 'collections'
  }
}

const filterDatasetId = ref('')
// 筛选结果（dataset_id 过滤后的分块列表）
const filterResults = ref<SegmentItem[]>([])
const filterTotal = ref(0)
const filterLoading = ref(false)
const filterPaginator = ref({ current_page: 1, page_size: 10 })
const showFilterResults = ref(false)

const handleFilterAll = async (page = 1) => {
  if (!filterDatasetId.value.trim()) {
    showFilterResults.value = false
    return
  }
  filterLoading.value = true
  showFilterResults.value = true
  const offset = (page - 1) * filterPaginator.value.page_size
  try {
    const resp = await getAll({
      dataset_id: filterDatasetId.value.trim(),
      limit: filterPaginator.value.page_size,
      offset,
    })
    filterResults.value = resp.data?.items ?? []
    filterTotal.value = resp.data?.total ?? 0
    filterPaginator.value.current_page = page
  } catch {
    Message.error('筛选失败')
  } finally {
    filterLoading.value = false
  }
}

// 切换筛选结果每页条数
const onFilterPageSizeChange = (size: number) => {
  filterPaginator.value.page_size = size
  handleFilterAll(1)
}

const clearFilter = () => {
  filterDatasetId.value = ''
  showFilterResults.value = false
  filterResults.value = []
}

const goToCollections = () => {
  viewMode.value = 'collections'
  fetchCollections()
}

const handleRefresh = () => {
  refreshing.value = true
  const done = () => {
    refreshing.value = false
  }
  if (viewMode.value === 'collections') fetchCollections().finally(done)
  // 文档/分块视图刷新：传入当前集合并强制绕过缓存（文档视图保持当前页）
  else if (viewMode.value === 'documents') fetchDocuments(currentDatasetId.value, { force: true, page: documentPaginator.value.current_page }).finally(done)
  else fetchSegments(selectedDatasetId.value, selectedDocumentId.value).finally(done)
}

const openSegmentDetail = (seg: SegmentItem) => {
  segmentDetailItem.value = seg
  segmentDetailVisible.value = true
}

// ─── 集合视图记忆：留在 /weaviate 路由内一直有效（含刷新，刷新保留当前视图）──
// 点击左侧菜单离开该路由时清除 —— 下次进入从 Collections 列表开始。
const LAST_VIEW_STORAGE_KEY = 'llmops-weaviate-last-view'

const persistView = () => {
  try {
    const collection = currentDatasetId.value || selectedCollection.value
    localStorage.setItem(
      LAST_VIEW_STORAGE_KEY,
      JSON.stringify({ mode: viewMode.value, collection }),
    )
  } catch {
    /* localStorage 不可用时忽略 */
  }
}
watch([viewMode, currentDatasetId, selectedCollection], persistView)

const restoreLastView = () => {
  try {
    const raw = localStorage.getItem(LAST_VIEW_STORAGE_KEY)
    if (!raw) return
    const saved = JSON.parse(raw) as { mode?: string; collection?: string }
    if (
      (saved.mode === 'documents' || saved.mode === 'segments') &&
      saved.collection &&
      collections.value.includes(saved.collection)
    ) {
      // 恢复到该集合的文档视图（分块层级不深挖，避免文档校验失败）
      void enterCollection(saved.collection)
    }
  } catch {
    /* 存储内容非法时忽略，留在 Collections 列表 */
  }
}

onBeforeRouteLeave(() => {
  localStorage.removeItem(LAST_VIEW_STORAGE_KEY)
})

onMounted(() => {
  fetchCollections().finally(restoreLastView)
})
</script>

<template>
  <div class="flex flex-col gap-4">
    <!-- 工具栏（视口缩小时只显示召回测试按钮，返回/刷新隐藏） -->
    <div class="flex items-center justify-between">
      <!-- 面包屑 -->
      <div class="flex items-center gap-1 text-sm text-gray-500">
        <span
          class="cursor-pointer hover:text-blue-600 transition-colors"
          :class="viewMode === 'collections' ? 'text-gray-800 font-medium' : ''"
          @click="goToCollections"
          >Collections</span
        >
        <template v-if="viewMode !== 'collections'">
          <icon-right class="text-xs !text-gray-300" />
          <span
            class="cursor-pointer hover:text-blue-600 transition-colors"
            :class="viewMode === 'documents' ? 'text-gray-800 font-medium' : ''"
            @click="viewMode = 'documents'"
            >{{ selectedCollection }}</span
          >
        </template>
        <template v-if="viewMode === 'segments'">
          <icon-right class="text-xs !text-gray-300" />
          <span class="text-gray-800 font-medium truncate max-w-[180px]">{{
            selectedDocumentId
          }}</span>
        </template>
      </div>

      <!-- 操作按钮（小视口只显示召回测试） -->
      <div class="flex items-center gap-2">
        <a-button
          v-if="viewMode !== 'collections'"
          size="small"
          class="!hidden md:!inline-flex"
          @click="goBack"
        >
          <template #icon><icon-left /></template>返回
        </a-button>
        <!-- dataset_id 筛选（仅 collections 视图下的全量数据筛选） -->
        <!--        <a-input-->
        <!--          v-if="viewMode === 'collections'"-->
        <!--          v-model="filterDatasetId"-->
        <!--          placeholder="按 dataset_id 筛选"-->
        <!--          allow-clear-->
        <!--          size="small"-->
        <!--          class="w-64"-->
        <!--          @press-enter="handleFilterAll"-->
        <!--          @clear="clearFilter"-->
        <!--        />-->
        <a-button
          size="small"
          class="!hidden md:!inline-flex"
          :disabled="refreshing"
          @click="handleRefresh"
        >
          <template #icon><icon-refresh /></template>刷新
        </a-button>
        <a-button size="small" @click="openRecall">
          <template #icon><icon-search /></template>召回测试
        </a-button>
      </div>
    </div>

    <!-- ── 筛选结果视图（dataset_id 过滤） ── -->
    <div
      v-if="viewMode === 'collections' && showFilterResults"
      class="border border-blue-200 rounded-lg bg-white overflow-hidden"
    >
      <div
        class="px-4 py-2.5 border-b border-blue-100 bg-blue-50 flex items-center justify-between"
      >
        <span class="text-xs text-blue-600 font-medium">
          dataset_id: <span class="font-mono">{{ filterDatasetId }}</span> &nbsp;·&nbsp;共
          {{ filterTotal }} 个分块
        </span>
        <a-button size="mini" type="text" @click="clearFilter">
          <template #icon><icon-close /></template>清除筛选
        </a-button>
      </div>
      <div v-if="filterLoading" class="flex flex-col items-center justify-center py-12 text-gray-400">
        <icon-search class="text-4xl mb-2" />
        <div class="text-sm">加载中...</div>
      </div>
      <div
        v-else-if="filterResults.length === 0"
        class="flex flex-col items-center justify-center py-12 text-gray-400"
      >
        <icon-search class="text-4xl mb-2" />
        <div class="text-sm">未找到匹配数据</div>
      </div>
      <div v-else class="divide-y divide-gray-100">
        <div
          v-for="seg in filterResults"
          :key="seg.id"
          class="flex items-start gap-3 px-4 py-3 hover:bg-gray-50 transition-colors group"
        >
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 mb-1 flex-wrap">
              <span class="text-xs font-mono text-blue-600 truncate max-w-[200px]">{{
                seg.segment_id
              }}</span>
              <span
                class="text-xs text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded font-mono truncate max-w-[180px]"
              >
                doc: {{ seg.document_id }}
              </span>
              <span v-if="seg.position != null" class="text-xs text-gray-400"
                >#{{ seg.position }}</span
              >
            </div>
            <div class="text-xs text-gray-600 line-clamp-2 leading-relaxed">{{ seg.text }}</div>
          </div>
          <a-tooltip content="查看详情">
            <a-button aria-label="查看"
              size="mini"
              type="text"
              class="flex-shrink-0 self-center"
              @click="openSegmentDetail(seg)"
            >
              <template #icon><icon-eye /></template>
            </a-button>
          </a-tooltip>
        </div>
      </div>
      <div
        v-if="filterTotal > filterPaginator.page_size"
        class="flex justify-end px-4 py-3 border-t border-gray-100"
      >
        <a-pagination
          :total="filterTotal"
          :page-size="filterPaginator.page_size"
          :current="filterPaginator.current_page"
          size="small"
          show-total
          show-page-size
          :page-size-options="[10, 20, 50, 100]"
          @change="(page: number) => handleFilterAll(page)"
          @page-size-change="onFilterPageSizeChange"
        />
      </div>
    </div>

    <!-- ── Collections 视图 ── -->
    <div
      v-if="viewMode === 'collections' && !showFilterResults"
      class="border border-gray-200 rounded-lg bg-white overflow-hidden"
    >
      <div v-if="loadingCollections" class="flex flex-col items-center justify-center py-12 text-gray-400">
        <icon-storage class="text-4xl mb-2" />
        <div class="text-sm">加载中...</div>
      </div>
      <div
        v-else-if="collections.length === 0"
        class="flex flex-col items-center justify-center py-12 text-gray-400"
      >
        <icon-storage class="text-4xl mb-2" />
        <div class="text-sm">暂无 Collection</div>
      </div>
      <div v-else class="divide-y divide-gray-100">
        <div
          v-for="name in collections"
          :key="name"
          class="flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors cursor-pointer group"
          @click="enterCollection(name)"
        >
          <div class="flex items-center gap-3">
            <div
              class="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center flex-shrink-0"
            >
              <icon-storage class="!text-blue-500 text-sm" />
            </div>
            <div>
              <div class="text-sm font-medium text-gray-700">{{ name }}</div>
              <div class="text-xs text-gray-400 mt-0.5">Weaviate Collection</div>
            </div>
          </div>
          <icon-right class="!text-gray-300 group-hover:!text-blue-500 transition-colors" />
        </div>
      </div>
    </div>

    <!-- ── Documents 视图 ── -->
    <div
      v-if="viewMode === 'documents'"
      class="border border-gray-200 rounded-lg bg-white overflow-hidden"
    >
      <div
        class="px-4 py-2.5 border-b border-gray-100 bg-gray-50 flex items-center justify-between"
      >
        <span class="text-xs text-gray-500">共 {{ documentPaginator.total }} 个文档</span>
      </div>
      <div v-if="loadingDocuments" class="flex flex-col items-center justify-center py-12 text-gray-400">
        <icon-file class="text-4xl mb-2" />
        <div class="text-sm">加载中...</div>
      </div>
      <div
        v-else-if="documents.length === 0"
        class="flex flex-col items-center justify-center py-12 text-gray-400"
      >
        <icon-file class="text-4xl mb-2" />
        <div class="text-sm">该知识库暂无文档向量</div>
      </div>
      <div v-else class="divide-y divide-gray-100">
        <div
          v-for="doc in documents"
          :key="doc.document_id"
          class="flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors group"
        >
          <div
            class="flex items-center gap-3 flex-1 min-w-0 cursor-pointer"
            @click="enterDocument(doc.dataset_id, doc.document_id)"
          >
            <div
              class="w-8 h-8 rounded-lg bg-indigo-50 flex items-center justify-center flex-shrink-0"
            >
              <icon-file class="!text-indigo-500 text-sm" />
            </div>
            <div class="min-w-0">
              <div class="text-sm font-medium text-gray-700 truncate flex items-center gap-2">
                {{ doc.name || '未命名文档' }}
                <span class="bg-gray-100 px-1.5 py-0.5 rounded text-xs text-gray-500 flex-shrink-0"
                  >{{ doc.segment_count }} 分块</span
                >
              </div>
              <div class="text-xs font-mono text-blue-600 truncate mt-0.5">
                {{ doc.document_id }}
              </div>
            </div>
          </div>
          <div class="flex items-center gap-1 flex-shrink-0">
            <a-tooltip content="查看分块">
              <a-button aria-label="查看"
                size="mini"
                type="text"
                @click="enterDocument(doc.dataset_id, doc.document_id)"
              >
                <template #icon><icon-eye /></template>
              </a-button>
            </a-tooltip>
            <a-button aria-label="删除"
              size="mini"
              type="text"
              class="!text-red-400 hover:!text-red-600"
              @click="handleDeleteDocument(doc.dataset_id, doc.document_id)"
            >
              <template #icon><icon-delete /></template>
            </a-button>
          </div>
        </div>
      </div>
      <!-- 文档分页：始终显示（数据量不足一页时 Arco 自动隐藏页码，仅保留总数/每页条数） -->
      <div class="flex justify-end px-4 py-3 border-t border-gray-100">
        <a-pagination
          :total="documentPaginator.total"
          :page-size="documentPaginator.page_size"
          :current="documentPaginator.current_page"
          size="small"
          show-total
          show-page-size
          :page-size-options="[8, 10, 20, 50, 100]"
          @change="onDocumentPageChange"
          @page-size-change="onDocumentPageSizeChange"
        />
      </div>
    </div>

    <!-- ── Segments 视图 ── -->
    <div
      v-if="viewMode === 'segments'"
      class="border border-gray-200 rounded-lg bg-white overflow-hidden"
    >
      <div
        class="px-4 py-2.5 border-b border-gray-100 bg-gray-50 flex items-center justify-between"
      >
        <span class="text-xs text-gray-500">共 {{ segmentPaginator.total }} 个分块</span>
      </div>
      <div v-if="loadingSegments" class="flex flex-col items-center justify-center py-12 text-gray-400">
        <icon-layers class="text-4xl mb-2" />
        <div class="text-sm">加载中...</div>
      </div>
      <div
        v-else-if="segments.length === 0"
        class="flex flex-col items-center justify-center py-12 text-gray-400"
      >
        <icon-layers class="text-4xl mb-2" />
        <div class="text-sm">暂无分块数据</div>
      </div>
      <!-- 列表：自然高度，随页面滚动 -->
      <div v-else class="divide-y divide-gray-100">
        <div
          v-for="(seg, idx) in segments"
          :key="seg.id"
          class="flex items-start gap-3 px-4 py-3 hover:bg-gray-50 transition-colors group"
        >
          <div
            class="w-6 h-6 rounded bg-gray-100 flex items-center justify-center flex-shrink-0 mt-0.5"
          >
            <span class="text-xs font-mono text-gray-500">{{ seg.position ?? idx + 1 }}</span>
          </div>
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 mb-1">
              <span class="text-xs font-mono text-blue-600 truncate max-w-[400px]">{{
                seg.segment_id
              }}</span>
              <div v-if="seg.keywords?.length" class="flex gap-1 flex-wrap">
                <span
                  v-for="kw in seg.keywords.slice(0, 3)"
                  :key="kw"
                  class="text-xs bg-blue-50 text-blue-600 px-1.5 py-0.5 rounded"
                  >{{ kw }}</span
                >
                <span v-if="seg.keywords.length > 3" class="text-xs text-gray-400"
                  >+{{ seg.keywords.length - 3 }}</span
                >
              </div>
            </div>
            <div class="text-xs text-gray-600 line-clamp-2 leading-relaxed">{{ seg.text }}</div>
          </div>
          <a-tooltip content="查看详情">
            <a-button aria-label="查看"
              size="mini"
              type="text"
              class="flex-shrink-0 self-center"
              @click="openSegmentDetail(seg)"
            >
              <template #icon><icon-eye /></template>
            </a-button>
          </a-tooltip>
        </div>
      </div>
      <!-- 分页：固定不参与滚动，始终显示（数据量不足一页时 Arco 自动隐藏页码） -->
      <div class="flex justify-end px-4 py-3 border-t border-gray-100">
        <a-pagination
          :total="segmentPaginator.total"
          :page-size="segmentPaginator.page_size"
          :current="segmentPaginator.current_page"
          size="small"
          show-total
          show-page-size
          :page-size-options="[8, 10, 20, 50, 100]"
          @change="(page: number) => fetchSegments(selectedDatasetId, selectedDocumentId, page)"
          @page-size-change="onSegmentPageSizeChange"
        />
      </div>
    </div>

    <!-- 分块详情弹窗 -->
    <a-modal
      v-model:visible="segmentDetailVisible"
      title="分块详情"
      :footer="false"
      width="clamp(320px, 80vw, 1200px)"
    >
      <div v-if="segmentDetailItem" class="flex flex-col gap-3 text-sm">
        <div class="grid grid-cols-2 gap-3">
          <div class="flex flex-col gap-1">
            <span class="text-xs text-gray-400">Segment ID</span>
            <span class="font-mono text-xs text-blue-600 break-all">{{
              segmentDetailItem.segment_id
            }}</span>
          </div>
          <div class="flex flex-col gap-1">
            <span class="text-xs text-gray-400">Position</span>
            <span class="font-mono text-xs">{{ segmentDetailItem.position }}</span>
          </div>
          <div class="flex flex-col gap-1">
            <span class="text-xs text-gray-400">Document ID</span>
            <span class="font-mono text-xs text-gray-600 break-all">{{
              segmentDetailItem.document_id || selectedDocumentId
            }}</span>
          </div>
          <div class="flex flex-col gap-1">
            <span class="text-xs text-gray-400">Dataset ID</span>
            <span class="font-mono text-xs text-gray-600 break-all">{{
              segmentDetailItem.dataset_id
            }}</span>
          </div>
        </div>
        <div v-if="segmentDetailItem.keywords?.length" class="flex flex-col gap-1">
          <span class="text-xs text-gray-400">关键词</span>
          <div class="flex gap-1.5 flex-wrap">
            <span
              v-for="kw in segmentDetailItem.keywords"
              :key="kw"
              class="text-xs bg-blue-50 text-blue-600 px-2 py-0.5 rounded-full"
              >{{ kw }}</span
            >
          </div>
        </div>
        <div class="flex flex-col gap-1">
          <span class="text-xs text-gray-400">分块原文</span>
          <div
            class="bg-gray-50 rounded-lg p-3 text-xs leading-relaxed whitespace-pre-wrap h-[450px] overflow-y-auto text-gray-700"
          >
            {{ segmentDetailItem.text }}
          </div>
        </div>
      </div>
    </a-modal>

    <!-- 召回测试弹窗 -->
    <a-modal
      v-model:visible="recallVisible"
      title="召回测试"
      :footer="false"
      modal-class="recall-modal rounded-xl"
    >
      <div class="flex flex-col gap-4">
        <div class="flex flex-col gap-3 border border-gray-200 rounded-lg p-4 bg-gray-50">
          <div class="flex gap-3">
            <div class="flex-1">
              <div class="text-xs text-gray-500 mb-1">
                文档 <span class="text-red-400">*</span>
              </div>
              <a-select
                v-model="recallForm.dataset_id"
                placeholder="请选择文档"
                allow-clear
                :loading="loadingDocuments"
              >
                <a-option
                  v-for="opt in recallDatasetOptions"
                  :key="opt.value"
                  :value="opt.value"
                  :label="opt.label"
                />
              </a-select>
            </div>
            <div class="w-24">
              <div class="text-xs text-gray-500 mb-1">Top K</div>
              <a-input-number v-model="recallForm.top_k" :min="1" :max="50" />
            </div>
          </div>
          <div class="flex gap-3 items-end">
            <div class="flex-1">
              <div class="text-xs text-gray-500 mb-1">
                查询语句 <span class="text-red-400">*</span>
              </div>
              <a-input v-model="recallForm.query" placeholder="输入查询内容" allow-clear />
            </div>
            <div class="w-40">
              <div class="text-xs text-gray-500 mb-1">相似度阈值（0~1）</div>
              <a-input v-model="recallForm.score_threshold" placeholder="留空不过滤" allow-clear />
            </div>
            <a-button
              type="primary"
              size="small"
              :disabled="recallLoading"
              @click="handleRecallTest"
            >
              开始测试
            </a-button>
          </div>
        </div>

        <!-- 加载中：屏幕中央转圈 -->
        <div v-if="recallLoading" class="flex items-center justify-center py-10">
          <a-spin />
        </div>
        <template v-else>
          <div v-if="recallResults.length > 0" class="flex flex-col gap-2">
          <div class="flex items-center justify-between">
            <div class="text-xs text-gray-500">共召回 {{ recallResults.length }} 条</div>
            <a-pagination
              v-if="recallResults.length > recallPageSize"
              :total="recallResults.length"
              :page-size="recallPageSize"
              :current="recallPage"
              size="mini"
              @change="(page: number) => (recallPage = page)"
            />
          </div>
          <div
            v-for="r in pagedRecallResults"
            :key="r.segment_id"
            class="border rounded-lg p-3 text-xs border-gray-200 bg-gray-50"
            :class="r.score >= 0.7 ? '!border-green-200 !bg-green-50' : ''"
          >
            <div class="flex items-center justify-between mb-1.5">
              <span class="font-mono text-blue-600 truncate">{{ r.segment_id }}</span>
              <div class="flex items-center gap-2 flex-shrink-0 ml-2">
                <span class="text-gray-500"
                  >相似度 <b class="text-gray-700">{{ r.score }}</b></span
                >
                <span class="text-gray-400">距离 {{ r.distance }}</span>
                <span
                  class="px-1.5 py-0.5 rounded"
                  :class="
                    r.score >= 0.7 ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
                  "
                  >{{ r.score >= 0.7 ? '相关' : '弱相关' }}</span
                >
                <a-button
                  v-if="needRecallExpand(r.content)"
                  size="mini"
                  class="rounded flex-shrink-0"
                  @click="toggleRecallExpand(r.segment_id)"
                >
                  <template #icon>
                    <icon-down v-if="!isRecallExpanded(r.segment_id)" />
                    <icon-up v-else />
                  </template>
                  {{ isRecallExpanded(r.segment_id) ? '收起' : '展开' }}
                </a-button>
              </div>
            </div>
            <div v-if="r.keywords?.length" class="flex gap-1 mb-1.5 flex-wrap">
              <span
                v-for="kw in r.keywords.slice(0, 4)"
                :key="kw"
                class="bg-blue-50 text-blue-500 px-1.5 py-0.5 rounded"
                >{{ kw }}</span
              >
            </div>
            <div
              :class="isRecallExpanded(r.segment_id)
                ? 'text-gray-600 leading-relaxed whitespace-pre-wrap max-h-40 overflow-y-auto'
                : 'text-gray-600 line-clamp-3 leading-relaxed'"
            >
              {{ r.content }}
            </div>
          </div>
          </div>
          <!-- 未检索到数据：数据出来才隐藏 -->
          <div v-else class="text-center text-gray-400 text-sm py-2">
            <div class="border rounded-lg p-3 text-xs border-gray-200 bg-gray-50">
              输入查询语句后点击「开始测试」
            </div>
          </div>
        </template>
      </div>
    </a-modal>

    <!-- 进入文档视图的全屏加载动画 -->
    <div
      v-if="enteringDocuments"
      class="fixed inset-0 z-[1000] flex items-center justify-center bg-white/60 backdrop-blur-[1px]"
    >
      <div class="flex flex-col items-center gap-3">
        <a-spin :size="36" />
        <div class="text-sm text-gray-500">正在加载文档…</div>
      </div>
    </div>

    <!-- 进入分块视图的全屏加载动画 -->
    <div
      v-if="enteringSegments"
      class="fixed inset-0 z-[1000] flex items-center justify-center bg-white/60 backdrop-blur-[1px]"
    >
      <div class="flex flex-col items-center gap-3">
        <a-spin :size="36" />
        <div class="text-sm text-gray-500">正在加载分块…</div>
      </div>
    </div>
  </div>
</template>

<style>
.arco-modal-footer {
  display: flex;
  justify-content: flex-end;
}

/* 召回测试弹框宽度：视口 <1500px 时占 80%，≥1500px 固定 1200px 封顶（纯 CSS） */
.recall-modal {
  width: clamp(320px, 80vw, 1200px);
}

/* 召回测试弹框标题左对齐（title 为 flex 容器，须用 justify-content 而非 text-align） */
.recall-modal .arco-modal-title {
  justify-content: flex-start;
}
</style>
