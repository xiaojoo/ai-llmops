<script setup lang="ts">
import {
  useGetDebugConversationSummary,
  useUpdateDebugConversationSummary,
} from '@/hooks/use-app.ts'
import { ref } from 'vue'

const props = defineProps({
  app_id: { type: String, required: true },
  long_term_memory: { type: Object, required: true, default: () => ({}) },
  // 编排型 Agent：子任务数量与页内 tab 视图模式（由父组件 DetailView 持有）
  subTaskCount: { type: Number, default: 0 },
  viewMode: { type: String, default: 'chat' },
})

const emits = defineEmits(['update:viewMode'])

const { debug_conversation_summary, loadDebugConversationSummary } =
  useGetDebugConversationSummary()
const { loading: updateLoading, handleUpdateDebugConversationSummary } =
  useUpdateDebugConversationSummary()
const summaryModalVisible = ref(false)

const openSummaryModal = () => {
  // 先立即弹出，再异步加载内容，避免点击后等待接口导致弹窗“卡顿”
  summaryModalVisible.value = true
  void loadDebugConversationSummary(props.app_id)
}

const onConfirmSummary = async () => {
  await handleUpdateDebugConversationSummary(props.app_id, debug_conversation_summary.value)

  summaryModalVisible.value = false
}
</script>

<template>
  <div class="">
    <!-- 预览与调试组件（对齐 demo .preview-head：标题 + 下划线 tab + 右侧操作） -->
    <div class="ab-preview-head">
      <div class="flex items-center gap-4 min-w-0">
        <div class="ab-preview-title shrink-0">预览调试</div>
        <!-- 页内 tab（与 web-apps 对话/任务详情同款：紧凑分段控件，字体 text-xs、高 28px） -->
        <div class="flex items-center gap-1 rounded-lg bg-gray-100 p-0.5 shrink-0">
          <button
            type="button"
            class="h-7 px-3 rounded-md text-xs transition-colors"
            :class="
              props.viewMode === 'chat'
                ? 'bg-white text-blue-600 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            "
            @click="emits('update:viewMode', 'chat')"
          >
            对话
          </button>
          <button
            type="button"
            class="h-7 px-3 rounded-md text-xs transition-colors"
            :class="
              props.viewMode === 'subagents'
                ? 'bg-white text-blue-600 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            "
            @click="emits('update:viewMode', 'subagents')"
          >
            任务详情
          </button>
        </div>
      </div>
      <a-button
        :disabled="!props.long_term_memory?.enable"
        size="mini"
        type="text"
        class="rounded-lg !text-blue-700 shrink-0"
        @click="openSummaryModal"
      >
        <template #icon>
          <icon-save />
        </template>
        长期记忆
      </a-button>
    </div>
    <!-- 长期记忆模态窗 -->
    <a-modal
      width="max(400px, min(520px, calc(100vw - 32px)))"
      v-model:visible="summaryModalVisible"
      hide-title
      :footer="false"
      modal-class="rounded-xl"
    >
      <!-- 顶部标题-->
      <div class="flex items-center justify-between">
        <div class="text-lg font-bold text-gray-700">长期记忆</div>
        <a-button aria-label="关闭"
          @click="summaryModalVisible = false"
          type="text"
          class="!text-gray-700"
          size="small"
        >
          <template #icon>
            <icon-close />
          </template>
        </a-button>
      </div>
      <!-- 底部表单 -->
      <div class="pt-6">
        <a-textarea
          v-model:model-value="debug_conversation_summary"
          placeholder="请输入当前调试会话长期记忆"
          show-word-limit
          :max-length="2000"
          :auto-size="{ minRows: 8, maxRows: 8 }"
        />
      </div>
      <!-- 底部按钮-->
      <div class="flex items-center justify-end">
        <a-space :size="16">
          <a-button class="rounded-lg" @click="summaryModalVisible = false">取消</a-button>
          <a-button
            :loading="updateLoading"
            type="primary"
            html-type="submit"
            class="rounded-lg"
            @click="onConfirmSummary"
          >
            保存
          </a-button>
        </a-space>
      </div>
    </a-modal>
  </div>
</template>

<style scoped></style>
