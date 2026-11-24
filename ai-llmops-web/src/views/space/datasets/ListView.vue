<script setup lang="ts">
import { useCreateOrUpdateDataset, useDeleteDataset, useGetDatasetsWithPage, } from '@/hooks/use-dataset'
import moment from 'moment'
import { getDataset } from '@/services/dataset.ts'
import type { RequestOption, UploadRequest, ValidatedError } from '@arco-design/web-vue'
import { uploadImage } from '@/services/upload-file.ts'

const props = defineProps({
  createType: {
    type: String,
    required: true,
  },
})

const emits = defineEmits(['update-create-type'])
const { loading, datasets, paginator, loadDatasets } = useGetDatasetsWithPage()
const { handleDelete } = useDeleteDataset()
const {
  loading: submitLoading,
  form,
  formRef,
  showUpdateModal,
  updateShowUpdateModal,
  saveDataset,
} = useCreateOrUpdateDataset()
let updateDatasetID = ''

const handleScroll = async (event: UIEvent) => {
  const { scrollTop, scrollHeight, clientHeight } = event.target as HTMLElement
  if (scrollTop + clientHeight >= scrollHeight - 10) {
    if (loading.value) {
      return
    }
    await loadDatasets()
  }
}

// 编辑知识库处理器
const handleSet = (dataset_id: string) => {
  updateShowUpdateModal(true, async () => {
    const resp = await getDataset(dataset_id)
    const data = resp.data
    updateDatasetID = dataset_id

    formRef.value?.resetFields()
    form.fileList = [{ uid: '1', name: '知识库图标', url: data.icon }]
    form.icon = data.icon
    form.name = data.name
    form.description = data.description
  })
}

// 取消模态窗
const handleCancel = () => {
  updateShowUpdateModal(false, async () => {
    updateDatasetID = ''
    formRef.value?.resetFields()

    emits('update-create-type', '')
  })
}

// 提交模态窗
const handleSubmit = async ({ errors }: { errors: Record<string, ValidatedError> | undefined }) => {
  if (errors) return
  await saveDataset(updateDatasetID)
  handleCancel()
  await loadDatasets(true)
}
</script>

<template>
  <a-spin
    :loading="loading"
    class="h-full w-full scrollbar-w-none overflow-scroll"
    @scroll="handleScroll"
  >
    <!-- 内容区（响应式：视口缩小时卡片自动换行） -->
    <div class="w-full">
      <a-row :gutter="[20, 20]" class="flex-1">
        <a-col
          v-for="dataset in datasets"
          :key="dataset.id"
          :xs="24"
          :sm="12"
          :md="8"
          :lg="6"
          :xl="6"
          :xxl="6"
        >
          <a-card hoverable class="cursor-pointer rounded-lg">
            <div class="flex items-center gap-3 mb-3">
              <a-avatar :size="40" shape="square" :image-url="dataset.icon" />
              <div class="flex flex-1 justify-between">
                <div class="flex flex-col">
                  <router-link
                    :to="{
                      name: 'space-datasets-documents-list',
                      params: { dataset_id: dataset.id },
                    }"
                    class="text-base text-gray-900 font-bold line-clamp-1"
                    >{{ dataset.name }}</router-link
                  >
                  <div class="text-xs text-gray-500 line-clamp-1">
                    {{ dataset.document_count }} 文档 ·
                    {{ Math.round(dataset.character_count / 1000) }} 千字符 ·
                    {{ dataset.related_app_count }} 关联应用
                  </div>
                </div>
                <a-dropdown position="br">
                  <a-button aria-label="更多操作" type="text" size="small" class="round-lg !text-gray-700">
                    <template #icon>
                      <icon-more />
                    </template>
                  </a-button>
                  <template #content>
                    <a-doption @click="() => handleSet(dataset.id)">设置</a-doption>
                    <a-doption
                      @click="() => handleDelete(dataset.id, () => loadDatasets(true))"
                      class="!text-red-500"
                      >删除</a-doption
                    >
                  </template>
                </a-dropdown>
              </div>
            </div>
            <div class="leading-[18px] text-gray-500 h-[72px] line-clamp-4 mb-2">
              {{ dataset.description }}
            </div>
            <div class="flex items-center gap-1.5">
              <a-avatar :size="18" class="bg-blue-700">
                <icon-user />
              </a-avatar>
              <div class="text-xs text-gray-400">
                DeepSeek · 最近编辑 {{ moment(dataset.created_at).format('MM-DD HH:mm:ss') }}
              </div>
            </div>
          </a-card>
        </a-col>
        <a-col v-if="datasets.length === 0" :span="24">
          <a-empty
            description="没有可用的知识库"
            class="h-[400px] flex flex-col items-center justify-center"
          />
        </a-col>
      </a-row>
      <a-row v-if="paginator.total_page >= 2">
        <a-col v-if="paginator.current_page <= paginator.total_page" :span="24" class="text-center">
          <a-space class="my-4">
            <a-spin />
            <div class="text-gray-400">加载中</div>
          </a-space>
        </a-col>
        <a-col v-else :span="24" class="text-center">
          <div class="text-gray-400 my-4">数据已全部加载</div>
        </a-col>
      </a-row>
    </div>
    <a-modal
      :width="'clamp(200px, 80vw, 520px)'"
      :visible="props.createType === 'dataset' || showUpdateModal"
      hide-title
      :footer="false"
      modal-class="rounded-xl"
      @cancel="handleCancel"
    >
      <div class="flex items-center justify-between">
        <div class="text-lg font-bold text-gray-700">
          {{ props.createType === 'dataset' ? '新建' : '更新' }}知识库
        </div>
        <a-button aria-label="关闭" @click="handleCancel" type="text" class="!text-gray-700" size="small">
          <template #icon>
            <icon-close />
          </template>
        </a-button>
      </div>
      <div class="pt-6">
        <a-form ref="formRef" :model="form" @submit="handleSubmit" layout="vertical">
          <a-form-item
            field="fileList"
            hide-label
            :rules="[{ required: true, message: '知识库图标不能为空' }]"
          >
            <a-upload
              id="form-icon"
              name="form-icon"
              :limit="1"
              list-type="picture-card"
              accept="image/png, image/jpeg"
              image-preview
              class="w-auto! mx-auto"
              v-model:file-list="form.fileList"
              :custom-request="
                (option: RequestOption): UploadRequest => {
                  const { fileItem, onSuccess, onError } = option
                  // a-upload 的 custom-request 需同步返回 UploadRequest（{ abort }），
                  // 异步上传逻辑放在内部任务中执行
                  const uploadTask = async () => {
                    try {
                      const resp = await uploadImage(fileItem.file as File)
                      form.icon = resp.data.image_url
                      onSuccess(resp)
                    } catch (err) {
                      onError?.(err)
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
            label="知识库名称"
            asterisk-position="end"
            :rules="[{ required: true, message: '知识库名称不能为空' }]"
          >
            <a-input
              id="form-name"
              name="form-name"
              v-model="form.name"
              placeholder="请输入知识库名称"
              show-word-limit
              :max-length="60"
            />
          </a-form-item>
          <a-form-item
            field="description"
            label="知识库描述"
            asterisk-position="end"
            :rules="[{ required: true, message: '知识库描述不能为空' }]"
          >
            <a-textarea
              id="form-description"
              name="form-description"
              v-model="form.description"
              :auto-size="{ minRows: 4, maxRows: 6 }"
              placeholder="请输入知识库描述"
            />
          </a-form-item>
          <div class="flex justify-end">
            <a-space :size="16">
              <a-button class="rounded-lg" @click="handleCancel">取消</a-button>
              <a-button
                :loading="submitLoading"
                type="primary"
                html-type="submit"
                class="rounded-lg"
                >保存</a-button
              >
            </a-space>
          </div>
        </a-form>
      </div>
    </a-modal>
  </a-spin>
</template>

<style scoped></style>
