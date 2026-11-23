<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useUpdateDraftAppConfig } from '@/hooks/use-app.ts'
import cloneDeep from 'lodash/cloneDeep'
import { isEqual } from 'lodash'
import type { GetDraftAppConfigResponse } from '@/models/app.ts'

const props = defineProps({
  app_id: { type: String, default: '', required: true },
  text_to_speech: {
    type: Object,
    default: () => {
      return {}
    },
    required: true,
  },
})

const { loading, handleUpdateDraftAppConfig } = useUpdateDraftAppConfig()
const isInit = ref(false)
const textToSpeechModalVisible = ref(false)

interface TextToSpeechForm {
  enable: boolean
  voice: string
  auto_play: boolean
}

const textToSpeechForm = ref<TextToSpeechForm>({
  enable: props.text_to_speech?.enable,
  voice: props.text_to_speech?.voice,
  auto_play: props.text_to_speech?.auto_play,
})

const originTextToSpeechForm = ref({ ...cloneDeep(textToSpeechForm.value) })

const isFormModified = () => {
  return !isEqual(originTextToSpeechForm.value, textToSpeechForm.value)
}

const handleCancelTextToSpeechModal = () => {
  textToSpeechModalVisible.value = false
  textToSpeechForm.value = cloneDeep(originTextToSpeechForm.value)
}

const handleSubmitTextToSpeech = async () => {
  await handleUpdateDraftAppConfig(props.app_id, {
    text_to_speech: {
      enable: textToSpeechForm.value.enable,
      voice: textToSpeechForm.value.voice,
      auto_play: textToSpeechForm.value.auto_play,
    },
  })

  originTextToSpeechForm.value = cloneDeep(textToSpeechForm.value)
  await nextTick()

  handleCancelTextToSpeechModal()
}

// 监听text_to_speech变化并同步到表单
watch(
  () => props.text_to_speech,
  (newValue: Partial<GetDraftAppConfigResponse['data']['text_to_speech']>) => {
    if (!isInit.value || !isFormModified()) {
      if (newValue && Object.keys(newValue).length > 0) {
// 更新表单数据和备份数据，使用深拷贝
        textToSpeechForm.value = { ...newValue } as TextToSpeechForm
        originTextToSpeechForm.value = { ...newValue } as TextToSpeechForm

        isInit.value = true
      }
    }
  },
  { immediate: true, deep: true },
)

const handleTextToSpeechSelect = async (value: unknown) => {
  const enable = Boolean(value)

  if (enable !== textToSpeechForm.value.enable) {
    try {
      textToSpeechForm.value.enable = enable

// 等待响应式刷新（如果你确实依赖）
      await nextTick()

      await handleSubmitTextToSpeech()
    } catch {
      /* ignore */
    }
  }
}

// 供外部（左侧「语音输出」导航）直接打开「语音输出」设置弹窗
defineExpose({ openAdd: () => { textToSpeechModalVisible.value = true } })
</script>

<template>
  <div class="">
    <a-collapse-item key="text_to_speech" class="app-ability-item text-to-speech">
      <template #header>
        <div class="text-gray-700 font-bold">语音输出</div>
      </template>
      <template #extra>
        <a-dropdown @select="handleTextToSpeechSelect">
          <a-button size="mini" class="rounded-lg flex items-center gap-1 px-1" @click.stop>
            {{ textToSpeechForm.enable ? '开启' : '关闭' }}
            <icon-down />
          </a-button>
          <template #content>
            <a-doption :value="1" class="text-xs py-1.5 text-gray-700">开启</a-doption>
            <a-doption :value="0" class="text-xs py-1.5 text-red-700">关闭</a-doption>
          </template>
        </a-dropdown>
      </template>
      <div class="group relative">
        <div class="ability-desc text-xs text-gray-500 leading-[28px]">
          在Bot回复后，语音播报回复内容。
        </div>
        <div
          v-if="textToSpeechForm.enable"
          class="absolute inset-0 flex items-center rounded-lg transition-all opacity-0 group-hover:opacity-100"
        >
          <a-button size="small" long class="rounded-lg" @click="textToSpeechModalVisible = true">
            <template #icon>
              <icon-settings />
            </template>
            语音设置
          </a-button>
        </div>
      </div>
    </a-collapse-item>
    <!-- 模态窗组件（auto-focus=false：避免 Arco 自动聚焦内部 aria-hidden 隐藏输入框触发 a11y 告警） -->
    <a-modal
      :visible="textToSpeechModalVisible"
      hide-title
      :footer="false"
      modal-class="rounded-xl"
      width="max(400px, min(520px, calc(100vw - 32px)))"
      :auto-focus="false"
      @cancel="handleCancelTextToSpeechModal"
    >
      <!-- 顶部标题 -->
      <div class="flex items-center justify-between">
        <div class="text-lg font-bold text-gray-700">语音输出</div>
        <a-button aria-label="关闭"
          type="text"
          class="!text-gray-700"
          size="small"
          @click="handleCancelTextToSpeechModal"
        >
          <template #icon>
            <icon-close />
          </template>
        </a-button>
      </div>
      <!-- 中间表单 -->
      <div class="py-4">
        <div class="flex flex-col gap-5">
          <!-- 总开关：开启语音输出 -->
          <div class="flex items-center justify-between p-3 bg-gray-50 border border-gray-200 rounded-lg">
            <div>
              <div class="text-gray-700">开启语音输出</div>
              <div class="text-gray-500 text-xs mt-1">关闭后音色与自动播放不可选择</div>
            </div>
            <a-switch
              v-model:model-value="textToSpeechForm.enable"
              size="small"
              type="round"
            />
          </div>
          <!-- 音色设置 -->
          <div class="flex flex-col gap-2">
            <div class="flex items-center gap-1 text-gray-700">
              音色设置
              <div class="text-red-700">*</div>
            </div>
            <div class="text-gray-500 text-xs">
              不同的音色适用于不同的场景，请结合业务需求选择合适的内容。
            </div>
          </div>
          <select
            v-model="textToSpeechForm.voice"
            :disabled="!textToSpeechForm.enable"
            aria-label="音色设置"
            class="w-full h-8 px-2 rounded-md border border-gray-200 text-sm bg-white focus:border-blue-500 focus:outline-none disabled:bg-gray-50 disabled:text-gray-400"
          >
            <option value="alloy">alloy</option>
            <option value="ash">ash</option>
            <option value="coral">coral</option>
            <option value="echo">echo</option>
            <option value="fable">fable</option>
            <option value="onyx">onyx</option>
            <option value="nova">nova</option>
            <option value="sage">sage</option>
            <option value="shimmer">shimmer</option>
          </select>

          <!-- 自动播放 -->
          <div class="flex flex-col gap-2">
            <div class="flex flex-col">
              <div class="flex items-center gap-1 text-gray-700">
                自动播放
                <div class="text-red-700">*</div>
              </div>
              <div class="text-gray-500 text-xs">Agent回复结束后，自动播放音频内容</div>
            </div>
            <div class="">
              <a-switch
                v-model:model-value="textToSpeechForm.auto_play"
                :disabled="!textToSpeechForm.enable"
                size="small"
                type="round"
              />
            </div>
          </div>
        </div>
      </div>
      <!-- 底部按钮 -->
      <div class="flex items-center justify-between">
        <div class=""></div>
        <a-space :size="16">
          <a-button class="rounded-lg" @click="handleCancelTextToSpeechModal">取消</a-button>
          <a-button
            :loading="loading"
            type="primary"
            class="rounded-lg"
            @click="handleSubmitTextToSpeech"
          >
            保存
          </a-button>
        </a-space>
      </div>
    </a-modal>
  </div>
</template>

<style scoped></style>
