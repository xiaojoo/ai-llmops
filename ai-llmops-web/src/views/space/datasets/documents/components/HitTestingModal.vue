<script setup lang="ts">
import moment from 'moment'
import { h, reactive, ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import type { TableData } from '@arco-design/web-vue'
import { getDatasetQueries, hit } from '@/services/dataset.ts'
import type { GetDatasetQueriesResponse, HitSegment } from '@/models/dataset.ts'

type QueryItem = GetDatasetQueriesResponse['data'][number]

// 命中片段在模型里缺少内容/类型/页码等展示字段，这里扩展为局部视图类型（字段可选，兼容模型返回）
interface HitSegmentView extends HitSegment {
  content?: string
  content_type?: string
  image_url?: string
  page_number?: number
  section_title?: string
}

// agentic 重检轨迹步骤（模型的 trace 字段类型不完整，按模板实际使用字段定义）
interface HitTraceStep {
  round: number
  strategy: string
  query: string
  k: number
  hits: number
  sufficient: boolean
  score: number
  missing: string
}

const props = defineProps({
  visible: { type: Boolean, required: true },
  dataset_id: { type: String, required: true },
})
const emits = defineEmits(['update:visible'])

// 最近查询相关
const queriesLoading = ref(false)
const queries = reactive<QueryItem[]>([])
const loadQueries = async () => {
  try {
    queriesLoading.value = true
    const resp = await getDatasetQueries(props.dataset_id)
    const data = resp.data

    queries.splice(0, queries.length, ...data)
  } finally {
    queriesLoading.value = false
  }
}

// 知识库检索设置相关
const retrievalSettingModalVisible = ref(false)
const defaultRetrievalSetting = {
  retrieval_strategy: 'semantic',
  k: 5,
  score: 0.5,
  agentic_enable: false,
  max_rounds: 2,
}
const retrievalSettingForm = reactive({ ...defaultRetrievalSetting })

const hideRetrievalSettingModal = () => {
  // 复原检索策略
  Object.assign(retrievalSettingForm, { ...hitTestingForm })

  // 隐藏模态框
  retrievalSettingModalVisible.value = false
}

const saveRetrievalSetting = () => {
  // 重置检索查询片段列表
  hitTestingSegments.splice(0, hitTestingSegments.length)

  // 更新索引策略
  Object.assign(hitTestingForm, { query: hitTestingForm.query, ...retrievalSettingForm })

  retrievalSettingModalVisible.value = false
}

// 召回设置相关
const hitTestingLoading = ref(false)
const hitTestingSegments = reactive<HitSegmentView[]>([])
// agentic 命中轨迹：每轮 {round, strategy, query, k, hits, sufficient, score, missing}
const hitTrace = ref<HitTraceStep[]>([])
// 记录已展开查看全文的片段 id（Set 用 ref 包装以便响应式）
const expandedSegments = ref<Set<string>>(new Set())
const hitTestingForm = reactive({
  query: '',
  ...defaultRetrievalSetting,
})

const hideHitTestingModal = () => emits('update:visible', false)

// 切换片段展开/收起
const toggleSegmentExpand = (segment: HitSegment) => {
  const set = expandedSegments.value
  if (set.has(segment.id)) {
    set.delete(segment.id)
  } else {
    set.add(segment.id)
  }
  // 触发响应式更新
  expandedSegments.value = new Set(set)
}

const isSegmentExpanded = (segment: HitSegment) => expandedSegments.value.has(segment.id)

const handleHitTesting = async () => {
  // 检索的源文件是否为空
  if (hitTestingForm.query.trim() === '') {
    Message.error('检索源文件不能为空')
    return
  }

  try {
    hitTestingLoading.value = true
    const resp = await hit(props.dataset_id, hitTestingForm)
    const data = resp.data
    // 新响应结构 {list, trace}；兼容旧数组
    const segments = Array.isArray(data) ? data : (data?.list || [])
    hitTestingSegments.splice(0, hitTestingSegments.length, ...segments)
    hitTrace.value = (Array.isArray(data) ? [] : (data?.trace || [])) as unknown as HitTraceStep[]
    // 新检索后重置展开状态
    expandedSegments.value = new Set()

    await loadQueries()
  } finally {
    hitTestingLoading.value = false
  }
}

watch(
  () => props.visible,
  async (newValue) => {
    if (newValue) {
      // 模态框开启，加载最近查询
      await loadQueries()
    } else {
      // 模态窗关闭，清空最近查询，召回记录，初始化检索配置
      queries.splice(0, queries.length)
      hitTestingSegments.splice(0, hitTestingSegments.length)
      hitTrace.value = []
      expandedSegments.value = new Set()
      Object.assign(hitTestingForm, { query: '', ...defaultRetrievalSetting })
      Object.assign(retrievalSettingForm, { ...defaultRetrievalSetting })
    }
  },
)

const columns = [
  {
    title: '数据源',
    dataIndex: 'source',
    width: 150,
  },
  {
    title: '文本',
    dataIndex: 'query',
    render: ({ record }: { record: TableData }) => {
      return h(
        'div',
        { class: 'line-clamp-1 overflow-hidden text-ellipsis whitespace-nowrap' },
        record.query,
      )
    },
  },
  {
    title: '时间',
    dataIndex: 'created_at',
    width: 160,
    render: ({ record }: { record: TableData }) => {
      return moment(record.created_at * 1000).format('YYYY-MM-DD HH:mm')
    },
  },
]
</script>

<template>
  <!-- 召回测试 -->
  <a-modal
    :visible="props.visible"
    hide-title
    :footer="false"
    modal-class="recall-modal rounded-xl overflow-auto scrollbar-w-none"
    @cancel="hideHitTestingModal"
  >
    <!-- 顶部标题  h-3/4-->
    <div class="flex items-center justify-between">
      <div class="text-lg font-bold text-gray-700">召回测试</div>
      <a-button aria-label="关闭" @click="hideHitTestingModal" type="text" class="!text-gray-700" size="small">
        <template #icon>
          <icon-close />
        </template>
      </a-button>
    </div>
    <!-- 副标题 -->
    <div class="text-gray-500">基于给定的查询文本测试知识库的召回效果</div>
    <!-- 中间内容区 -->
    <div class="pt-6">
      <div class="w-full flex justify-between gap-2">
        <!-- 左侧输入框以及最近查询：与右侧等高的限高滚动（显示滚动条） -->
        <div class="flex flex-col w-1/2 max-h-[60vh] overflow-y-auto pr-1">
          <!-- 顶部输入框 -->
          <div class="border border-blue-700 bg-blue-100 rounded-lg flex flex-col mb-6">
            <!-- 输入框标题-->
            <div class="flex items-center justify-between px-4 py-1.5">
              <div class="font-bold text-gray-900">源文本</div>
              <a-button
                size="small"
                class="rounded-lg px-2"
                @click="retrievalSettingModalVisible = true"
              >
                <template #icon>
                  <icon-language />
                </template>
                <div v-if="hitTestingForm.retrieval_strategy === 'semantic'">相似性检索</div>
                <div v-else-if="hitTestingForm.retrieval_strategy === 'full_text'">全文检索</div>
                <div v-else>混合检索</div>
              </a-button>
            </div>
            <!-- 输入框容器 -->
            <div class="bg-white rounded-lg p-2">
              <!-- 输入框 -->
              <a-textarea
                id="query"
                name="query"
                autocomplete="off"
                v-model:model-value="hitTestingForm.query"
                placeholder="请输入文本，建议使用简短的陈述句"
                :max-length="200"
                :auto-size="{ minRows: 6, maxRows: 6 }"
                class="!bg-white border-0! mb-1"
              />
              <!-- 字符限制以及召回按钮 -->
              <div class="flex items-center justify-between">
                <a-tag size="small" class="rounded text-gray-700">
                  {{ hitTestingForm.query.length }}/200
                </a-tag>
                <a-button
                  :loading="hitTestingLoading"
                  type="primary"
                  size="small"
                  class="rounded-lg"
                  @click="handleHitTesting"
                >
                  召回测试
                </a-button>
              </div>
            </div>
          </div>
          <!-- 底部最近查询 -->
          <div class="">
            <div class="text-gray-700 font-bold mb-4">最近查询</div>
            <a-table
              :loading="queriesLoading"
              :columns="columns"
              :pagination="false"
              :data="queries"
              :bordered="{ wrapper: true }"
              table-layout-fixed
              class="rounded-lg overflow-hidden"
              @row-click="(record: TableData) => (hitTestingForm.query = record.query)"
            />
          </div>
        </div>
        <!-- 右侧召回列表：轨迹面板独立固定（不滚动），仅召回列表滚动 -->
        <div class="w-1/2 flex flex-col max-h-[60vh]">
          <!-- Agentic 命中轨迹：独立模块，不参与滚动 -->
          <div
            v-if="hitTrace.length > 0"
            class="mb-3 p-3 bg-blue-50 border border-blue-200 rounded-lg shrink-0"
          >
            <div class="flex items-center gap-2 mb-2">
              <icon-search class="!text-blue-600" />
              <span class="text-xs font-bold text-blue-700">Agentic 重检轨迹</span>
              <span class="text-xs text-blue-400">共 {{ hitTrace.length }} 轮</span>
            </div>
            <div class="flex flex-col gap-2">
              <div
                v-for="step in hitTrace"
                :key="step.round"
                class="flex items-start gap-2 text-xs"
              >
                <span
                  class="shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-white"
                  :class="step.sufficient ? 'bg-green-500' : 'bg-amber-500'"
                >{{ step.round }}</span>
                <div class="min-w-0">
                  <div class="text-gray-700">
                    {{ step.strategy }} 策略 · 召回 {{ step.k }} 候选 / 命中 {{ step.hits }}
                    <span v-if="!step.sufficient" class="text-amber-600 font-medium">· 不充分（{{ step.score }} 分）</span>
                    <span v-else class="text-green-600 font-medium">· 充分（{{ step.score }} 分）</span>
                  </div>
                  <div v-if="!step.sufficient && step.missing" class="text-gray-500 line-clamp-2">
                    → 补充查询：{{ step.missing }}
                  </div>
                  <div v-else-if="step.round === 1 && step.sufficient" class="text-gray-400">
                    首轮即充分，无需重检
                  </div>
                </div>
              </div>
            </div>
          </div>
          <!-- 召回列表：独立滚动区域 -->
          <div class="flex-1 min-h-0 overflow-y-auto pr-1">
            <a-spin :loading="hitTestingLoading" class="w-full">
            <div v-if="hitTestingSegments.length > 0" class="flex flex-col gap-3">
              <!-- 每条召回记录横向展示（单列），可展开查看全文 -->
              <div
                v-for="segment in hitTestingSegments"
                :key="segment.id"
                class="p-3 bg-gray-50 rounded-lg border border-gray-200"
              >
                <!-- 顶部：得分 + 序号 + 展开按钮 -->
                <div class="flex items-center justify-between gap-2 mb-1.5">
                  <div class="flex items-center gap-2 min-w-0">
                    <span class="text-gray-400 text-xs shrink-0">#{{ hitTestingSegments.indexOf(segment) + 1 }}</span>
                    <template v-if="hitTestingForm.retrieval_strategy === 'semantic'">
                      <icon-pushpin class="shrink-0" />
                      <a-progress
                        class="shrink-0 w-[100px]"
                        :stroke-width="6"
                        :show-text="false"
                        :percent="Math.min(segment.score * 100, 100)"
                      />
                      <div class="text-gray-700 text-xs shrink-0">
                        {{ segment.score ? segment.score.toFixed(2) : '0.00' }}
                      </div>
                    </template>
                    <template v-else>
                      <div class="text-gray-700 text-xs shrink-0">
                        {{ segment.score ? segment.score.toFixed(2) : '0.00' }}
                      </div>
                    </template>
                  </div>
                  <a-button
                    size="mini"
                    class="rounded shrink-0"
                    @click="toggleSegmentExpand(segment)"
                  >
                    <template #icon>
                      <icon-down v-if="!isSegmentExpanded(segment)" />
                      <icon-up v-else />
                    </template>
                    {{ isSegmentExpanded(segment) ? '收起' : '展开' }}
                  </a-button>
                </div>
                <!-- 内容：图片块显示图片预览；其余默认截断 4 行，展开显示全部 -->
                <div v-if="segment.content_type === 'image' && segment.image_url" class="mb-1.5">
                  <img
                    :src="segment.image_url"
                    class="max-w-full max-h-[180px] rounded-lg border border-gray-200 object-contain bg-white"
                    alt="图片片段"
                  />
                </div>
                <div
                  v-else
                  :class="isSegmentExpanded(segment)
                    ? 'text-gray-500 text-xs break-all whitespace-pre-wrap'
                    : 'text-gray-500 text-xs line-clamp-4 break-all'"
                >
                  {{ segment.content }}
                </div>
                <!-- 文档归属信息 -->
                <div class="flex items-center gap-2 text-gray-400 text-xs mt-2 pt-2 border-t border-gray-200">
                  <icon-file class="shrink-0" />
                  <div class="line-clamp-1">{{ segment.document.name }}</div>
                  <a-tag v-if="segment.content_type === 'table'" size="small" color="arcoblue" class="shrink-0">表格</a-tag>
                  <a-tag v-else-if="segment.content_type === 'image'" size="small" color="green" class="shrink-0">图片</a-tag>
                  <!-- 页码直接显示；章节标题（若有）放到 tooltip 弹出框，不占卡片 -->
                  <a-tooltip
                    v-if="segment.page_number"
                    :content="segment.section_title ? `第 ${segment.page_number} 页 · ${segment.section_title}` : `第 ${segment.page_number} 页`"
                  >
                    <a-tag size="small" class="shrink-0">第 {{ segment.page_number }} 页</a-tag>
                  </a-tooltip>
                </div>
              </div>
            </div>
            <!-- 无数据 -->
            <a-empty v-else />
            </a-spin>
          </div>
        </div>
      </div>
    </div>
  </a-modal>
  <!-- 检索设置 -->
  <a-modal
    :visible="retrievalSettingModalVisible"
    hide-title
    :footer="false"
    width="max(400px, min(520px, calc(100vw - 32px)))"
    modal-class="rounded-xl"
  >
    <!-- 顶部标题 -->
    <div class="flex items-center justify-between">
      <div class="text-lg font-bold text-gray-700">检索设置</div>
      <a-button aria-label="关闭" @click="hideRetrievalSettingModal" type="text" class="!text-gray-700" size="small">
        <template #icon>
          <icon-close />
        </template>
      </a-button>
    </div>
    <!-- 中间表单内容 -->
    <a-form class="pt-6" :model="retrievalSettingForm" @submit="saveRetrievalSetting">
      <a-form-item field="retrieval_strategy" label="检索策略" label-align="left">
        <a-radio-group
          v-model:model-value="retrievalSettingForm.retrieval_strategy"
          default-value="semantic"
          :options="[
            { label: '混合策略', value: 'hybrid' },
            { label: '全文检索', value: 'full_text' },
            { label: '相似性检索', value: 'semantic' },
          ]"
        />
      </a-form-item>
      <a-form-item field="k" label="最大召回数量">
        <div class="flex items-center gap-4 w-full pl-3">
          <a-slider v-model:model-value="retrievalSettingForm.k" :step="1" :min="1" :max="10" />
          <div class="w-[80px] shrink-0">
            <a-input-number
              id="retrieval-k"
              name="retrieval-k"
              autocomplete="off"
              v-model:model-value="retrievalSettingForm.k"
              :default-value="4"
            />
          </div>
        </div>
      </a-form-item>
      <a-form-item field="score" label="最小匹配度">
        <div class="flex items-center gap-4 w-full pl-3">
          <a-slider
            v-model:model-value="retrievalSettingForm.score"
            :step="0.01"
            :min="0"
            :max="0.99"
          />
          <div class="w-[80px] shrink-0">
            <a-input-number
              v-model:model-value="retrievalSettingForm.score"
              :default-value="0.5"
              :step="0.01"
              :min="0"
              :max="0.99"
              :precision="2"
              name="score_input"
              autocomplete="off"
              aria-label="最小匹配度数值"
              :input-attrs="{ id: 'score_inner_input' }"
            />
          </div>
        </div>
      </a-form-item>
      <!-- Agentic RAG：结果校验 + 多轮重检 -->
      <a-form-item
        field="agentic_enable"
        label="Agentic 重检"
        :label-attrs="{ for: 'agentic_enable_switch_ht' }"
      >
        <div class="flex flex-col gap-2 w-full pl-3">
          <!-- 开关行 -->
          <div class="flex items-center gap-3">
            <a-switch id="agentic_enable_switch_ht" v-model="retrievalSettingForm.agentic_enable" />
            <span class="text-xs text-gray-600 font-medium">开启 Agentic 重检</span>
          </div>
          <!-- 重检轮数：样式与最大召回数量一致（slider + 数字框），上限 3 轮 -->
          <div class="flex items-center gap-4 w-full">
            <a-slider v-model:model-value="retrievalSettingForm.max_rounds" :step="1" :min="1" :max="3" />
            <div class="w-[80px] shrink-0">
              <a-input-number
                v-model:model-value="retrievalSettingForm.max_rounds"
                :default-value="2"
                :min="1"
                :max="3"
              />
            </div>
          </div>
          <!-- 描述 -->
          <div class="text-xs text-gray-400 leading-relaxed">
            召回后由大模型评估结果充分性，不足时换策略扩大召回再检，最多可重检 {{ retrievalSettingForm.max_rounds }} 轮
          </div>
        </div>
      </a-form-item>
      <!-- 底部按钮-->
      <div class="flex items-center justify-end">
        <a-space :size="16">
          <a-button class="rounded-lg" @click="hideRetrievalSettingModal">取消</a-button>
          <a-button type="primary" html-type="submit" class="rounded-lg">保存</a-button>
        </a-space>
      </div>
    </a-form>
  </a-modal>
</template>

<style scoped>
/* 最近查询表格圆角（与召回卡片一致的圆角） */
:deep(.arco-table-container) {
  border-radius: 8px;
  overflow: hidden;
}
</style>

<!-- 弹框宽度：min(520px, 100vw-32px)——不超过 520px，窄视口时随视口收缩（不出现横向滚动）
     模态框 teleport 到 body，需用非 scoped 样式通过 modal-class 命中 .arco-modal -->
<style>
.recall-modal {
  width: min(520px, calc(100vw - 32px));
}
</style>
