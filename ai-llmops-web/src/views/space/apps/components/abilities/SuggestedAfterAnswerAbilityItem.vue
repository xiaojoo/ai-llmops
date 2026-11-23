<script setup lang="ts">
import type { PropType } from 'vue'
import { useUpdateDraftAppConfig } from '@/hooks/use-app.ts'

const props = defineProps({
  app_id: { type: String, required: true },
  suggested_after_answer: {
    type: Object as PropType<{ enable: boolean }>,
    required: true,
    default: () => ({ enable: false }),
  },
})

const emits = defineEmits(['update:suggested_after_answer'])

const { handleUpdateDraftAppConfig } = useUpdateDraftAppConfig()

const onSelectSuggestedAfterAnswer = async (value: unknown) => {
  const enable = Boolean(value)
  if (enable === props.suggested_after_answer?.enable) return
  emits('update:suggested_after_answer', { enable })
  await handleUpdateDraftAppConfig(props.app_id, {
    suggested_after_answer: { enable },
  })
}
</script>

<template>
  <div>
    <a-collapse-item key="suggested_after_answer" class="app-ability-item">
      <template #header>
        <div class="text-gray-700 font-bold">用户问题建议</div>
      </template>
      <template #extra>
        <a-dropdown @select="onSelectSuggestedAfterAnswer">
          <a-button size="mini" class="rounded-lg flex items-center gap-1 px-1" @click.stop>
            {{ props.suggested_after_answer.enable ? '开启' : '关闭' }}
            <icon-down />
          </a-button>
          <template #content>
            <a-doption :value="1" class="text-xs py-1.5 text-gray-700">开启</a-doption>
            <a-doption :value="0" class="text-xs py-1.5 text-red-700">关闭</a-doption>
          </template>
        </a-dropdown>
      </template>
      <div class="text-xs text-gray-500 leading-[28px]">
        在应用回复后，自动根据对话内容提供3条用户提问建议。
      </div>
    </a-collapse-item>
  </div>
</template>

<style scoped></style>
