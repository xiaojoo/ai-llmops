<script setup lang="ts">
import { nextTick, type PropType, ref, watch } from 'vue'
import { useGetDatasetsWithPage } from '@/hooks/use-dataset.ts'
import { useUpdateDraftAppConfig } from '@/hooks/use-app.ts'
import { isEqual } from 'lodash'
import { Message } from '@arco-design/web-vue'
import { showErrorToast } from '@/utils/http/error'
import cloneDeep from 'lodash/cloneDeep'

const props = defineProps({
  app_id: { type: String, required: true },
  retrieval_config: {
    type: Object,
    required: true,
    default: () => ({}),
  },
  datasets: {
    type: Array as PropType<
      {
        id: string
        name: string
        icon: string
        description: string
      }[]
    >,
    required: true,
    default: () => [],
  },
})
const emits = defineEmits(['update:retrieval_config', 'update:datasets'])
const { loading: updateDraftAppConfigLoading, handleUpdateDraftAppConfig } =
  useUpdateDraftAppConfig()
const { loading, paginator, datasets: apiDatasets, loadDatasets } = useGetDatasetsWithPage()
const datasetsModalVisible = ref(false)
const retrievalConfigModalVisible = ref(false)
const isDatasetsInit = ref(false)

type ActivatedDataset = {
  id: string
  name: string
  icon: string
  description: string
}

interface RetrievalConfigForm {
  retrieval_strategy: string
  k: number
  score: number
  agentic_enable?: boolean
  max_rounds?: number
}

const activateDatasets = ref<ActivatedDataset[]>([])
const originDatasets = ref<ActivatedDataset[]>([])
const retrievalConfigForm = ref<RetrievalConfigForm>({} as RetrievalConfigForm)
const originRetrievalConfigForm = ref<RetrievalConfigForm>({} as RetrievalConfigForm)
const isRetrievalConfigInit = ref(false)

const handleScroll = async (event: UIEvent) => {
// 获取滚动距离、可滚动最大距离、客户端/浏览器窗口高度
  const { scrollTop, scrollHeight, clientHeight } = event.target as HTMLElement
  if (scrollTop + clientHeight >= scrollHeight - 10) {
    if (loading.value) {
      return
    }
    await loadDatasets()
  }
}

const isRetrievalConfigFormModified = () => {
  return isEqual(retrievalConfigForm.value, originRetrievalConfigForm.value)
}

const handleCancelDatasetsModal = () => {
  datasetsModalVisible.value = false
  activateDatasets.value = cloneDeep(originDatasets.value)
  isDatasetsInit.value = false
}

const handleCancelRetrievalConfigModal = () => {
  retrievalConfigModalVisible.value = false
  retrievalConfigForm.value = originRetrievalConfigForm.value
  isRetrievalConfigInit.value = false
}

const handleSelectDataset = (idx: number) => {
  const dataset = apiDatasets[idx]
  if (!dataset) return

  if (activateDatasets.value.some((activateDataset) => activateDataset.id === dataset.id)) {
    activateDatasets.value = activateDatasets.value.filter(
      (activateDataset) => activateDataset.id !== dataset.id,
    )
  } else {
    if (activateDatasets.value.length >= 5) {
      Message.warning('关联知识库已超过5个，无法继续关联')
      return
    }
    activateDatasets.value.push({
      id: dataset.id,
      name: dataset.name,
      icon: dataset.icon,
      description: dataset.description,
    })
  }
}

const handleSubmitDatasets = async () => {
  try {
    await handleUpdateDraftAppConfig(props.app_id, {
      datasets: activateDatasets.value.map((activateDataset) => activateDataset.id),
    })
    originDatasets.value = activateDatasets.value
    await nextTick()

    emits('update:datasets', activateDatasets.value)

    handleCancelDatasetsModal()
  } catch (e) {
    showErrorToast(String(e))
  }
}

const handleSubmitRetrievalConfig = async () => {
  try {
    await handleUpdateDraftAppConfig(props.app_id, {
      retrieval_config: retrievalConfigForm.value,
    })
    originRetrievalConfigForm.value = retrievalConfigForm.value
    emits('update:retrieval_config', cloneDeep(retrievalConfigForm.value))

    handleCancelRetrievalConfigModal()
  } catch (e) {
    showErrorToast(String(e))
  }
}

watch(
  () => props.datasets,
  (newValue) => {
    const initData = (newValue || []).map((dataset) => ({
      id: dataset.id,
      name: dataset.name,
      icon: dataset.icon,
      description: dataset.description,
    }))

    activateDatasets.value = cloneDeep(initData)
    originDatasets.value = cloneDeep(initData)
  },
  { immediate: true, deep: true },
)

watch(
  () => props.retrieval_config,
  (newValue) => {
    if (!isRetrievalConfigInit.value || !isRetrievalConfigFormModified()) {
      if (newValue && Object.keys(newValue).length > 0) {
        retrievalConfigForm.value = {
          agentic_enable: false,
          max_rounds: 2,
          ...newValue,
        } as RetrievalConfigForm
        originRetrievalConfigForm.value = { ...retrievalConfigForm.value }

        isRetrievalConfigInit.value = true
      }
    }
  },
  { immediate: true, deep: true },
)

watch(
  () => datasetsModalVisible.value,
  async (newValue) => {
    if (newValue) {
      await loadDatasets(true)
    } else {
      apiDatasets.splice(0, apiDatasets.length)
    }
  },
)

const handleRemoveDataset = async (idx: number) => {
  const newDatasets = [...props.datasets]
  newDatasets.splice(idx, 1)
  await handleUpdateDraftAppConfig(props.app_id, {
    datasets: newDatasets.map((item) => item.id),
  })
  activateDatasets.value = cloneDeep(newDatasets)
  originDatasets.value = cloneDeep(newDatasets)
  emits('update:datasets', newDatasets)
}

// 供外部（左侧「知识库」导航）直接打开选择引用知识库弹窗
defineExpose({ openAdd: () => { datasetsModalVisible.value = true } })
</script>

<template>
  <div class="">
    <a-collapse-item key="datasets" class="app-ability-item">
      <template #header>
        <div class="text-gray-700 font-bold">知识库</div>
      </template>
      <template #extra>
        <a-space>
          <a-button
            size="mini"
            class="rounded-lg px-2"
            @click.stop="retrievalConfigModalVisible = true"
          >
            <template #icon>
              <icon-language />
            </template>
            <div v-if="retrieval_config?.retrieval_strategy == 'semantic'" class="">相似性检索</div>
            <div v-else-if="retrieval_config?.retrieval_strategy == 'full_text'" class="">
              全文检索
            </div>
            <div v-else class="">混合检索</div>
          </a-button>
          <a-button aria-label="添加"
            size="mini"
            type="text"
            class="!text-gray-700"
            @click.stop="datasetsModalVisible = true"
          >
            <template #icon>
              <icon-plus />
            </template>
          </a-button>
        </a-space>
      </template>
      <div v-if="props.datasets?.length > 0" class="flex flex-col gap-1">
        <div
          v-for="(dataset, idx) in props.datasets"
          :key="dataset.id"
          class="flex items-center justify-between bg-white p-3 rounded-lg cursor-pointer hover:shadow-sm group"
        >
          <!-- 左侧知识库信息 -->
          <div class="flex items-center gap-2">
            <a-avatar
              :size="36"
              shape="square"
              class="rounded flex-shrink-0"
              :image-url="dataset.icon"
            />
            <!-- 名称与描述信息 -->
            <div class="flex flex-col flex-1 gap-1 h-9">
              <div class="text-gray-700 font-bold leading-[18px] line-clamp-1">
                {{ dataset.name }}
              </div>
              <div class="text-gray-500 text-xs line-clamp-1">{{ dataset.description }}</div>
            </div>
          </div>
          <!-- 右侧删除按钮 -->
          <a-button aria-label="删除"
            size="mini"
            type="text"
            class="hidden group-hover:block flex-shrink-0 ml-2 !text-red-700 rounded"
            @click="handleRemoveDataset(idx)"
          >
            <template #icon>
              <icon-delete />
            </template>
          </a-button>
        </div>
      </div>
      <div v-else class="text-xs text-gray-500 leading-[28px]">
        引用文本类型数据，实现知识问答，应用最多支持关联5个知识库。
      </div>
    </a-collapse-item>
    <!-- 知识库模态窗 -->
    <a-modal
      :visible="datasetsModalVisible"
      hide-title
      :footer="false"
      width="max(340px, min(400px, calc(100vw - 32px)))"
      class="datasets-modal"
      modal-class="h-[calc(100vh-32px)] right-4"
      @cancel="handleCancelDatasetsModal"
    >
      <!-- 顶部标题 -->
      <div class="flex items-center justify-between mb-6">
        <div class="text-lg font-bold text-gray-700">选择引用知识库</div>
        <a-button aria-label="关闭" type="text" class="text-gray-700" size="small" @click="handleCancelDatasetsModal">
          <template #icon>
            <icon-close />
          </template>
        </a-button>
      </div>
      <!-- 中间知识库容器 -->
      <div class="h-[calc(100vh-180px)] mb-4 overflow-scroll scrollbar-w-none">
        <a-spin
          :loading="loading"
          class="block h-full w-full scrollbar-w-none overflow-scroll"
          @scroll="handleScroll"
        >
          <!-- 知识库列表 -->
          <div class="flex flex-col gap-2">
            <!-- 有数据UI状态 -->
            <div
              v-for="(dataset, idx) in apiDatasets"
              :key="dataset.id"
              :class="[
                `flex items-center gap-2 border px-3 py-2 rounded-lg cursor-pointer hover:bg-blue-50 hover:border-blue-700 ${activateDatasets.some((activateDataset) => activateDataset.id === dataset.id) ? 'bg-blue-50 border-blue-700' : ''}`,
              ]"
              @click="handleSelectDataset(idx)"
            >
              <a-avatar
                :size="24"
                shape="square"
                class="flex-shrink-0 rounded"
                :image-url="dataset.icon"
              />
              <div class="flex flex-col flex-1 min-w-0">
                <div class="line-clamp-1 text-gray-700 text-sm font-medium">{{ dataset.name }}</div>
                <div class="line-clamp-1 text-gray-400 text-xs">{{ dataset.description }}</div>
              </div>
              <icon-check
                v-if="activateDatasets.some((s) => s.id === dataset.id)"
                class="text-blue-700 flex-shrink-0"
              />
            </div>
            <!-- 无数据UI状态-->
            <a-empty
              v-if="apiDatasets.length === 0"
              description="没有可用的知识库"
              class="h-[400px] flex flex-col items-center justify-center"
            />
          </div>
          <!-- 加载器 -->
          <a-row v-if="paginator.total_page >= 2">
            <a-col
              v-if="paginator.current_page <= paginator.total_page"
              :span="24"
              class="!text-center"
            >
              <a-space class="my-4">
                <a-spin />
                <div class="text-gray-400">加载中</div>
              </a-space>
            </a-col>
            <a-col v-else :span="24" class="!text-center">
              <div class="text-gray-400 my-4">数据已加载完成</div>
            </a-col>
          </a-row>
        </a-spin>
      </div>
      <!-- 底部选中知识库及按钮 -->
      <div class="flex items-center justify-between">
        <!-- 左侧提示文字 -->
        <div class="">{{ activateDatasets.length }} 个知识库被选中</div>
        <!-- 按钮组 -->
        <a-space :size="12">
          <a-button class="rounded-lg" @click="retrievalConfigModalVisible = true">检索设置</a-button>
          <a-button class="rounded-lg" @click="handleCancelDatasetsModal">取消</a-button>
          <a-button
            :loading="updateDraftAppConfigLoading"
            type="primary"
            class="rounded-lg"
            @click="handleSubmitDatasets"
          >
            保存
          </a-button>
        </a-space>
      </div>
    </a-modal>
    <!-- 检索设置模态窗 -->
    <a-modal
      :visible="retrievalConfigModalVisible"
      hide-title
      :footer="false"
      width="max(440px, min(560px, calc(100vw - 32px)))"
      modal-class="rounded-xl"
      @cancel="handleCancelRetrievalConfigModal"
    >
      <!-- 顶部标题 -->
      <div class="flex items-center justify-between">
        <div class="text-lg font-bold text-gray-700">检索设置</div>
        <a-button aria-label="关闭"
          type="text"
          class="text-gray-700"
          size="small"
          @click="handleCancelRetrievalConfigModal"
        >
          <template #icon>
            <icon-close />
          </template>
        </a-button>
      </div>
      <!-- 中间表单内容 -->
      <a-form :model="retrievalConfigForm" @submit="handleSubmitRetrievalConfig" class="pt-6">
        <a-form-item field="retrieval_strategy" label="检索策略" label-align="left">
          <a-radio-group
            v-model:model-value="retrievalConfigForm.retrieval_strategy"
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
            <a-slider v-model:model-value="retrievalConfigForm.k" :step="1" :min="1" :max="10" />
            <a-input-number
              v-model:model-value="retrievalConfigForm.k"
              class="w-[80px]"
              :default-value="4"
            />
          </div>
        </a-form-item>
        <a-form-item field="score" label="最小匹配度">
          <div class="flex items-center gap-4 w-full pl-3">
            <a-slider
              v-model:model-value="retrievalConfigForm.score"
              :step="0.01"
              :min="0"
              :max="0.99"
            />
            <a-input-number
              v-model:model-value="retrievalConfigForm.score"
              class="w-[80px]"
              :min="0"
              :max="0.99"
              :step="0.01"
              :precision="2"
              :default-value="0.5"
            />
          </div>
        </a-form-item>
        <!-- Agentic 重检：结果校验 + 多轮重检 -->
        <a-form-item
          field="agentic_enable"
          label="Agentic 重检"
          :label-attrs="{ for: 'agentic_enable_switch_apps' }"
        >
          <div class="flex flex-col gap-2 w-full pl-3">
            <!-- 开关行 -->
            <div class="flex items-center gap-3">
              <a-switch id="agentic_enable_switch_apps" v-model="retrievalConfigForm.agentic_enable" />
              <span class="text-xs text-gray-600 font-medium">开启 Agentic 重检</span>
            </div>
            <!-- 重检轮数：样式与最大召回数量一致（slider + 数字框），上限 3 轮 -->
            <div v-if="retrievalConfigForm.agentic_enable" class="flex items-center gap-4 w-full">
              <a-slider
                v-model:model-value="retrievalConfigForm.max_rounds"
                :step="1"
                :min="1"
                :max="3"
              />
              <a-input-number
                v-model:model-value="retrievalConfigForm.max_rounds"
                class="w-[80px]"
                :default-value="2"
                :min="1"
                :max="3"
              />
            </div>
            <!-- 描述 -->
            <div class="text-xs text-gray-400 leading-relaxed">
              召回后由大模型评估结果充分性，不足时换策略扩大召回再检，最多可重检
              {{ retrievalConfigForm.agentic_enable ? retrievalConfigForm.max_rounds : 0 }} 轮
            </div>
          </div>
        </a-form-item>
        <!-- 底部按钮 -->
        <div class="flex items-center justify-between">
          <div class=""></div>
          <a-space :size="16">
            <a-button class="rounded-lg" @click="handleCancelRetrievalConfigModal">取消</a-button>
            <a-button
              :loading="updateDraftAppConfigLoading"
              type="primary"
              html-type="submit"
              class="rounded-lg"
              >保存
            </a-button>
          </a-space>
        </div>
      </a-form>
    </a-modal>
  </div>
</template>

<style>
.datasets-modal {
  .arco-modal-wrapper {
    text-align: right;
  }
}
</style>
