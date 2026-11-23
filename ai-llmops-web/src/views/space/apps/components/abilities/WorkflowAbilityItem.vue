<script setup lang="ts">
import { nextTick, type PropType, ref, watch } from 'vue'
import { useUpdateDraftAppConfig } from '@/hooks/use-app.ts'
import { Message } from '@arco-design/web-vue'
import { showErrorToast } from '@/utils/http/error'
import cloneDeep from 'lodash/cloneDeep'
import { useGetWorkflowsWithPage } from '@/hooks/use-workflow.ts'

const props = defineProps({
  app_id: { type: String, required: true },
  workflows: {
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
const emits = defineEmits(['update:workflows'])
const { loading: updateDraftAppConfigLoading, handleUpdateDraftAppConfig } =
  useUpdateDraftAppConfig()
const { loading, paginator, workflows: apiWorkflows, loadWorkflows } = useGetWorkflowsWithPage()
const workflowsModalVisible = ref(false)
const isWorkflowsInit = ref(false)

type ActivatedWorkflow = {
  id: string
  name: string
  icon: string
  description: string
}

const activateWorkflows = ref<ActivatedWorkflow[]>([])
const originWorkflows = ref<ActivatedWorkflow[]>([])

const handleScroll = async (event: UIEvent) => {
// 获取滚动距离、可滚动最大距离、客户端/浏览器窗口高度
  const { scrollTop, scrollHeight, clientHeight } = event.target as HTMLElement
  if (scrollTop + clientHeight >= scrollHeight - 10) {
    if (loading.value) {
      return
    }
    await loadWorkflows('', 'published')
  }
}

const handleCancelWorkflowsModal = () => {
  workflowsModalVisible.value = false
  activateWorkflows.value = cloneDeep(originWorkflows.value)
  isWorkflowsInit.value = false
}

const handleSelectWorkflow = (idx: number) => {
  const workflow = apiWorkflows.value[idx]
  if (!workflow) return

  if (activateWorkflows.value.some((activateWorkflow) => activateWorkflow.id === workflow.id)) {
    activateWorkflows.value = activateWorkflows.value.filter(
      (activateWorkflow) => activateWorkflow.id !== workflow.id,
    )
  } else {
    if (activateWorkflows.value.length >= 5) {
      Message.warning('关联工作流已超过5个，无法继续关联')
      return
    }
    activateWorkflows.value.push({
      id: workflow.id,
      name: workflow.name,
      icon: workflow.icon,
      description: workflow.description,
    })
  }
}

const handleSubmitWorkflows = async () => {
  try {
    await handleUpdateDraftAppConfig(props.app_id, {
      workflows: activateWorkflows.value.map((activateWorkflow) => activateWorkflow.id),
    })
    originWorkflows.value = cloneDeep(activateWorkflows.value)
    await nextTick()
    emits('update:workflows', cloneDeep(activateWorkflows.value))
    handleCancelWorkflowsModal()
  } catch (e) {
    showErrorToast(String(e))
  }
}

watch(
  () => props.workflows,
  (newValue) => {
    const initData = (newValue || []).map((workflow) => ({
      id: workflow.id,
      name: workflow.name,
      icon: workflow.icon,
      description: workflow.description,
    }))

    activateWorkflows.value = cloneDeep(initData)
    originWorkflows.value = cloneDeep(initData)
  },
  { immediate: true, deep: true },
)

watch(
  () => workflowsModalVisible.value,
  async (newValue) => {
    if (newValue) {
      await loadWorkflows('', 'published', true)
    } else {
      apiWorkflows.value.splice(0, apiWorkflows.value.length)
    }
  },
)

const handleRemoveWorkflow = async (idx: number) => {
  const newWorkflows = [...props.workflows]
  newWorkflows.splice(idx, 1)
  await handleUpdateDraftAppConfig(props.app_id, {
    workflows: newWorkflows.map((item) => item.id),
  })
  activateWorkflows.value = cloneDeep(newWorkflows)
  originWorkflows.value = cloneDeep(newWorkflows)
  emits('update:workflows', newWorkflows)
}
// 供外部（左侧「工作流」导航）直接打开选择工作流弹窗
defineExpose({ openAdd: () => { workflowsModalVisible.value = true } })
</script>

<template>
  <div class="">
    <a-collapse-item key="workflows" class="app-ability-item">
      <template #header>
        <div class="text-gray-700 font-bold">工作流</div>
      </template>
      <template #extra>
        <a-space>
          <a-button aria-label="添加"
            size="mini"
            type="text"
            class="!text-gray-700"
            @click.stop="workflowsModalVisible = true"
          >
            <template #icon>
              <icon-plus />
            </template>
          </a-button>
        </a-space>
      </template>      <div v-if="props.workflows?.length > 0" class="flex flex-col gap-1">
        <div
          v-for="(workflow, idx) in props.workflows"
          :key="workflow.id"
          class="flex items-center justify-between bg-white p-3 rounded-lg cursor-pointer hover:shadow-sm group"
        >
          <!-- 左侧工作流信息 -->
          <div class="flex items-center gap-2">
            <a-avatar
              :size="36"
              shape="square"
              class="rounded flex-shrink-0"
              :image-url="workflow.icon"
            />
            <!-- 名称与描述信息 -->
            <div class="flex flex-col flex-1 gap-1 h-9">
              <div class="text-gray-700 font-bold leading-[18px] line-clamp-1">
                {{ workflow.name }}
              </div>
              <div class="text-gray-500 text-xs line-clamp-1">{{ workflow.description }}</div>
            </div>
          </div>
          <!-- 右侧删除按钮 -->
          <a-button aria-label="删除"
            size="mini"
            type="text"
            class="hidden group-hover:block flex-shrink-0 ml-2 !text-red-700 rounded"
            @click="handleRemoveWorkflow(idx)"
          >
            <template #icon>
              <icon-delete />
            </template>
          </a-button>
        </div>
      </div>
      <div v-else class="text-xs text-gray-500 leading-[28px]">
        工作流支持通过可视化的方式，对插件、大语言模型、代码块等功能进行组合，从而实现复杂、稳定的业务流程编排，例如旅行规划、报告分析等，应用最多支持关联5个工作流。
      </div>
    </a-collapse-item>
    <!-- 工作流模态窗 -->
    <a-modal
      :visible="workflowsModalVisible"
      hide-title
      :footer="false"
      width="max(340px, min(400px, calc(100vw - 32px)))"
      class="datasets-modal"
      modal-class="h-[calc(100vh-32px)] right-4"
      @cancel="handleCancelWorkflowsModal"
    >
      <!-- 顶部标题 -->
      <div class="flex items-center justify-between mb-6">
        <div class="text-lg font-bold text-gray-700">选择引用工作流</div>
        <a-button aria-label="关闭"
          type="text"
          class="text-gray-700"
          size="small"
          @click="handleCancelWorkflowsModal"
        >
          <template #icon>
            <icon-close />
          </template>
        </a-button>
      </div>
      <!-- 中间工作流容器 -->
      <div class="h-[calc(100vh-180px)] mb-4 overflow-scroll scrollbar-w-none">
        <a-spin
          :loading="loading"
          class="block h-full w-full scrollbar-w-none overflow-scroll"
          @scroll="handleScroll"
        >
          <!-- 工作流列表 -->
          <div class="flex flex-col gap-2">
            <!-- 有数据UI状态 -->
            <div
              v-for="(workflow, idx) in apiWorkflows"
              :key="workflow.id"
              :class="[
                `flex items-center gap-2 border px-3 py-2 rounded-lg cursor-pointer hover:bg-blue-50 hover:border-blue-700 ${activateWorkflows.some((activateWorkflow) => activateWorkflow.id === workflow.id) ? 'bg-blue-50 border-blue-700' : ''}`,
              ]"
              @click="handleSelectWorkflow(idx)"
            >
              <a-avatar
                :size="24"
                shape="square"
                class="flex-shrink-0 rounded"
                :image-url="workflow.icon"
              />
              <div class="flex flex-col flex-1 min-w-0">
                <div class="line-clamp-1 text-gray-700 text-sm font-medium">
                  {{ workflow.name }}
                </div>
                <div class="line-clamp-1 text-gray-400 text-xs">{{ workflow.description }}</div>
              </div>
              <icon-check
                v-if="activateWorkflows.some((s) => s.id === workflow.id)"
                class="text-blue-700 flex-shrink-0"
              />
            </div>
            <!-- 无数据UI状态-->
            <a-empty
              v-if="apiWorkflows.length === 0"
              description="没有可用的工作流"
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
        <div class="">{{ activateWorkflows.length }} 个工作流被选中</div>
        <!-- 按钮组 -->
        <a-space :size="12">
          <a-button class="rounded-lg" @click="handleCancelWorkflowsModal">取消</a-button>
          <a-button
            :loading="updateDraftAppConfigLoading"
            type="primary"
            class="rounded-lg"
            @click="handleSubmitWorkflows"
          >
            保存
          </a-button>
        </a-space>
      </div>
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
