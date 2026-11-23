<script setup lang="ts">
import { useUpdateConversationName } from '@/hooks/use-conversation.ts'
import { ref, watch } from 'vue'
import type { Form, ValidatedError } from '@arco-design/web-vue'

const props = defineProps<{
  visible: boolean
  conversation_id: string
  success_callback?: (conversation_id: string, conversation_name: string) => void
}>()

const emits = defineEmits(['update:visible'])

const { loading, handleUpdateConversationName } = useUpdateConversationName()

const form = ref({ name: '' })
const formRef = ref<InstanceType<typeof Form>>()

// 关闭弹窗
const hideModal = () => emits('update:visible', false)

// 提交表单
const saveName = async ({ errors }: { errors?: Record<string, ValidatedError> }) => {
  if (errors) return

  await handleUpdateConversationName(props.conversation_id, form.value.name)

  hideModal()
  props.success_callback?.(props.conversation_id, form.value.name)
}

// 监听弹窗显示状态
watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      // 打开弹窗
      formRef.value?.clearValidate()
    } else {
      // 关闭弹窗
      form.value = { name: '' }
    }
  },
)
</script>

<template>
  <a-modal
    :width="520"
    :visible="props.visible"
    hide-title
    :footer="false"
    modal-class="rounded-xl"
    @cancel="hideModal"
  >
    <!-- 顶部标题 -->
    <div class="flex items-center justify-between">
      <div class="text-lg font-bold text-gray-700">
        {{ props.conversation_id !== '' ? '重命名' : '' }}
      </div>
      <a-button aria-label="关闭" type="text" class="!text-gray-700" size="small" @click="hideModal">
        <template #icon>
          <icon-close />
        </template>
      </a-button>
    </div>
    <!-- 中间表单 -->
    <div class="pt-6">
      <a-form ref="formRef" :model="form" layout="vertical" @submit="saveName">
        <a-form-item
          field="name"
          label="应用名称"
          asterisk-position="end"
          :rules="[{ required: true, message: '应用名称不能为空' }]"
        >
          <a-input v-model="form.name" placeholder="请输入应用名称" />
        </a-form-item>

        <!-- 底部按钮 -->
        <div class="flex items-center justify-between">
          <div class=""></div>
          <a-space :size="16">
            <a-button class="rounded-lg" @click="hideModal">取消</a-button>
            <a-button :loading="loading" type="primary" html-type="submit" class="rounded-lg">
              保存
            </a-button>
          </a-space>
        </div>
      </a-form>
    </div>
  </a-modal>
</template>

<style scoped></style>
