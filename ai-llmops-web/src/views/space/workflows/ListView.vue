<script setup lang="ts">
import { useRoute } from 'vue-router'
import { onMounted, ref, watch } from 'vue'
import { useDeleteWorkflow, useGetWorkflowsWithPage } from '@/hooks/use-workflow.ts'
import CreateOrUpdateWorkflowModal from '@/views/space/workflows/components/CreateOrUpdateWorkflowModal.vue'
import moment from 'moment/moment'

const route = useRoute()
const props = defineProps({
  createType: { type: String, default: '', required: true },
})
const emits = defineEmits(['update-create-type'])
const createOrUpdateWorkflowModalVisible = ref(false)
const updateWorkflowId = ref('')
const {
  loading: getWorkflowsWithPageLoading,
  workflows,
  paginator,
  loadWorkflows,
} = useGetWorkflowsWithPage()
const { handleDeleteWorkflow } = useDeleteWorkflow()

const handleScroll = async (event: UIEvent) => {
// 获取滚动距离、可滚动的最大距离、客户端/浏览器窗口的高度
  const { scrollTop, scrollHeight, clientHeight } = event.target as HTMLElement

  if (scrollTop + clientHeight >= scrollHeight - 10) {
    if (getWorkflowsWithPageLoading.value) return
    await loadWorkflows(String(route.query?.search_word ?? ''), '')
  }
}

// 页面DOM加载完毕后执行
onMounted(async () => {
  // 初始化工作流数据
  await loadWorkflows(String(route.query?.search_word ?? ''), '', true)
})

watch(
  () => props.createType,
  (newValue) => {
    if (newValue === 'workflow') {
      updateWorkflowId.value = ''
      createOrUpdateWorkflowModalVisible.value = true
      emits('update-create-type', '')
    }
  },
)

watch(
  () => route.query?.search_word,
  async () => await loadWorkflows(String(route.query?.search_word ?? ''), '', true),
)

const onDeleteWorkflow = (workflowId: string) => {
  handleDeleteWorkflow(workflowId, async () => {
    await loadWorkflows(String(route.query?.search_word ?? ''), '', true)
  })
}

const handleEditWorkflow = (workflow_id: string) => {
  updateWorkflowId.value = workflow_id
  createOrUpdateWorkflowModalVisible.value = true
}
</script>

<template>
  <a-spin
    :loading="getWorkflowsWithPageLoading"
    class="block h-full w-full scrollbar-w-none overflow-scroll"
    @scroll="handleScroll"
  >
    <!-- 底部工作流列表 -->
    <a-row :gutter="[20, 20]" class="flex-1">
      <!-- 有数据的UI状态（响应式：视口缩小自动换行 4/3/2/1 列） -->
      <a-col
        v-for="workflow in workflows"
        :key="workflow.id"
        :xs="24"
        :sm="12"
        :md="8"
        :lg="6"
        :xl="6"
        :xxl="6"
      >
        <a-card hoverable class="cursor-pointer rounded-lg">
          <!-- 顶部工作流名称 -->
          <div class="flex items-center gap-3 mb-3">
            <!-- 左侧图标 -->
            <a-avatar :size="40" shape="square" :image-url="workflow.icon" />
            <!-- 右侧信息 -->
            <div class="flex flex-1 justify-between">
              <div class="flex flex-col">
                <router-link
                  :to="{
                    name: 'space-workflows-detail',
                    params: { workflow_id: workflow.id },
                  }"
                  class="text-base text-gray-900 font-bold line-clamp-1"
                >
                  {{ workflow.name }}
                  <icon-check-circle-fill
                    v-if="workflow.status === 'published'"
                    class="!text-green-700"
                  />
                </router-link>
                <div class="text-xs text-gray-500 line-clamp-1">
                  {{ workflow.tool_call_name }} · {{ workflow.node_count }} 节点数
                </div>
              </div>
              <!-- 操作按钮 -->
              <a-dropdown position="br">
                <a-button aria-label="更多操作" type="text" size="small" class="rounded-lg !text-gray-700">
                  <template #icon>
                    <icon-more />
                  </template>
                </a-button>
                <template #content>
                  <a-doption @click="handleEditWorkflow(workflow.id)"> 编辑工作流 </a-doption>
                  <a-doption class="text-red-700" @click="onDeleteWorkflow(workflow.id)">
                    删除
                  </a-doption>
                </template>
              </a-dropdown>
            </div>
          </div>
          <!-- 工作流的描述信息 -->
          <div class="leading-[18px] text-gray-500 h-[72px] line-clamp-4 mb-2">
            {{ workflow.description }}
          </div>
          <!-- 工作流的发布信息 -->
          <div class="flex items-center gap-1.5">
            <a-avatar :size="18" class="bg-blue-700">
              <icon-user />
            </a-avatar>
            <div class="text-xs text-gray-400">
              DeepSeek · 最近编辑
              {{
                moment(
                  (workflow as unknown as { created_at?: number }).created_at ?? workflow.updated_at,
                ).format('MM-DD HH:mm:ss')
              }}
            </div>
          </div>
        </a-card>
      </a-col>
      <a-row v-if="paginator.total_page >= 2">
        <!-- 加载数据中 -->
        <a-col v-if="paginator.current_page <= paginator.total_page" :span="24" align="center">
          <a-space class="my-4">
            <a-spin />
            <div class="text-gray-400">加载中</div>
          </a-space>
        </a-col>
        <!-- 数据加载完成 -->
        <a-col v-else :span="24" align="center">
          <div class="text-gray-400 my-4">数据已加载完成</div>
        </a-col>
      </a-row>
      <!-- 没数据的UI状态 -->
      <a-col v-if="workflows.length === 0" :span="24">
        <a-empty
          description="没有可用的工作流"
          class="h-[400px] flex flex-col items-center justify-center"
        />
      </a-col>
    </a-row>
    <!-- 新建/修改模态窗 -->
    <create-or-update-workflow-modal
      v-model:visible="createOrUpdateWorkflowModalVisible"
      v-model:workflow_id="updateWorkflowId"
      :callback="async () => await loadWorkflows(String(route.query?.search_word ?? ''), '', true)"
    />
  </a-spin>
</template>

<style scoped></style>
