<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useUpdateDraftAppConfig } from '@/hooks/use-app.ts'
import { isEqual } from 'lodash'
import cloneDeep from 'lodash/cloneDeep'
import { showErrorToast } from '@/utils/http/error'
import type { GetDraftAppConfigResponse } from '@/models/app.ts'

const props = defineProps({
  app_id: { type: String, required: true, default: '' },
  review_config: {
    type: Object,
    required: true,
    default: () => ({}),
  },
})
// const emits = defineEmits(['update:review_config'])

const { loading, handleUpdateDraftAppConfig } = useUpdateDraftAppConfig()
const isInit = ref(false)

interface ReviewConfigForm {
  enable: boolean
  keywords: string
  inputs_config: {
    enable: boolean
    preset_response: string
  }
  outputs_config: {
    enable: boolean
  }
}

const reviewConfigForm = ref<ReviewConfigForm>({
  enable: props.review_config?.enable,
  keywords: props.review_config?.keywords?.join('\n'),
  inputs_config: {
    enable: props.review_config?.inputs_config?.enable,
    preset_response: props.review_config?.inputs_config?.preset_response,
  },
  outputs_config: {
    enable: props.review_config?.outputs_config?.enable,
  },
})
const reviewConfigModalVisible = ref(false)

const originReviewConfigForm = ref({ ...cloneDeep(reviewConfigForm.value) })

const isFormModified = () => {
  return isEqual(originReviewConfigForm.value, reviewConfigForm.value)
}

const handleCancelReviewConfigModal = () => {
  reviewConfigModalVisible.value = false
  // 还原表单数据
  reviewConfigForm.value = cloneDeep(originReviewConfigForm.value)
}

// 提交审核配置模态框存储内容
const handleSubmitReviewConfig = async () => {
  try {
    await handleUpdateDraftAppConfig(props.app_id, {
      review_config: {
        enable: reviewConfigForm.value.enable,
        keywords: reviewConfigForm.value.keywords
          .split(/\r?\n/)
          .filter((item: string) => item.trim() !== ''),
        inputs_config: reviewConfigForm.value.inputs_config,
        outputs_config: reviewConfigForm.value.outputs_config,
      },
    })
    // 接口更新成功，同步表单信息
    originReviewConfigForm.value = cloneDeep(reviewConfigForm.value)
    await nextTick()

    handleCancelReviewConfigModal()
  } catch (e) {
    showErrorToast(String(e))
  }
}

// 监听review_config变化并同步到表单
watch(
  () => props.review_config,
  (newValue: Partial<GetDraftAppConfigResponse['data']['review_config']>) => {
    // 检测数据是否更新并且未初始化
    if (!isInit.value || !isFormModified()) {
      if (newValue && Object.keys(newValue).length > 0) {
        // 更新表单数据和备份数据，使用深拷贝
        reviewConfigForm.value = cloneDeep({
          ...newValue,
          keywords: newValue.keywords?.join('\n'),
        }) as ReviewConfigForm
        originReviewConfigForm.value = cloneDeep({
          ...newValue,
          keywords: newValue.keywords?.join('\n'),
        }) as ReviewConfigForm
        // 标记为已初始化
        isInit.value = true
      }
    }
  },
  { immediate: true, deep: true },
)

const onSelectEnable = async (value: unknown) => {
  const enable = Boolean(value)
  if (enable === reviewConfigForm.value.enable) return
  try {
    // 更新本地 reactive 状态
    reviewConfigForm.value.enable = enable
    await nextTick()
    // 提交表单
    await handleSubmitReviewConfig()
  } catch (e) {
    showErrorToast(String(e))
  }
}

// 供外部（左侧「内容审查」导航）直接打开「内容审核」弹窗
defineExpose({ openAdd: () => { reviewConfigModalVisible.value = true } })
</script>

<template>
  <div>
    <a-collapse-item key="review_config" class="app-ability-item review-config-ability-item">
      <template #header>
        <div class="text-gray-700 font-bold">内容审查</div>
      </template>
      <template #extra>
        <a-dropdown @select="onSelectEnable">
          <a-button size="mini" class="rounded-lg flex items-center gap-1 px-1" @click.stop>
            {{ reviewConfigForm.enable ? '开启' : '关闭' }}
            <icon-down />
          </a-button>
          <template #content>
            <a-doption :value="1" class="text-xs py-1.5 text-gray-700">开启</a-doption>
            <a-doption :value="0" class="text-xs py-1.5 text-gray-700">关闭</a-doption>
          </template>
        </a-dropdown>
      </template>
      <div class="group relative">
        <div class="ability-desc text-xs text-gray-500 leading-[28px]">
          对用户输入以及大语言模型输出内容进行审查。
        </div>
        <div
          v-if="reviewConfigForm.enable"
          class="absolute inset-0 flex items-center rounded-lg transition-all opacity-0 group-hover:opacity-100"
        >
          <a-button size="small" long class="rounded-lg" @click="reviewConfigModalVisible = true">
            <template #icon>
              <icon-settings />
            </template>
            设置
          </a-button>
        </div>
      </div>
    </a-collapse-item>
    <a-modal
      :visible="reviewConfigModalVisible"
      hide-title
      :footer="false"
      width="max(400px, min(520px, calc(100vw - 32px)))"
      modal-class="rounded-xl"
      @cancel="handleCancelReviewConfigModal"
    >
      <!-- 顶部标题 -->
      <div class="flex items-center justify-between">
        <div class="text-lg font-bold text-gray-700">内容审核</div>
        <a-button aria-label="关闭"
          type="text"
          class="text-gray-700"
          size="small"
          @click="handleCancelReviewConfigModal"
        >
          <template #icon>
            <icon-close />
          </template>
        </a-button>
      </div>
      <!-- 中间表单 -->
      <div class="py-4">
        <div class="flex flex-col gap-5">
          <!-- 总开关：开启内容审核 -->
          <div class="flex items-center justify-between p-3 bg-gray-50 border border-gray-200 rounded-lg">
            <div>
              <div class="text-gray-700">开启内容审核</div>
              <div class="text-gray-500 text-xs mt-1">关闭后关键词与预设回复等输入框不可编辑</div>
            </div>
            <a-switch
              v-model:model-value="reviewConfigForm.enable"
              size="small"
              type="round"
            />
          </div>
          <!-- 关键词 -->
          <div class="flex flex-col gap-2">
            <div class="flex flex-col">
              <div class="flex items-center gap-1 text-gray-700">
                关键词
                <div class="text-red-700">*</div>
              </div>
              <div class="text-gray-500 text-xs">每行一个，用换行符分割，最多填写100个关键词</div>
            </div>
            <a-textarea
              v-model:model-value="reviewConfigForm.keywords"
              :disabled="!reviewConfigForm.enable"
              class="bg-white rounded-lg border border-gray-200"
              placeholder="每行一个，用换行符分隔。"
              :max-length="100"
              show-word-limit
              :auto-size="{ minRows: 4, maxRows: 4 }"
              :word-length="
                (value) => {
                  if (value.trim() == '') return 0
                  return value.split(/\r\n/).length
                }
              "
              :word-slice="
                (value, maxLength) => {
                  // 分割内容并截取前100个关键词
                  const lines = value.split(/\r?\n/)
                  const first100Lines = lines.slice(0, maxLength)

                  return first100Lines.join('\n')
                }
              "
            />
            <!-- 输入审核 -->
            <div class="flex flex-col gap-2 p-3 bg-gray-50 border border-gray-200 rounded-lg">
              <div class="flex items-center justify-between">
                <div class="text-gray-700">输入审查内容</div>
                <a-switch
                  v-model:model-value="reviewConfigForm.inputs_config.enable"
                  :disabled="!reviewConfigForm.enable"
                  size="small"
                  type="round"
                />
              </div>
              <div class="flex flex-col gap-2">
                <div class="text-gray-700 text-xs">预设回复</div>
                <a-textarea
                  v-model:model-value="reviewConfigForm.inputs_config.preset_response"
                  :disabled="!reviewConfigForm.enable"
                  placeholder="这里是预设回复内容"
                  class="bg-white rounded-lg border border-gray-200"
                  :auto-size="{ minRows: 3, maxRows: 3 }"
                />
              </div>
            </div>
            <!-- 输出审核 -->
            <div class="flex flex-col p-3 bg-gray-50 border border-gray-200 rounded-lg">
              <div class="flex items-center justify-between">
                <div class="text-gray-700">输出审查内容</div>
                <a-switch
                  v-model:model-value="reviewConfigForm.outputs_config.enable"
                  :disabled="!reviewConfigForm.enable"
                  size="small"
                  type="round"
                />
              </div>
            </div>
          </div>
        </div>
      </div>
      <!-- 底部按钮 -->
      <div class="flex items-center justify-between">
        <div class=""></div>
        <a-space :size="16">
          <a-button class="rounded-lg" @click="handleCancelReviewConfigModal">取消</a-button>
          <a-button
            :loading="loading"
            type="primary"
            class="rounded-lg"
            @click="handleSubmitReviewConfig"
          >
            保存
          </a-button>
        </a-space>
      </div>
    </a-modal>
  </div>
</template>

<style>
.review-config-ability-item {
  .arco-collapse-item-content-box {
    padding: 0;
  }
}
</style>
