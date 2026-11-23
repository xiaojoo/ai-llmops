<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { type Form, Message, type ValidatedError } from '@arco-design/web-vue'
import { createSegment, getSegment, updateSegment } from '@/services/dataset.ts'

const props = defineProps({
  dataset_id: { type: String, required: false },
  document_id: { type: String, required: false },
  segment_id: { type: String, required: false },
  visible: { type: Boolean, required: true },
  callback: { type: Function, required: false },
})
const emits = defineEmits(['update:visible'])
const loading = ref(false)
const defaultForm: { content: string; keywords: string[] } = {
  content: '',
  keywords: [],
}
const form = reactive({ ...defaultForm })
const formRef = ref<InstanceType<typeof Form>>()
const isUpdateOperation = computed(() => props.segment_id && props.segment_id !== '')

const hideModal = () => emits('update:visible', false)

const saveSegment = async ({ errors }: { errors: Record<string, ValidatedError> | undefined }) => {
  if (errors) return
  try {
    loading.value = true
    let resp
    if (isUpdateOperation.value) {
      resp = await updateSegment(
        props.dataset_id as string,
        props.document_id as string,
        props.segment_id as string,
        form,
      )
    } else {
      resp = await createSegment(props.dataset_id as string, props.document_id as string, form)
    }
    emits('update:visible', false)
    Message.success(resp.message)
    if (props.callback) {
      props.callback()
    }
  } finally {
    loading.value = false
  }
}

watch(
  () => props.visible,
  async (newValue) => {
    formRef.value?.resetFields()

    if (newValue) {
      if (isUpdateOperation.value) {
        const resp = await getSegment(
          props.dataset_id as string,
          props.document_id as string,
          props.segment_id as string,
        )
        const data = resp.data

        form.content = data.content
        form.keywords = data.keywords
      }
    } else {
      formRef.value?.resetFields()
      Object.assign(form, { ...defaultForm })
    }
  },
)
</script>

<template>
  <a-modal
    width="max(400px, min(520px, calc(100vw - 32px)))"
    :visible="props.visible"
    hide-title
    :footer="false"
    modal-class="rounded-xl"
    @cancel="hideModal"
  >
    <div class="flex items-center justify-between">
      <div class="text-lg font-bold text-gray-700">
        {{ isUpdateOperation ? '更新' : '添加' }}片段
      </div>
      <a-button aria-label="关闭" type="text" class="=!text-gray-700" size="small" @click="hideModal">
        <template #icon>
          <icon-close />
        </template>
      </a-button>
    </div>
    <div class="pt-6">
      <a-form ref="formRef" :model="form" layout="vertical" @submit="saveSegment">
        <a-form-item
          field="content"
          label="片段内容"
          asterisk-position="end"
          :rules="[{ required: true, message: '片段内容不能为空' }]"
        >
          <a-textarea
            v-model:model-value="form.content"
            :auto-size="{ minRows: 8, maxRows: 8 }"
            placeholder="在这里添加文档片段内容"
          />
        </a-form-item>
        <a-form-item field="keywords" label="关键词">
          <a-input-tag
            v-model:model-value="form.keywords"
            :max-tag-count="10"
            placeholder="请输入文档片段关键词，最多不超过10个，安Enter输入"
          />
        </a-form-item>
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
