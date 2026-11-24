<script setup lang="ts">
import { useCreateApp, useGetApp, useUpdateApp } from '@/hooks/use-app.ts'
import { ref, watch } from 'vue'
import { type FileItem, type Form, type RequestOption, type ValidatedError } from '@arco-design/web-vue'
import { uploadImage } from '@/services/upload-file.ts'

const props = defineProps({
  app_id: { type: String, default: '', required: false },
  visible: { type: Boolean, required: true },
  callback: { type: Function, required: false },
})

const emits = defineEmits(['update:visible', 'update:app_id'])
const { loading: createAppLoading, handleCreateApp } = useCreateApp()
const { loading: updateAppLoading, handleUpdateApp } = useUpdateApp()
const { app, loadApp } = useGetApp()
const defaultForm = {
  fileList: [] as FileItem[],
  icon: '',
  name: '',
  description: '',
  app_type: 'agent' as 'agent' | 'orchestrator',
  orchestrator_config: {
    enable: false,
    max_sub_tasks: 5,
    max_parallel: 3,
    sub_task_timeout: 300,
    resume_mode: 'auto' as 'auto' | 'manual',
  },
}

const form = ref({ ...defaultForm })
const formRef = ref<InstanceType<typeof Form>>()

const hideModal = () => emits('update:visible', false)

const saveApp = async ({ errors }: { errors: Record<string, ValidatedError> | undefined }) => {
  if (errors) return

// 检测保存还是新增，调用不同的API接口
  if (props.app_id) {
    // 编辑模式：后端 UpdateAppReq 仅支持基础信息
    const { name, icon, description } = form.value
    await handleUpdateApp(props.app_id, { name, icon, description })
  } else {
    await handleCreateApp(form.value)
  }
// 完成保存操作，隐藏模态窗并调用回调函数
  hideModal()
  props.callback?.()
}

watch(
  () => props.visible,
  async (newValue) => {
    formRef.value?.resetFields()

    if (newValue) {
// 开启弹窗，需要检测下是更新还是创建操作
      if (props.app_id) {
        await loadApp(props.app_id)

        const appData = app.value
        if (appData) {
          form.value = {
            ...defaultForm,
            fileList: [{ uid: '1', name: '应用图标', url: appData.icon ?? '' }],
            icon: appData.icon ?? '',
            name: appData.name ?? '',
            description: appData.description ?? '',
          }
        }
      }
    } else {
      form.value = { ...defaultForm }
      formRef.value?.resetFields()
      emits('update:app_id', '')
    }
  },
)
</script>

<template>
  <a-modal
    :width="'clamp(200px, 80vw, 520px)'"
    :visible="props.visible"
    hide-title
    :footer="false"
    modal-class="rounded-xl"
    @cancel="hideModal"
  >
    <!-- 顶部标题 -->
    <div class="flex items-center justify-between">
      <div class="text-lg font-bold text-gray-700">
        {{ props.app_id === '' ? '创建AI应用' : '编辑AI应用' }}
      </div>
      <a-button aria-label="关闭" type="text" class="!text-gray-700" size="small" @click="hideModal">
        <template #icon>
          <icon-close />
        </template>
      </a-button>
    </div>
    <!-- 中间表单 -->
    <div class="pt-6">
      <a-form ref="formRef" :model="form" layout="vertical" @submit="saveApp">
        <a-form-item
          field="fileList"
          hide-label
          :rules="[{ required: true, message: '应用图标不能为空' }]"
        >
          <a-upload
            :limit="1"
            list-type="picture-card"
            accept="image/png, image/jpeg"
            class="w-auto! mx-auto"
            v-model:file-list="form.fileList"
            image-preview
            :custom-request="
              (option: RequestOption) => {
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
            :on-before-remove="
              async () => {
                form.icon = ''
                return true
              }
            "
          />
        </a-form-item>
        <a-form-item
          field="name"
          label="应用名称"
          asterisk-position="end"
          :rules="[{ required: true, message: '应用名称不能为空' }]"
        >
          <a-input v-model="form.name" placeholder="请输入应用名称" />
        </a-form-item>
        <a-form-item field="description" label="应用描述">
          <a-textarea
            v-model="form.description"
            :auto-size="{ minRows: 8, maxRows: 8 }"
            :max-length="800"
            show-word-limit
            placeholder="请输入关于该应用的描述信息"
          />
        </a-form-item>
        <a-form-item
          v-if="!props.app_id"
          field="app_type"
          label="应用类型"
          asterisk-position="end"
        >
          <a-select v-model="form.app_type" placeholder="请选择应用类型">
            <a-option value="agent">Agent（智能体）</a-option>
            <a-option value="orchestrator">Orchestrator（任务编排）</a-option>
          </a-select>
        </a-form-item>
        <!-- 编排型应用配置表单 -->
        <div
          v-if="!props.app_id && form.app_type === 'orchestrator'"
          class="flex flex-col gap-3 bg-gray-50 rounded-lg p-4 mb-4"
        >
          <div class="text-gray-700 font-bold text-sm">任务编排配置</div>
          <div class="flex items-center justify-between">
            <span class="text-xs text-gray-600">启用任务分解</span>
            <a-switch v-model="form.orchestrator_config.enable" size="small" type="round" />
          </div>
          <div class="flex flex-col gap-1">
            <span class="text-xs text-gray-600">最大子任务数</span>
            <a-input-number
              v-model="form.orchestrator_config.max_sub_tasks"
              :min="1"
              :max="20"
              size="small"
            />
          </div>
          <div class="flex flex-col gap-1">
            <span class="text-xs text-gray-600">最大并行数</span>
            <a-input-number
              v-model="form.orchestrator_config.max_parallel"
              :min="1"
              :max="10"
              size="small"
            />
          </div>
          <div class="flex flex-col gap-1">
            <span class="text-xs text-gray-600">单子任务超时（秒）</span>
            <a-input-number
              v-model="form.orchestrator_config.sub_task_timeout"
              :min="10"
              :max="3600"
              size="small"
            />
          </div>
          <div class="flex flex-col gap-1">
            <span class="text-xs text-gray-600">断点恢复模式</span>
            <a-select v-model="form.orchestrator_config.resume_mode" size="small">
              <a-option value="auto">auto（自动续跑）</a-option>
              <a-option value="manual">manual（仅手动触发）</a-option>
            </a-select>
          </div>
        </div>
        <!-- 底部按钮 -->
        <div class="flex items-center justify-between">
          <div class=""></div>
          <a-space :size="16">
            <a-button class="rounded-lg" @click="hideModal">取消</a-button>
            <a-button
              :loading="createAppLoading || updateAppLoading"
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
