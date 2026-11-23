<script setup lang="ts">
import { useUpdateDraftAppConfig } from '@/hooks/use-app.ts'
import type { PropType } from 'vue'

const props = defineProps({
  app_id: { type: String, default: '', required: true },
  speech_to_text: {
    type: Object as PropType<{ enable: boolean }>,
    default: () => {
      return { enable: false }
    },
    required: true,
  },
})

const emits = defineEmits(['update:speech_to_text'])
const { handleUpdateDraftAppConfig } = useUpdateDraftAppConfig()

const handleSpeechToTextStep = async (value: unknown) => {
  const enable = Boolean(value)

  if (enable !== props.speech_to_text?.enable) {
    emits('update:speech_to_text', { enable })

    await handleUpdateDraftAppConfig(props.app_id, {
      speech_to_text: { enable },
    })
  }
}
</script>

<template>
  <div class="">
    <a-collapse-item key="speech_to_text" class="app-ability-item">
      <template #header>
        <div class="text-gray-700 font-bold">语音输入</div>
      </template>
      <template #extra>
        <a-dropdown @select="handleSpeechToTextStep">
          <a-button size="mini" class="rounded-lg flex items-center gap-1 px-1" @click.stop>
            {{ props.speech_to_text.enable ? '开启' : '关闭' }}
            <icon-down />
          </a-button>
          <template #content>
            <a-doption :value="1" class="text-xs py-1.5 text-gray-700">开启</a-doption>
            <a-doption :value="0" class="text-xs py-1.5 text-red-700">关闭</a-doption>
          </template>
        </a-dropdown>
      </template>
      <div class="ability-desc text-xs text-gray-500 leading-[28px]">启用后，您可以使用语音输入。</div>
    </a-collapse-item>
  </div>
</template>

<style scoped></style>
