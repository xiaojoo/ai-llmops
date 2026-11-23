<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message, Modal } from '@arco-design/web-vue'
import type { RecallResult, VectorItem } from '@/models/chroma-vector.ts'
import {
  clearVectors,
  deleteVector,
  listVectors,
  recallTest,
  syncDocuments,
  updateVector,
} from '@/services/chroma-vector.ts'

defineOptions({ name: 'ChromaVector' })

const vectorList = ref<VectorItem[]>([])
const vectorPaginator = ref({ total_count: 0, total_pages: 1, current_page: 1, page_size: 10 })
const loadingVectors = ref(false)
const deletingVector = ref<string | null>(null)
const syncing = ref(false)

// 编辑弹窗
const vectorModalVisible = ref(false)
const vectorModalLoading = ref(false)
const vectorForm = ref({ id: '', content: '', metadata: '{}' })
const editingDocId = ref('')

// 详情弹窗
const detailVisible = ref(false)
const detailItem = ref<VectorItem | null>(null)

// 召回测试
const recallVisible = ref(false)
const recallForm = ref({
  query: '',
  top_k: 5,
})
const recallLoading = ref(false)
const recallResults = ref<RecallResult[]>([])
// 召回结果分页（默认每页 3 条）+ 单条展开/收起状态
// 展开状态按结果在 recallResults 中的全局索引记录（而非 id——召回结果 id 可能重复/为空，
// 用 id 会导致点击一条全部展开），翻页后仍保持各自的展开状态
const recallPageSize = 3
const recallPage = ref(1)
const expandedRecallIdx = ref<Set<number>>(new Set())

const recallIndexOffset = computed(() => (recallPage.value - 1) * recallPageSize)

const pagedRecallResults = computed(() => {
  return recallResults.value.slice(recallIndexOffset.value, recallIndexOffset.value + recallPageSize)
})

const toggleRecallExpand = (pageIndex: number) => {
  const idx = recallIndexOffset.value + pageIndex
  const set = new Set(expandedRecallIdx.value)
  if (set.has(idx)) set.delete(idx)
  else set.add(idx)
  expandedRecallIdx.value = set
}

const isRecallExpanded = (pageIndex: number) =>
  expandedRecallIdx.value.has(recallIndexOffset.value + pageIndex)

const fetchVectors = async (page = vectorPaginator.value.current_page) => {
  loadingVectors.value = true
  try {
    const resp = await listVectors(page, vectorPaginator.value.page_size)
    vectorList.value = resp.data?.list ?? []
    if (resp.data?.paginator) vectorPaginator.value = resp.data.paginator
  } catch {
    Message.error('获取向量列表失败')
  } finally {
    loadingVectors.value = false
  }
}

// 切换每页条数：更新 page_size 并回到第一页
const onPageSizeChange = (size: number) => {
  vectorPaginator.value.page_size = size
  fetchVectors(1)
}

const openEditModal = (item: VectorItem) => {
  editingDocId.value = item.id
  vectorForm.value = {
    id: item.id,
    content: item.content,
    metadata: JSON.stringify(item.metadata, null, 2),
  }
  vectorModalVisible.value = true
}

const handleVectorSubmit = async () => {
  if (!vectorForm.value.content.trim()) return Message.warning('content 不能为空')
  let metadata: Record<string, unknown> = {}
  try {
    metadata = JSON.parse(vectorForm.value.metadata || '{}')
  } catch {
    return Message.error('metadata 不是合法 JSON')
  }
  vectorModalLoading.value = true
  try {
    await updateVector(editingDocId.value, { content: vectorForm.value.content.trim(), metadata })
    Message.success('更新成功')
    vectorModalVisible.value = false
    await fetchVectors()
  } catch {
    Message.error('更新失败')
  } finally {
    vectorModalLoading.value = false
  }
}

const handleDeleteVector = (id: string) => {
  Modal.confirm({
    title: '删除向量记录',
    content: `确认删除 ${id}？`,
    onOk: async () => {
      deletingVector.value = id
      try {
        await deleteVector(id)
        Message.success('删除成功')
        await fetchVectors()
      } catch {
        Message.error('删除失败')
      } finally {
        deletingVector.value = null
      }
    },
  })
}

const handleClearVectors = () => {
  Modal.confirm({
    title: '清空向量库',
    content: '确认清空所有向量记录？此操作不可恢复！',
    onOk: async () => {
      try {
        const resp = await clearVectors()
        Message.success(`已清空 ${resp.data?.deleted ?? 0} 条记录`)
        await fetchVectors()
      } catch {
        Message.error('清空失败')
      }
    },
  })
}

const handleSync = async () => {
  syncing.value = true
  try {
    const resp = await syncDocuments()
    Message.success(`同步完成，新增 ${resp.data?.added ?? 0} 条`)
    await fetchVectors()
  } catch {
    Message.error('同步失败')
  } finally {
    syncing.value = false
  }
}

const handleRecallTest = async () => {
  if (!recallForm.value.query.trim()) return Message.warning('请输入查询语句')
  recallLoading.value = true
  try {
    const resp = await recallTest({
      query: recallForm.value.query.trim(),
      top_k: recallForm.value.top_k,
    })
    recallResults.value = resp.data?.results ?? []
    // 新一次测试：回到第一页并收起所有展开项
    recallPage.value = 1
    expandedRecallIdx.value = new Set()
  } catch {
    Message.error('召回测试失败')
  } finally {
    recallLoading.value = false
  }
}
onMounted(() => fetchVectors(1))
</script>

<template>
  <div class="flex flex-col gap-4">
    <!-- 工具栏（视口缩小时只隐藏刷新列表，其余按钮保留） -->
    <div class="flex items-center justify-between">
      <div class="text-xs text-gray-400">共 {{ vectorPaginator.total_count }} 条向量记录</div>
      <div class="flex items-center gap-2">
        <a-button
          size="small"
          class="!hidden md:!inline-flex"
          :disabled="loadingVectors"
          @click="fetchVectors()"
        >
          <template #icon><icon-refresh /></template>{{ loadingVectors ? '刷新中...' : '刷新列表' }}
        </a-button>
        <a-button size="small" @click="recallVisible = true">
          <template #icon><icon-search /></template>召回测试
        </a-button>
        <a-button size="small" :disabled="syncing" @click="handleSync">
          <template #icon><icon-sync /></template>{{ syncing ? '同步中...' : '同步文档' }}
        </a-button>
        <a-button size="small" status="danger" @click="handleClearVectors">
          <template #icon><icon-delete /></template>清空
        </a-button>
      </div>
    </div>

    <!-- 向量列表：自然高度，不撑满，不设滚动 -->
    <div class="border border-gray-200 rounded-lg bg-white">
      <div v-if="loadingVectors" class="flex items-center justify-center py-4"><a-spin /></div>
      <div
        v-else-if="vectorList.length === 0"
        class="flex flex-col items-center justify-center py-4 text-gray-400"
      >
        <icon-storage class="text-4xl mb-2" />
        <div class="text-sm">向量库为空</div>
      </div>
      <div v-else class="divide-y divide-gray-100">
        <div
          v-for="item in vectorList"
          :key="item.id"
          class="flex items-start gap-3 px-4 py-3 hover:bg-gray-50 transition-colors group"
        >
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 mb-1">
              <span class="text-xs font-mono font-medium text-blue-600 truncate max-w-[200px]">{{
                item.id
              }}</span>
              <span class="text-xs text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded flex-shrink-0"
                >{{ item.embedding_dims }}维</span
              >
            </div>
            <div class="text-xs text-gray-600 line-clamp-2 leading-relaxed">{{ item.content }}</div>
            <div class="text-xs text-gray-400 font-mono mt-1 truncate">
              [{{ item.embedding_preview.join(', ') }}{{ item.embedding_dims > 8 ? ', ...' : '' }}]
            </div>
          </div>
          <div class="flex gap-1 flex-shrink-0 self-center">
            <a-tooltip content="详情">
              <a-button
                size="mini"
                type="text"
                @click="
                  () => {
                    detailItem = item
                    detailVisible = true
                  }
                "
              >
                <template #icon><icon-eye /></template>
              </a-button>
            </a-tooltip>
            <a-tooltip content="编辑">
              <a-button aria-label="编辑" size="mini" type="text" @click="openEditModal(item)">
                <template #icon><icon-edit /></template>
              </a-button>
            </a-tooltip>
            <a-button aria-label="删除"
              size="mini"
              type="text"
              class="!text-red-400 hover:!text-red-600"
              :loading="deletingVector === item.id"
              @click="handleDeleteVector(item.id)"
            >
              <template #icon><icon-delete /></template>
            </a-button>
          </div>
        </div>
      </div>
    </div>

    <!-- 分页：固定不参与滚动 -->
    <div
      v-if="vectorPaginator.total_pages > 1"
      class="flex justify-end flex-shrink-0 border border-gray-200 rounded-lg bg-white px-4 py-2"
    >
      <a-pagination
        :total="vectorPaginator.total_count"
        :page-size="vectorPaginator.page_size"
        :current="vectorPaginator.current_page"
        size="small"
        show-total
        show-page-size
        :page-size-options="[10, 20, 50, 100]"
        @change="fetchVectors"
        @page-size-change="onPageSizeChange"
      />
    </div>

    <!-- 编辑弹窗 -->
    <a-modal
      width="clamp(320px, 80vw, 1200px)"
      title="编辑向量记录"
      v-model:visible="vectorModalVisible"
      :confirm-loading="vectorModalLoading"
      @ok="handleVectorSubmit"
    >
      <div class="flex flex-col gap-3 h-[520px]">
        <div class="flex flex-col gap-1 flex-1 min-h-0">
          <label class="text-xs text-gray-600 font-medium flex-shrink-0" for="vector-content"
            >内容 <span class="text-red-500">*</span></label
          >
          <a-textarea
            v-model="vectorForm.content"
            placeholder="输入文档内容，将自动向量化存储"
            class="flex-1 min-h-0 resize-none"
            :textarea-attrs="{ id: 'vector-content' }"
          />
        </div>
        <div class="flex flex-col gap-1 flex-shrink-0">
          <label class="text-xs text-gray-600 font-medium" for="vector-metadata">Metadata（JSON）</label>
          <a-textarea
            v-model="vectorForm.metadata"
            placeholder='{"source": "manual"}'
            :auto-size="{ minRows: 2, maxRows: 5 }"
            :textarea-attrs="{ id: 'vector-metadata' }"
          />
        </div>
      </div>
    </a-modal>

    <!-- 详情弹窗 -->
    <a-modal
      v-model:visible="detailVisible"
      title="向量详情"
      :footer="false"
      width="clamp(320px, 80vw, 1200px)"
    >
      <div v-if="detailItem" class="flex flex-col gap-3 text-sm">
        <div class="flex gap-2 items-center">
          <span class="text-gray-400 w-20 flex-shrink-0">ID</span>
          <span class="font-mono text-blue-600">{{ detailItem.id }}</span>
        </div>
        <div class="flex gap-2 items-center">
          <span class="text-gray-400 w-20 flex-shrink-0">维度</span>
          <span>{{ detailItem.embedding_dims }}</span>
        </div>
        <div class="flex gap-2">
          <span class="text-gray-400 w-20 flex-shrink-0">Metadata</span>
          <pre class="text-xs bg-gray-50 rounded p-2 flex-1 overflow-auto">
            {{ JSON.stringify(detailItem.metadata, null, 2) }}
          </pre>
        </div>
        <div class="flex flex-col gap-1">
          <span class="text-gray-400">内容</span>
          <div
            class="bg-gray-50 rounded p-3 text-xs leading-relaxed whitespace-pre-wrap h-[450px] overflow-y-auto"
          >
            {{ detailItem.content }}
          </div>
        </div>
        <div class="flex flex-col gap-1">
          <span class="text-gray-400">向量预览（前8维）</span>
          <div class="font-mono text-xs text-gray-600 bg-gray-50 rounded p-2 break-all">
            {{ detailItem.embedding_preview }}
          </div>
        </div>
      </div>
    </a-modal>

    <!-- 召回测试弹窗 -->
    <a-modal v-model:visible="recallVisible" title="召回测试" modal-class="recall-modal" :footer="false">
      <div class="flex flex-col gap-4">
        <div class="flex flex-col gap-3 border border-gray-200 rounded-lg p-4 bg-gray-50">
          <div class="flex gap-3">
            <div class="flex-1">
              <div class="text-xs text-gray-500 mb-1">查询语句</div>
              <a-input v-model="recallForm.query" placeholder="输入查询内容" allow-clear />
            </div>
            <div class="w-24">
              <div class="text-xs text-gray-500 mb-1">Top K</div>
              <a-input-number v-model="recallForm.top_k" :min="1" :max="50" />
            </div>
            <div class="flex items-end">
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
        </div>
        <!-- 加载中：屏幕中央转圈 -->
        <div
          v-if="recallLoading"
          class="flex items-center justify-center py-10"
        >
          <a-spin />
        </div>
        <!-- 结果列表：默认每页 3 条，单条可展开/收起，展开后滚动条在展开区域上 -->
        <div v-else-if="recallResults.length > 0" class="flex flex-col gap-2">
          <div class="text-xs text-gray-500">共召回 {{ recallResults.length }} 条</div>
          <div
            v-for="(r, i) in pagedRecallResults"
            :key="recallIndexOffset + i"
            class="border rounded-lg p-0.5 text-xs"
            :class="r.relevant ? 'border-green-200 bg-green-50' : 'border-gray-200 bg-gray-50'"
          >
            <div class="flex items-center justify-between mb-1">
              <span class="font-mono text-blue-600 truncate">{{ r.id }}</span>
              <div class="flex items-center gap-2 flex-shrink-0 ml-2">
                <span class="text-gray-500">距离 {{ r.score }}</span>
                <span
                  class="px-1.5 py-0.5 rounded"
                  :class="r.relevant ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'"
                >
                  {{ r.relevant ? '相关' : '不相关' }}
                </span>
                <!-- 展开/收起：跟在"相关"标签后面 -->
                <a-button
                  type="text"
                  size="mini"
                  class="!text-blue-600"
                  @click="toggleRecallExpand(i)"
                >
                  {{ isRecallExpanded(i) ? '收起' : '展开' }}
                </a-button>
              </div>
            </div>
            <!-- 内容：默认 3 行截断；展开后显示全文，滚动条加在展开区域上 -->
            <div
              v-if="!isRecallExpanded(i)"
              class="text-gray-600 line-clamp-3 leading-relaxed"
            >
              {{ r.content }}
            </div>
            <div
              v-else
              class="text-gray-600 leading-relaxed max-h-40 overflow-y-auto"
            >
              {{ r.content }}
            </div>
          </div>
          <a-pagination
            v-if="recallResults.length > recallPageSize"
            :current="recallPage"
            :page-size="recallPageSize"
            :total="recallResults.length"
            show-total
            class="self-end"
            @change="(page: number) => (recallPage = page)"
          />
        </div>
        <!-- 未检索到数据：数据出来才隐藏 -->
        <div v-else class="text-center text-gray-400 text-sm pt-1">
          <div class="border rounded-lg p-3 text-xs border-green-200 bg-green-50">未检索到数据</div>
        </div>
      </div>
    </a-modal>
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

/* 弹框标题左对齐 */
/* 召回测试弹框标题左对齐（title 为 flex 容器，须用 justify-content 而非 text-align） */
.recall-modal .arco-modal-title {
  justify-content: flex-start;
}
</style>
