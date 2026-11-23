<script setup lang="ts">
import { Message, type ValidatedError } from '@arco-design/web-vue'
import { computed, ref, watch } from 'vue'
import cloneDeep from 'lodash/cloneDeep'
import { useVueFlow } from '@vue-flow/core'
import { getReferencedVariables } from '@/utils/helper.ts'
import { useGetDatasetsWithPage } from '@/hooks/use-dataset.ts'

const props = defineProps({
  visible: { type: Boolean, required: true, default: false },
  node: { type: Object, required: true, default: () => ({}) },
  loading: { type: Boolean, required: true, default: false },
})

const emits = defineEmits(['updateNode', 'update:visible'])
const datasetsModalVisible = ref(false)
type DatasetRetrievalFormDataset = { id: string; name: string; icon: string; description: string }
type DatasetRetrievalFormInput = { name: string; type: string; content: string; ref: string }
type DatasetRetrievalForm = {
  id?: string
  type?: string
  title?: string
  description?: string
  datasets: DatasetRetrievalFormDataset[]
  retrieval_config: { retrieval_strategy: string; k: number; score: number }
  inputs: DatasetRetrievalFormInput[]
  outputs?: { name: string; type: string; value: { type: string; content: string | number } }[]
}
const tempDatasets = ref<DatasetRetrievalFormDataset[]>([])
const { nodes, edges } = useVueFlow()
const form = ref<DatasetRetrievalForm>({
  retrieval_config: { retrieval_strategy: 'semantic', k: 4, score: 0 },
  datasets: [],
  inputs: [],
})
const {
  loading: getDatasetsWithPageLoading,
  paginator,
  datasets,
  loadDatasets,
} = useGetDatasetsWithPage()

const handleScroll = async (event: UIEvent) => {
  const { scrollTop, scrollHeight, clientHeight } = event.target as HTMLElement
  if (scrollTop + clientHeight >= scrollHeight - 10) {
    if (getDatasetsWithPageLoading.value) return
    await loadDatasets()
  }
}

const inputRefOptions = computed(() => {
  return getReferencedVariables(cloneDeep(nodes.value), cloneDeep(edges.value), props.node.id)
})

const removeDataset = (idx: number) => {
  form.value.datasets?.splice(idx, 1)
}

// 打开知识库模态框
const openDatasetsModal = () => {
  tempDatasets.value = cloneDeep(form.value.datasets ?? [])
  datasetsModalVisible.value = true
}

const addInput = () => {
  form.value.inputs?.push({
    name: '',
    type: 'ref',
    content: '',
    ref: '',
  })
}

const removeInput = (idx: number) => {
  form.value.inputs?.splice(idx, 1)
}

const handleSelectDataset = (idx: number) => {
  const dataset = datasets[idx]
  if (!dataset) return

// 检测id是否选中，如果是选中则删除
  if (tempDatasets.value.some((activateDataset) => activateDataset.id === dataset.id)) {
    tempDatasets.value = tempDatasets.value.filter(
      (activateDataset) => activateDataset.id !== dataset.id,
    )
  } else {
    if (form.value.datasets.length >= 5) {
      Message.warning('关联知识库已超过5个，无法继续关联')
      return
    }
    tempDatasets.value.push({
      id: dataset.id,
      name: dataset.name,
      icon: dataset.icon,
      description: dataset.description,
    })
  }
}

const confirmDatasets = () => {
  form.value.datasets = cloneDeep(tempDatasets.value)
  datasetsModalVisible.value = false
}

const activateTempDatasets = computed(() => tempDatasets.value)

const onSubmit = async ({ errors }: { errors: Record<string, ValidatedError> | undefined }) => {
// 检查表单是否出现错误，如果出现错误则直接结束
  if (errors) return

  const cloneInputs = cloneDeep(form.value.inputs) ?? []
  const cloneDatasets = cloneDeep(form.value.datasets) ?? []

// 数据校验通过，通过事件触发数据更新
  emits('updateNode', {
    id: props.node.id,
    title: form.value.title,
    description: form.value.description,
    dataset_ids: cloneDatasets.map((dataset) => dataset.id),
    meta: { datasets: cloneDatasets },
    retrieval_config: cloneDeep(form.value.retrieval_config),
    inputs: cloneInputs.map((input) => {
      return {
        name: input.name,
        description: '',
        required: true,
        type: input.type === 'ref' ? 'string' : input.type,
        value: {
          type: input.type === 'ref' ? 'ref' : 'literal',
          content:
            input.type === 'ref'
              ? {
                  ref_node_id: input.ref.split('/')[0] || '',
                  ref_var_name: input.ref.split('/')[1] || '',
                }
              : input.content,
        },
        meta: {},
      }
    }),
    outputs: cloneDeep(form.value.outputs),
  })
}

// 节点数据输入（来自草稿图，含扩展字段）
type NodeSourceInput = {
  name: string
  type: string
  value: { type: string; content: unknown }
}

// 监听数据，将数据映射到表单模型上
watch(
  () => props.node,
  (newNode) => {
    const cloneInputs = cloneDeep(newNode.data.inputs)
    form.value = {
      id: newNode.id,
      type: newNode.type,
      title: newNode.data.title,
      description: newNode.data.description,
      datasets: cloneDeep(newNode.data.meta?.datasets) ?? [],
      retrieval_config: cloneDeep(newNode.data.retrieval_config) ?? {
        k: 4,
        retrieval_strategy: 'semantic',
        score: 0,
      },
      inputs: cloneInputs.map((input: NodeSourceInput) => {
        const refContent = input.value.content as { ref_node_id: string; ref_var_name: string }
        const ref =
          input.value.type === 'ref'
            ? `${refContent.ref_node_id}/${refContent.ref_var_name}`
            : ''

// 判断引用的变量值信息是否存在，如果不存在则设置为空
        let refExists = false
        if (input.value.type === 'ref') {
          for (const inputRefOption of inputRefOptions.value) {
            for (const option of inputRefOption.options) {
              if (option.value === ref) {
                refExists = true
                break
              }
            }
          }
        }

        const rawContent = input.value.type === 'literal' ? input.value.content : ''
        const safeContent = typeof rawContent === 'object' && rawContent !== null ? '' : rawContent

        return {
          name: input.name,
          type: input.value.type === 'literal' ? input.type : 'ref',
          content: safeContent as string,
          ref: input.value.type === 'ref' && refExists ? ref : '',
        }
      }),
      outputs: [
        {
          name: 'combine_documents',
          type: 'string',
          value: { type: 'generated', content: '' },
        },
      ],
    }
  },
  { immediate: true },
)
</script>

<template>
  <div
    v-if="props.visible"
    id="start-node-info"
    class="absolute top-0 right-0 bottom-0 w-[400px] border-l z-50 bg-white overflow-scroll scrollbar-w-none p-3"
  >
    <!-- 顶部标题信息 -->
    <div class="flex items-center justify-between gap-3 mb-2">
      <!-- 左侧标题 -->
      <div class="flex items-center gap-1 flex-1">
        <a-avatar :size="30" shape="square" class="!bg-blue-700 rounded-lg flex-shrink-0">
          <icon-home />
        </a-avatar>
        <a-input
          v-model:model-value="form.title"
          placeholder="请输入标题"
          class="!bg-white text-gray-700 font-semibold px-2"
        />
      </div>
      <!-- 右侧关闭按钮 -->
      <a-button
        type="text"
        size="mini"
        class="!text-gray-700 flex-shrink-0"
        @click="() => emits('update:visible', false)"
      >
        <template #icon>
          <icon-close />
        </template>
      </a-button>
    </div>
    <!-- 描述信息 -->
    <a-textarea
      :auto-size="{ minRows: 3, maxRows: 5 }"
      v-model="form.description"
      class="rounded-lg text-gray-700 !text-xs"
      placeholder="输入描述..."
    />
    <!-- 分隔符 -->
    <a-divider class="my-2" />
    <!-- 输入数据表单 -->
    <a-form :model="form" size="mini" layout="vertical" @submit="onSubmit">
      <!-- 输入参数 -->
      <div class="flex flex-col gap-2">
        <!-- 标题&操作按钮 -->
        <div class="flex items-center justify-between">
          <!-- 左侧标题 -->
          <div class="flex items-center gap-2 text-gray-700 font-semibold">
            <div>输入参数</div>
            <a-tooltip content="输入给知识库检索节点的参数，支持引用上游节点的输出变量。">
              <icon-question-circle />
            </a-tooltip>
          </div>
          <!-- 添加参数按钮 -->
          <a-button aria-label="添加" size="mini" type="text" class="!text-gray-700" @click="addInput">
            <template #icon>
              <icon-plus />
            </template>
          </a-button>
        </div>
        <!-- 字段名 -->
        <div
          v-if="form?.inputs?.length > 0"
          class="flex items-center gap-1 text-xs text-gray-500 mb-1"
        >
          <div class="w-[20%]">参数名</div>
          <div class="w-[25%]">类型</div>
          <div class="w-[47%]">值</div>
          <div class="w-[8%]"></div>
        </div>
        <!-- 参数列表 -->
        <div v-for="(input, idx) in form?.inputs" :key="idx" class="flex items-center gap-1">
          <div class="w-[20%] flex-shrink-0">
            <a-input v-model="input.name" size="mini" placeholder="参数名" class="!px-2" />
          </div>
          <div class="w-[25%] flex-shrink-0">
            <a-select
              size="mini"
              v-model="input.type"
              class="px-2"
              :options="[
                { label: '引用', value: 'ref' },
                { label: 'STRING', value: 'string' },
                { label: 'INT', value: 'int' },
                { label: 'FLOAT', value: 'float' },
                { label: 'BOOLEAN', value: 'boolean' },
              ]"
            />
          </div>
          <div class="w-[47%] flex-shrink-0 flex items-center gap-1">
            <a-input
              v-if="input.type !== 'ref'"
              size="mini"
              v-model="input.content"
              placeholder="请输入参数值"
            />
            <a-select
              v-else
              placeholder="请选择引用变量"
              size="mini"
              tag-nowrap
              v-model="input.ref"
              :options="inputRefOptions"
            />
          </div>
          <!-- 删除按钮 -->
          <div class="w-[8%] flex-shrink-0 flex justify-center">
            <a-button aria-label="移除" size="mini" type="text" class="!text-red-500" @click="removeInput(Number(idx))">
              <template #icon>
                <icon-minus-circle />
              </template>
            </a-button>
          </div>
        </div>
        <!-- 空状态 -->
        <a-empty v-if="form?.inputs?.length <= 0" class="my-4">该节点暂无输入参数</a-empty>
      </div>
      <a-divider class="my-4" />
      <!-- 检索策略 -->
      <div class="flex flex-col gap-2">
        <!-- 标题&操作按钮 -->
        <div class="flex items-center justify-between">
          <!-- 左侧标题 -->
          <div class="flex items-center gap-2 text-gray-700 font-semibold">
            <div>检索设置</div>
            <a-tooltip content="配置知识库的检索规则，支持相似性检索、混合检索、全文检索。">
              <icon-question-circle />
            </a-tooltip>
          </div>
        </div>
        <a-radio-group
          v-model="form.retrieval_config.retrieval_strategy"
          default-value="semantic"
          :options="[
            { label: '混合策略', value: 'hybrid' },
            { label: '全文检索', value: 'full_text' },
            { label: '相似性检索', value: 'semantic' },
          ]"
        />
      </div>
      <a-divider class="my-4" />
      <!-- 最大召回数量 -->
      <div class="flex flex-col gap-2">
        <!-- 标题&操作按钮 -->
        <div class="flex items-center justify-between">
          <!-- 左侧标题 -->
          <div class="flex items-center gap-2 text-gray-700 font-semibold">
            <div>最大召回数量</div>
            <a-tooltip content="配置知识库的最大召回数量，范围为0-10.">
              <icon-question-circle />
            </a-tooltip>
          </div>
        </div>
        <div class="flex items-center gap-4 w-full pl-3">
          <a-slider v-model="form.retrieval_config.k" :step="1" :min="1" :max="10" />
          <a-input-number
            size="mini"
            v-model="form.retrieval_config.k"
            class="w-[80px]"
            :default-value="4"
          />
        </div>
      </div>
      <a-divider class="my-4" />
      <!-- 最小匹配度 -->
      <div class="flex flex-col gap-2">
        <!-- 标题&操作按钮 -->
        <div class="flex items-center justify-between">
          <!-- 左侧标题 -->
          <div class="flex items-center gap-2 text-gray-700 font-semibold">
            <div>最小匹配度</div>
            <a-tooltip content="配置知识库的最小匹配度，范围为0-1">
              <icon-question-circle />
            </a-tooltip>
          </div>
        </div>
        <div class="flex items-center gap-4 w-full pl-3">
          <a-slider v-model="form.retrieval_config.score" :step="0.01" :min="0" :max="1" />
          <a-input-number
            size="mini"
            v-model="form.retrieval_config.score"
            class="w-[80px]"
            :min="0"
            :max="0.99"
            :step="0.01"
            :precision="2"
            :default-value="0.5"
          />
        </div>
      </div>
      <a-divider class="my-4" />
      <!-- 关联知识库 -->
      <div class="flex flex-col gap-2">
        <!-- 标题&操作按钮 -->
        <div class="flex items-center justify-between">
          <!-- 左侧标题 -->
          <div class="flex items-center gap-2 text-gray-700 font-semibold">
            <div>关联知识库</div>
            <a-tooltip content="绑定知识库检索节点需要检索的知识库，最多可以关联5个知识库。">
              <icon-question-circle />
            </a-tooltip>
          </div>
          <!-- 右侧关联知识库按钮 -->
          <a-button aria-label="添加" size="mini" type="text" class="!text-gray-700" @click="openDatasetsModal">
            <template #icon>
              <icon-plus />
            </template>
          </a-button>
        </div>
        <div v-if="form.datasets?.length > 0" class="flex flex-col gap-1">
          <div
            v-for="(dataset, idx) in form.datasets"
            :key="dataset.id"
            class="flex items-center justify-between bg-white p-3 rounded-lg cursor-pointer hover:shadow-sm group"
          >
            <!-- 左侧知识库信息 -->
            <div class="flex items-center gap-2">
              <!-- 图标 -->
              <a-avatar
                :size="36"
                shape="square"
                class="rounded flex-shrink-0"
                :image-url="dataset.icon"
              />
              <!-- 名称与描述信息 -->
              <div class="flex flex-col flex-1 gap-1 h-9">
                <div class="text-gray-700 font-bold leading-[18px] line-clamp-1 break-all">
                  {{ dataset.name }}
                </div>
                <div class="text-gray-500 text-xs line-clamp-1 break-all">
                  {{ dataset.description }}
                </div>
              </div>
            </div>
            <!-- 右侧删除按钮 -->
            <a-button aria-label="删除"
              size="mini"
              type="text"
              class="hidden group-hover:block flex-shrink-0 ml-2 !text-red-700 rounded"
              @click="removeDataset(Number(idx))"
            >
              <template #icon>
                <icon-delete />
              </template>
            </a-button>
          </div>
        </div>
        <div v-else class="text-xs text-gray-500 leading-[22px]">
          引用文本类型数据，实现知识问答，工作流最多支持关联5个知识库。
        </div>
      </div>
      <a-divider class="my-4" />
      <!-- 输出参数 -->
      <div class="flex flex-col gap-2">
        <!-- 输出标题 -->
        <div class="font-semibold text-gray-700">输出数据</div>
        <!-- 字段标题 -->
        <div class="text-gray-500 text-xs">参数名</div>
        <!-- 输出参数列表 -->
        <div v-for="(output, idx) in form?.outputs" :key="idx" class="flex flex-col gap-2">
          <div class="flex items-center gap-2">
            <div class="text-gray-700">{{ output.name }}</div>
            <div class="text-gray-500 bg-gray-200 px-1 py-0.5 rounded">{{ output.type }}</div>
          </div>
        </div>
      </div>
      <a-divider class="my-4" />
      <!-- 保存按钮 -->
      <a-button
        :loading="props.loading"
        type="primary"
        size="small"
        html-type="submit"
        long
        class="rounded-lg"
      >
        保存
      </a-button>
    </a-form>
    <!-- 知识库模态窗 -->
    <a-modal
      :visible="datasetsModalVisible"
      hide-title
      :footer="false"
      :width="400"
      modal-class="h-[calc(100vh-32px)]"
      @cancel="() => (datasetsModalVisible = false)"
    >
      <!-- 顶部标题 -->
      <div class="flex items-center justify-between mb-6">
        <div class="text-lg font-bold text-gray-700">选择引用知识库</div>
        <a-button
          type="text"
          class="text-gray-700"
          size="small"
          @click="() => (datasetsModalVisible = false)"
        >
          <template #icon>
            <icon-close />
          </template>
        </a-button>
      </div>
      <!-- 中间知识库容器 -->
      <div class="h-[calc(100vh-180px)] mb-4 overflow-scroll scrollbar-w-none">
        <a-spin
          :loading="getDatasetsWithPageLoading"
          class="block h-full w-full scrollbar-w-none overflow-scroll"
          @scroll="handleScroll"
        >
          <!-- 知识库列表 -->
          <div class="flex flex-col gap-2">
            <!-- 有数据UI状态 -->
            <div
              v-for="(dataset, idx) in datasets"
              :key="dataset.id"
              :class="[
                `flex items-center gap-2 border px-3 py-2 rounded-lg cursor-pointer hover:bg-blue-50 hover:border-blue-700 ${activateTempDatasets.some((activateDataset) => activateDataset.id === dataset.id) ? 'bg-blue-50 border-blue-700' : ''}`,
              ]"
              @click="handleSelectDataset(idx)"
            >
              <a-avatar
                :size="24"
                shape="square"
                class="flex-shrink-0 rounded"
                :image-url="dataset.icon"
              />
              <div class="line-clamp-1 text-gray-500 flex-1">{{ dataset.name }}</div>
            </div>
            <!-- 无数据UI状态-->
            <a-empty
              v-if="datasets.length === 0"
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
        <div class="">{{ activateTempDatasets.length }} 个知识库被选中</div>
        <!-- 按钮组 -->
        <a-space :size="12">
          <a-button class="rounded-lg" @click="() => (datasetsModalVisible = false)">取消</a-button>
          <a-button type="primary" class="rounded-lg" @click="confirmDatasets">保存</a-button>
        </a-space>
      </div>
    </a-modal>
  </div>
</template>

<style>
#dataset_retrieval-node-info {
  .arco-textarea {
    @apply !text-xs;
  }
}
</style>
