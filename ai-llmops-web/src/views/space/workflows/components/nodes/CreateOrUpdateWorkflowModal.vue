<script setup lang="ts">
import { useCreateWorkflow, useGetWorkflow, useUpdateWorkflow } from '@/hooks/use-workflow.ts'
import { type FileItem, type Form, type ValidatedError } from '@arco-design/web-vue'
import { ref, watch } from 'vue'
import { uploadImage } from '@/services/upload-file.ts'

const props = defineProps({
  workflow_id: { type: String, default: '', required: false },
  visible: { type: Boolean, required: true },
  callback: { type: Function, required: false },
})

const emits = defineEmits(['update:visible', 'update:workflow_id'])
const { loading: createWorkflowLoading, handleCreateWorkflow } = useCreateWorkflow()
const { loading: updateWorkflowLoading, handleUpdateWorkflow } = useUpdateWorkflow()
const { workflow, loadWorkflow } = useGetWorkflow()
const defaultForm = {
  fileList: [] as FileItem[],
  icon: '',
  name: '',
  tool_call_name: '',
  description: '',
}

const form = ref({ ...defaultForm })
const formRef = ref<InstanceType<typeof Form>>()

const hideModal = () => emits('update:visible', false)

const saveWorkflow = async ({ errors }: { errors: Record<string, ValidatedError> | undefined }) => {
  if (errors) return

// 检测是保存还是新增，调用不同的API接口
  if (props.workflow_id) {
    await handleUpdateWorkflow(props.workflow_id, form.value)
  } else {
    await handleCreateWorkflow(form.value)
  }

  emits('update:visible', false)
  if (props.callback) {
    props.callback()
  }
}

watch(
  () => props.visible,
  async (newValue) => {
    formRef.value?.resetFields()
    if (newValue) {
// 开启弹窗，需要检测下是更新还是创建操作
      if (props.workflow_id) {
        await loadWorkflow(props.workflow_id)
        form.value = {
          fileList: [{ uid: '1', name: '应用图标', url: String(workflow.value?.icon) }],
          icon: String(workflow.value?.icon),
          name: String(workflow.value?.name),
          tool_call_name: String(workflow.value?.tool_call_name),
          description: String(workflow.value?.description),
        }
      }
    } else {
      form.value = defaultForm
      formRef.value?.resetFields()
      emits('update:workflow_id', '')
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
        {{ props.workflow_id === '' ? '创建工作流' : '编辑工作流' }}
      </div>
      <a-button aria-label="关闭" type="text" class="!text-gray-700" size="small" @click="hideModal">
        <template #icon>
          <icon-close />
        </template>
      </a-button>
    </div>
    <div class="pt-6">
      <a-form ref="formRef" :model="form" layout="vertical" @submit="saveWorkflow">
        <a-form-item
          field="fileList"
          hide-label
          :rules="[{ required: true, message: '工作流图标不能为空' }]"
        >
          <a-upload
            :limit="1"
            list-type="picture-card"
            accept="image/png, image/jpeg"
            class="w-auto! mx-auto"
            v-model:file-list="form.fileList"
            image-preview
            :custom-request="
              (option: {
                fileItem: FileItem
                onSuccess: (response?: unknown) => void
                onError: (response?: unknown) => void
              }) => {
                const { fileItem, onSuccess, onError } = option

                const uploadTask = async () => {
                  try {
                    const resp = await uploadImage(fileItem.file as File)
                    form.icon = resp.data.image_url
                    onSuccess(resp)
                  } catch (error) {
                    onError(error)
                  }
                }
                uploadTask()
                return { abort: () => {} }
              }
            "
          />
        </a-form-item>
        <a-form-item
          field="name"
          label="工作流名称"
          asterisk-position="end"
          :rules="[{ required: true, message: '工作流名称不能为空' }]"
        >
          <a-input
            show-word-limit
            :max-length="50"
            v-model:model-value="form.name"
            placeholder="请输入工作流名称"
          />
        </a-form-item>
        <a-form-item
          field="tool_call_name"
          label="英文名称"
          asterisk-position="end"
          :rules="[{ required: true, message: '英文名称不能为空' }]"
        >
          <a-input
            show-word-limit
            :max-length="50"
            v-model:model-value="form.tool_call_name"
            placeholder="英文名称将用于被大模型识别及调用"
          />
        </a-form-item>
        <a-form-item
          field="description"
          label="工作流描述"
          asterisk-position="end"
          :rules="[{ required: true, message: '工作流描述不能为空' }]"
        >
          <a-textarea
            v-model:model-value="form.description"
            :auto-size="{ minRows: 8, maxRows: 8 }"
            :max-length="255"
            show-word-limit
            placeholder="请输入关于该工作流的描述信息，以便LLM能准确识别工作流的用途。"
          />
        </a-form-item>
        <!--- 底部按钮 --->
        <div class="flex items-center justify-between">
          <div class=""></div>
          <a-space :size="16">
            <a-button class="rounded-lg" @click="hideModal">取消</a-button>
            <a-button
              :loading="createWorkflowLoading || updateWorkflowLoading"
              type="primary"
              html-type="submit"
              class="rounded-lg"
            >
              保存
            </a-button>
          </a-space>
        </div>
      </a-form>
    </div>
  </a-modal>
</template>

<style scoped></style>
