<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { type Form, Message, type ValidatedError } from '@arco-design/web-vue'
import { getDocument, updateDocumentName } from '@/services/dataset.ts'

const props = defineProps({
  visible: { type: Boolean, required: true },
  dataset_id: { type: String, required: true },
  document_id: { type: String, required: true },

  onAfterUpdate: {
    type: Function,
    required: false,
    default: () => {},
  },
})

const emits = defineEmits(['update:visible'])
const loading = ref(false)
const form = reactive({ name: '' })
const formRef = ref<InstanceType<typeof Form>>()

const hideModal = () => {
  emits('update:visible', false)
  formRef.value?.resetFields()
}

const handleSubmit = async ({ errors }: { errors: Record<string, ValidatedError> | undefined }) => {
  if (errors) return

  try {
    loading.value = true
    const resp = await updateDocumentName(props.dataset_id, props.document_id, form.name)
    Message.success(resp.message)

    hideModal()
    props.onAfterUpdate()
  } finally {
    loading.value = false
  }
}

watch(
  () => props.visible,
  async (newValue: boolean) => {
    if (newValue) {
      const resp = await getDocument(props.dataset_id, props.document_id)
      const data = resp.data

      formRef.value?.resetFields()
      form.name = data.name
    }
  },
)
</script>

<template>
  <a-modal
    :width="520"
    :visible="visible"
    hide-title
    :footer="false"
    modal-class="rounded-xl"
    @cancel="hideModal"
  >
    <!-- 顶部标题-->
    <div class="flex items-center justify-between">
      <div class="text-lg font-bold text-gray-700">重命名</div>
      <a-button aria-label="关闭" @click="hideModal" type="text" class="!text-gray-700" size="small">
        <template #icon>
          <icon-close />
        </template>
      </a-button>
    </div>
    <!-- 中间表单-->
    <div class="pt-6">
      <a-form ref="formRef" :model="form" @submit="handleSubmit" layout="vertical">
        <a-form-item
          field="name"
          label="名称"
          asterisk-position="end"
          :rules="[{ required: true, message: '文档名称不能为空' }]"
        >
          <a-input
            id="form-name"
            name="form-name"
            v-model="form.name"
            placeholder="请输入文档名称"
            show-word-limit
            :max-length="100"
          />
        </a-form-item>
        <!-- 底部按钮-->
        <div class="flex items-center justify-end">
          <a-space :size="16">
            <a-button class="rounded-lg" @click="hideModal">取消</a-button>
            <a-button :loading="loading" type="primary" html-type="submit" class="rounded-lg"
              >保存</a-button
            >
          </a-space>
        </div>
      </a-form>
    </div>
  </a-modal>
</template>

<style scoped></style>
