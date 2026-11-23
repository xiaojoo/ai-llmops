<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { computed, ref } from 'vue'
import moment from 'moment'
import {
  useDeleteSegment,
  useGetDocument,
  useGetSegmentsWithPage,
  useUpdateSegmentEnabled,
} from '@/hooks/use-dataset.ts'
import CreateOrUpdateSegmentModal from '@/views/space/datasets/documents/segments/components/CreateOrUpdateSegmentModal.vue'

const route = useRoute()
const router = useRouter()
const datasetId = computed(() => String(route.params.dataset_id))
const { loading, segments, paginator, loadSegments, loadSegmentsByPage } = useGetSegmentsWithPage(
  String(route.params?.dataset_id),
  String(route.params?.document_id),
)
// 模型里 GetSegmentsWithPageResponse 的 list 被泛型多包了一层数组类型，
// 实际运行数据是扁平片段列表；这里展平后再渲染，避免 v-for 元素类型错误
const segmentList = computed(() => segments.flat())
const { document } = useGetDocument(
  String(route.params?.dataset_id),
  String(route.params?.document_id),
)
const { handleUpdate } = useUpdateSegmentEnabled()
const { handleDelete } = useDeleteSegment()
const useCreateOrUpdateModalVisible = ref(false)
const updateSegmentID = ref('')

const onSearch = (value: string) => {
  router.push({
    path: route.path,
    query: {
      ...route.query,
      search_word: value,
    },
  })
}

// 分页切换
const onPageChange = (page: number) => {
  loadSegmentsByPage(page)
}

// 每页条数变更：更新 page_size 并回到第一页
const onPageSizeChange = (size: number) => {
  paginator.page_size = size
  loadSegmentsByPage(1)
}

const addSegments = () => {
  useCreateOrUpdateModalVisible.value = true
  updateSegmentID.value = ''
}

const updateSegmentEnable = async (
  type: 'search' | 'segment-enabled',
  payload: {
    value: boolean
    segmentId: string
  },
) => {
  if (type === 'segment-enabled') {
    await handleUpdate(
      route.params?.dataset_id as string,
      route.params?.document_id as string,
      payload.segmentId,
      payload.value,
    )
  }
}

const deleteSegment = async (segment_id: string) => {
  await handleDelete(
    route.params?.dataset_id as string,
    route.params?.document_id as string,
    segment_id,
    () => {
      loadSegments(true)
    },
  )
}
</script>

<template>
  <!-- 调整边距+隐藏 -->
  <div class="px-6 pt-6 flex flex-col overflow-hidden h-full">
    <!-- 固定顶部 -->
    <div class="sticky top-0 z-20 bg-gray-50">
      <div class="sticky top-0 z-20 bg-gray-50">
        <!-- 顶部回退按钮+文档详情 -->
        <div class="flex items-center w-full gap-2 mb-6">
          <!-- 左侧回退按钮 -->
          <router-link
            :to="{
              name: 'space-datasets-documents-list',
              params: { dataset_id: datasetId },
            }"
          >
            <a-button aria-label="返回" size="mini" type="text" class="!text-gray-700">
              <template #icon>
                <icon-left />
              </template>
            </a-button>
          </router-link>
          <!-- 右侧文档信息 -->
          <div class="flex items-center gap-3">
            <!-- 文档图标 -->
            <a-avatar :size="40" shape="square" class="rounded-lg bg-blue-700"
              ><icon-file
            /></a-avatar>
            <!-- 文档信息 -->
            <div class="flex flex-col justify-between h-[40]">
              <a-skeleton-line v-if="!document?.name" :widths="[100]" />
              <div v-else class="text-gray-700">文档 / {{ document.name }}</div>
              <div v-if="!document?.name" class="flex items-center gap-2">
                <a-skeleton-line :widths="[60]" :line-height="18" />
                <a-skeleton-line :widths="[60]" :line-height="18" />
                <a-skeleton-line :widths="[60]" :line-height="18" />
              </div>
              <div v-else class="flex items-center gap-2">
                <a-tag
                  size="small"
                  class="rounded h-[18px] leading-[18px] bg-gray-200 text-gray-500"
                  >{{ document.segment_count }} 文档片段</a-tag
                >
                <a-tag
                  size="small"
                  class="rounded h-[18px] leading-[18px] bg-gray-200 text-gray-500"
                  >{{ document.hit_count }} 命中</a-tag>
                <a-tag
                  v-if="document.title"
                  size="small"
                  class="rounded h-[18px] leading-[18px] bg-gray-200 text-gray-500"
                  >标题：{{ document.title }}</a-tag
                >
                <a-tag
                  v-if="document.page_count"
                  size="small"
                  class="rounded h-[18px] leading-[18px] bg-gray-200 text-gray-500"
                  >{{ document.page_count }} 页</a-tag
                >
                <a-tooltip
                  v-if="document.footer"
                  :content="`页脚：${document.footer}`"
                >
                  <a-tag
                    size="small"
                    class="rounded h-[18px] leading-[18px] bg-gray-200 text-gray-500 max-w-[200px]"
                    >页脚：{{ document.footer }}</a-tag
                  >
                </a-tooltip>
                <a-tag
                  size="small"
                  class="rounded h-[18px] leading-[18px] bg-gray-200 text-gray-500"
                >
                  {{ moment((document.updated_at ?? 0) * 1000).format('YYYY-MM-DD HH:mm:dd') }}
                  最后编辑
                </a-tag>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    <!-- 中间检索以及功能按钮 -->
    <div class="flex items-center justify-between mb-6">
      <!-- 左侧搜索框 -->
      <div class="w-[200px] shrink-0">
        <a-input-search
          :default-value="route.query?.search_word || ''"
          placeholder="请输入关键词搜索文档"
          class="bg-white rounded-lg border-gray-200"
          @search="onSearch"
          allow-clear
        />
      </div>
      <!--右侧按钮 -->
      <a-space :size="12">
        <div
          class="seg-avail flex items-center gap-2 h-8 leading-8 bg-white rounded-lg px-3 text-gray-700"
        >
          <div
            v-if="document.enabled"
            class="w-2 h-2 bg-green-500 border border-green-700 rounded-sm"
          ></div>
          <div v-else class="w-2 h-2 bg-green-500 border border-green-700 rounded-sm"></div>
          {{ document.enabled ? '可用' : '已禁用 ' }}
        </div>
        <a-button type="primary" class="rounded-lg" @click="addSegments">
          <template #icon>
            <icon-file />
          </template>
          添加片段
        </a-button>
      </a-space>
    </div>
    <!-- 中间列表区域 -->

    <a-spin
      :loading="loading"
      class="block h-full w-full scrollbar-w-none overflow-scroll"
    >
      <!-- 片段列表（响应式列数：≥992px 4列 / ≥768px 3列 / ≥576px 2列 / <576px 1列） -->
      <a-row :gutter="[20, 20]">
        <a-col
          v-for="segment in segmentList"
          :key="segment.id"
          :xs="24"
          :sm="12"
          :md="8"
          :lg="6"
        >
          <a-card hoverable class="cursor-pointer rounded-lg">
            <div class="flex flex-wrap items-center justify-between gap-1 mb-2">
              <div class="flex items-center gap-1.5 min-w-0">
                <a-tag size="small" class="rounded-md text-gray-500 flex-shrink-0">
                  #{{ segment.position.toString().padStart(3, '0') }}
                </a-tag>
                <!-- 来源定位：页码直接显示；章节标题放入 tooltip 弹出框（不占卡片） -->
                <a-tooltip
                  v-if="segment.page_number"
                  :content="segment.section_title ? `第 ${segment.page_number} 页 · ${segment.section_title}` : `第 ${segment.page_number} 页`"
                >
                  <a-tag size="small" class="rounded-md text-gray-500 flex-shrink-0">第 {{ segment.page_number }} 页</a-tag>
                </a-tooltip>
              </div>
              <div class="flex items-center flex-none">
                <div class="flex items-center gap-1 text-xs text-gray-700">
                  {{ segment.enabled ? '已启用' : '已禁用' }}
                  <div
                    v-if="segment.enabled"
                    class="w-2 h-2 bg-green-500 border border-green-700 rounded-sm"
                  ></div>
                  <div v-else class="w-2 h-2 bg-green-500 border border-green-700 rounded-sm"></div>
                </div>
                <a-divider direction="vertical" />
                <a-switch
                  v-model:model-value="segment.enabled"
                  :disabled="segment.status !== 'completed'"
                  @change="
                    (value) =>
                      updateSegmentEnable('segment-enabled', {
                        value: value as boolean,
                        segmentId: segment.id,
                      })
                  "
                  type="round"
                  size="small"
                />
              </div>
            </div>
            <!-- 中间片段内容：图片块点击放大预览（不打开编辑框）；其余块点击打开编辑框 -->
            <div
              class="leading-[18px] text-gray-700 h-[72px] line-clamp-4 mb-2 break-all"
              @click="
                () => {
                  if (segment.content_type !== 'image') {
                    updateSegmentID = segment.id
                    useCreateOrUpdateModalVisible = true
                  }
                }
              "
            >
              <!-- 图片块：居中显示，宽高 100%；a-image 自带点击放大预览（大图），不触发编辑框 -->
              <div
                v-if="segment.content_type === 'image' && segment.image_url"
                class="w-full h-full flex items-center justify-center overflow-hidden rounded bg-gray-50"
              >
                <a-image
                  :src="segment.image_url"
                  :preview="true"
                  class="!w-full !h-full object-contain img-full"
                  alt="图片片段"
                />
              </div>
              <template v-else>{{ segment.content }}</template>
            </div>
            <!-- 底部扩展信息 -->
            <div class="flex flex-wrap items-center justify-between gap-1">
              <div class="flex items-center gap-3 min-w-0 flex-wrap">
                <a-tag
                  v-if="segment.content_type === 'table'"
                  size="small"
                  color="arcoblue"
                  class="rounded"
                  >表格</a-tag
                >
                <a-tag
                  v-else-if="segment.content_type === 'image'"
                  size="small"
                  color="green"
                  class="rounded"
                  >图片</a-tag
                >
                <div class="flex items-center gap-1 text-xs text-gray-500">
                  <icon-bookmark />
                  {{ segment.character_count }} 字符
                </div>
                <div class="flex items-center gap-1 text-xs text-gray-500">
                  <icon-pushpin />
                  {{ segment.hit_count }} 命中
                </div>
              </div>
              <a-button aria-label="删除"
                type="text"
                size="mini"
                class="!text-gray-500 flex-none"
                @click="deleteSegment(segment.id)"
              >
                <template #icon>
                  <icon-delete />
                </template>
              </a-button>
            </div>
          </a-card>
        </a-col>
        <a-col v-if="segments.length === 0" :span="24">
          <a-empty
            description="没有可用的文档片段"
            class="h-[400px] flex flex-col items-center justify-center"
          />
        </a-col>
      </a-row>
      <!-- 分页器 -->
      <div
        v-if="paginator.total_record > 0"
        class="flex items-center justify-end py-4"
      >
        <a-pagination
          :current="paginator.current_page"
          :page-size="paginator.page_size"
          :total="paginator.total_record"
          show-total
          show-page-size
          :page-size-options="[10, 20, 50]"
          @change="onPageChange"
          @page-size-change="onPageSizeChange"
        />
      </div>
    </a-spin>
    <!-- 新增/修改模态框 -->
    <create-or-update-segment-modal
      v-model:visible="useCreateOrUpdateModalVisible"
      :dataset_id="route.params?.dataset_id as string"
      :document_id="route.params?.document_id as string"
      :segment_id="updateSegmentID"
      :callback="() => loadSegments(true)"
    />
  </div>
</template>

<style scoped>
.text-center {
  text-align: center;
}

/* 最小视口：隐藏「添加片段」旁的「可用」状态块，按钮保持可见 */
@media (max-width: 640px) {
  .seg-avail {
    display: none;
  }
}

/* 图片块：a-image 内部 img 铺满容器（class 只作用到 .arco-image 根元素） */
:deep(.img-full .arco-image-img) {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
</style>
