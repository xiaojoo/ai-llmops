<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Message, Modal } from '@arco-design/web-vue'
import { showErrorToast } from '@/utils/http/error'
import moment from 'moment'
import {
  getDocumentsWithPage,
  retryDocument,
  pauseDocument,
  resumeDocument,
} from '@/services/dataset.ts'
import type { GetDocumentsWithPageResponse } from '@/models/dataset.ts'

// 任务列表使用的文档行：基础文档字段 + 处理进度字段（原接口未覆盖，这里补全为可选字段）
type TaskDocument = GetDocumentsWithPageResponse['data']['list'][number] & {
  segment_count?: number
  completed_segment_count?: number
}

const props = defineProps({
  visible: { type: Boolean, required: true },
  dataset_id: { type: String, required: true },
})
const emits = defineEmits(['update:visible'])

const loading = ref(false)
const retrying = ref<Set<string>>(new Set())
const documents = reactive<TaskDocument[]>([])
// 分页状态（前端本地分页，数据已全量拉取）
const currentPage = ref(1)
const pageSize = ref(10)

// 状态中文映射
const STATUS_LABEL: Record<string, { text: string; color: string }> = {
  waiting: { text: '等待处理', color: 'gray' },
  parsing: { text: '解析中', color: 'blue' },
  splitting: { text: '分段中', color: 'blue' },
  indexing: { text: '索引中', color: 'blue' },
  completed: { text: '已完成', color: 'green' },
  error: { text: '处理失败', color: 'red' },
  stopped: { text: '已暂停', color: 'orange' },
}

const hideModal = () => emits('update:visible', false)

// 加载全部文档（拉取全量：按每页 50 逐页拉完）
const loadDocuments = async () => {
  loading.value = true
  try {
    documents.splice(0, documents.length)
    currentPage.value = 1
    let page = 1
    let totalPage = 1
    while (page <= totalPage) {
      const resp = await getDocumentsWithPage(props.dataset_id, {
        current_page: page,
        page_size: 50,
        search_word: '',
      })
      const data = resp.data
      documents.push(...data.list)
      totalPage = data.paginator.total_page
      page++
    }
  } finally {
    loading.value = false
  }
}

// 分页切换（前端本地分页）
const onPageChange = (page: number) => {
  currentPage.value = page
}
const onPageSizeChange = (size: number) => {
  pageSize.value = size
  currentPage.value = 1
}

// 当前页展示的数据
const pagedDocuments = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return documents.slice(start, start + pageSize.value)
})

// 所有任务均已完成（或列表为空）时隐藏操作列
const allCompleted = computed(
  () => documents.length > 0 && documents.every((d) => d.status === 'completed'),
)

// 弹框确认工具：Arco 2.x Modal.confirm 返回 ModalReturn（非 Promise），
// 用 onOk 回调包装成 Promise，resolve(true)=确认 / resolve(false)=取消
const confirmAction = (options: {
  title: string
  content: string
  okText?: string
  cancelText?: string
}): Promise<boolean> =>
  new Promise((resolve) => {
    Modal.confirm({
      title: options.title,
      content: options.content,
      okText: options.okText || '确认',
      cancelText: options.cancelText || '取消',
      onOk: () => resolve(true),
      onCancel: () => resolve(false),
    })
  })

// 重试构建
const onRetry = async (record: TaskDocument) => {
  try {
    const confirm = await confirmAction({
      title: '重新构建',
      content: `确认重新构建文档「${record.name}」？将清理旧的索引数据并重新上传构建。`,
      okText: '确认重试',
      cancelText: '取消',
    })
    if (!confirm) return

    retrying.value.add(record.id)
    const resp = await retryDocument(props.dataset_id, record.id)
    Message.success(resp.message || '已重新提交构建任务')
    await loadDocuments()
  } catch (e: unknown) {
    showErrorToast((e as Error)?.message || '重试失败')
  } finally {
    retrying.value.delete(record.id)
  }
}

// 暂停构建（等待/失败/处理中状态的任务可暂停）
const pausing = ref<Set<string>>(new Set())
const onPause = async (record: TaskDocument) => {
  try {
    const processing = ['parsing', 'splitting', 'indexing'].includes(record.status)
    const confirm = await confirmAction({
      title: '暂停构建',
      content: processing
        ? `确认暂停「${record.name}」的构建任务？处理中的任务将在当前阶段完成后停止，已完成的片段会保留，继续时可断点续传。`
        : `确认暂停「${record.name}」的构建任务？暂停后可随时继续。`,
      okText: '确认暂停',
      cancelText: '取消',
    })
    if (!confirm) return

    pausing.value.add(record.id)
    const resp = await pauseDocument(props.dataset_id, record.id)
    Message.success(resp.message || '已暂停构建任务')
    await loadDocuments()
  } catch (e: unknown) {
    showErrorToast((e as Error)?.message || '暂停失败')
  } finally {
    pausing.value.delete(record.id)
  }
}

// 继续构建（暂停状态的任务可继续）
const resuming = ref<Set<string>>(new Set())
const onResume = async (record: TaskDocument) => {
  try {
    resuming.value.add(record.id)
    const resp = await resumeDocument(props.dataset_id, record.id)
    Message.success(resp.message || '已继续构建任务')
    await loadDocuments()
  } catch (e: unknown) {
    showErrorToast((e as Error)?.message || '继续失败')
  } finally {
    resuming.value.delete(record.id)
  }
}

const isRetryable = (record: TaskDocument) =>
  record.status === 'error' || record.status === 'waiting'
// 等待/失败/处理中（解析/分段/索引）均可暂停；处理中暂停后当前阶段完成即停止（软暂停）
const isPausable = (record: TaskDocument) =>
  ['waiting', 'error', 'parsing', 'splitting', 'indexing'].includes(record.status)
const isResumable = (record: TaskDocument) => record.status === 'stopped'

onMounted(async () => {
  if (props.visible) await loadDocuments()
})

// 弹框打开时加载任务列表
watch(
  () => props.visible,
  async (visible) => {
    if (visible) await loadDocuments()
  },
)
</script>

<template>
  <a-modal
    :visible="props.visible"
    hide-title
    :footer="false"
    modal-class="recall-modal rounded-xl"
    @cancel="hideModal"
  >
    <!-- 顶部标题 -->
    <div class="flex items-center justify-between mb-4">
      <div class="flex items-center gap-2">
        <div class="text-lg font-bold text-gray-700">任务查看</div>
        <a-tag size="small" class="rounded">{{ documents.length }} 个文档</a-tag>
      </div>
      <div class="flex items-center gap-2">
        <a-button size="small" class="rounded-lg" @click="loadDocuments">
          <template #icon><icon-refresh /></template>
          刷新
        </a-button>
        <a-button aria-label="关闭" size="small" type="text" class="!text-gray-700" @click="hideModal">
          <template #icon><icon-close /></template>
        </a-button>
      </div>
    </div>
    <div class="text-gray-500 text-xs mb-3">
      查看上传文件的异步处理情况。等待/失败的任务可暂停，暂停后可继续；失败的任务可重新上传构建。
    </div>

    <!-- 文档任务列表（本地分页，无内部滚动条） -->
    <a-table
      :loading="loading"
      :data="pagedDocuments"
      :pagination="{
        current: currentPage,
        pageSize,
        total: documents.length,
        showTotal: true,
        showPageSize: true,
        pageSizeOptions: [10, 20, 50],
      }"
      :bordered="{ wrapper: false }"
      :scroll="{ x: 1120 }"
      class="rounded-lg overflow-hidden"
      @page-change="onPageChange"
      @page-size-change="onPageSizeChange"
    >
      <template #columns>
        <a-table-column
          title="文档名称"
          data-index="name"
          :width="200"
          fixed="left"
          header-cell-class="!bg-gray-200 text-gray-700"
          cell-class="bg-white"
        >
          <template #cell="{ record }">
            <div class="line-clamp-1" :title="record.name">{{ record.name }}</div>
          </template>
        </a-table-column>
        <a-table-column
          title="状态"
          data-index="status"
          :width="100"
          fixed="left"
          header-cell-class="!bg-gray-200 text-gray-700"
          cell-class="bg-white"
        >
          <template #cell="{ record }">
            <a-tag
              size="small"
              class="rounded"
              :color="(STATUS_LABEL[record.status] || { color: 'gray' }).color"
            >
              {{ (STATUS_LABEL[record.status] || { text: record.status }).text }}
            </a-tag>
          </template>
        </a-table-column>
        <a-table-column
          title="处理进度"
          data-index="progress"
          :width="180"
          header-cell-class="!bg-gray-200 text-gray-700"
          cell-class="bg-transparent"
        >
          <template #cell="{ record }">
            <template v-if="record.status === 'completed'">
              <a-progress
                :percent="100"
                :show-text="false"
                :stroke-width="6"
                class="w-[90px]"
                color="#00b42a"
              />
              <div class="text-gray-400 text-xs mt-0.5">
                {{ record.segment_count || 0 }} / {{ record.segment_count || 0 }} 块
              </div>
            </template>
            <template v-else-if="record.status === 'error'">
              <div class="text-gray-400 text-xs">-</div>
            </template>
            <template v-else>
              <a-progress
                v-if="(record.segment_count ?? 0) > 0"
                :percent="Math.min(Math.round(((record.completed_segment_count ?? 0) / (record.segment_count ?? 0)) * 100), 100)"
                :show-text="false"
                :stroke-width="6"
                class="w-[90px]"
              />
              <a-progress v-else :percent="0" :show-text="false" :stroke-width="6" class="w-[90px]" />
              <div class="text-gray-400 text-xs mt-0.5">
                {{ record.completed_segment_count || 0 }} / {{ record.segment_count || 0 }} 块
              </div>
            </template>
          </template>
        </a-table-column>
        <a-table-column
          title="错误原因 / 处理信息"
          data-index="error"
          :width="280"
          header-cell-class="!bg-gray-200 text-gray-700"
          cell-class="bg-transparent"
        >
          <template #cell="{ record }">
            <div v-if="record.status === 'error'" class="text-red-500 text-xs line-clamp-2" :title="record.error">
              {{ record.error || '处理失败' }}
            </div>
            <div v-else-if="record.status === 'stopped'" class="text-orange-500 text-xs">
              已暂停，可点击"继续"恢复构建
            </div>
            <div v-else class="text-gray-400 text-xs">
              {{ record.status === 'completed' ? '索引构建完成' : '正在异步处理中…' }}
            </div>
          </template>
        </a-table-column>
        <a-table-column
          title="上传时间"
          data-index="created_at"
          :width="200"
          header-cell-class="!bg-gray-200 text-gray-700"
          cell-class="bg-transparent"
        >
          <template #cell="{ record }">
            {{ moment(record.created_at * 1000).format('YYYY-MM-DD HH:mm:ss') }}
          </template>
        </a-table-column>
        <!-- 所有任务已完成时隐藏操作列 -->
        <a-table-column
          v-if="!allCompleted"
          title="操作"
          data-index="operator"
          :width="160"
          fixed="right"
          header-cell-class="rounded-tr-lg !bg-gray-200 text-gray-700"
          cell-class="bg-white"
        >
          <template #cell="{ record }">
            <a-space :size="8">
              <!-- 暂停：等待/失败的任务可暂停 -->
              <a-button
                v-if="isPausable(record)"
                size="mini"
                class="rounded-lg"
                :loading="pausing.has(record.id)"
                @click="onPause(record)"
              >
                暂停
              </a-button>
              <!-- 继续：暂停的任务可继续 -->
              <a-button
                v-if="isResumable(record)"
                size="mini"
                type="primary"
                class="rounded-lg"
                :loading="resuming.has(record.id)"
                @click="onResume(record)"
              >
                继续
              </a-button>
              <!-- 重新上传：失败的任务可重新构建 -->
              <a-button
                v-if="isRetryable(record)"
                size="mini"
                type="primary"
                class="rounded-lg"
                :loading="retrying.has(record.id)"
                @click="onRetry(record)"
              >
                重新上传
              </a-button>
            </a-space>
          </template>
        </a-table-column>
      </template>
    </a-table>
  </a-modal>
</template>

<style scoped>
:deep(.arco-table-container) {
  border-radius: 8px;
  overflow: hidden;
}
</style>

<!-- 弹框宽度：视口 <1500px 时占 80%，≥1500px 固定 1200px 封顶（纯 CSS）。
     模态框 teleport 到 body，需用非 scoped 样式通过 modal-class 命中 .arco-modal -->
<style>
.recall-modal {
  width: clamp(320px, 80vw, 1200px);
}
</style>
