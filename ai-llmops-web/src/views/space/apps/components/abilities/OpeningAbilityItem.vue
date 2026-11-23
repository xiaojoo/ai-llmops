<script setup lang="ts">
import { ref, type PropType } from 'vue'
import { useUpdateDraftAppConfig } from '@/hooks/use-app.ts'
import { Message } from '@arco-design/web-vue'

const props = defineProps({
  app_id: { type: String, required: true },
  opening_statement: { type: String, required: true, default: '' },
  opening_questions: {
    type: Array as PropType<string[]>,
    required: true,
    default: () => [],
  },
})

const emits = defineEmits(['update:opening_statement', 'update:opening_questions'])

const { loading, handleUpdateDraftAppConfig } = useUpdateDraftAppConfig()

// 本地草稿：仅点「保存」才写入，取消/关闭即丢弃
const localStatement = ref(props.opening_statement || '')

// 展示行：先只显示 1 个空输入框；有内容后追加下一个（最多 3 个），空行只保留尾部 1 个输入位
const localQuestions = ref<string[]>([''])
const normalizeRows = (rows: string[]): string[] => {
  const filled = rows.filter((r) => r !== '')
  const out = filled.slice(0, 3)
  if (out.length < 3) out.push('')
  return out
}
localQuestions.value = normalizeRows([...(props.opening_questions || [])])

const updateQuestionAt = (idx: number, value: string) => {
  const next = [...localQuestions.value]
  next[idx] = value
  localQuestions.value = normalizeRows(next)
}

// 删除对应的那一行
const removeQuestion = (idx: number) => {
  const next = [...localQuestions.value]
  next.splice(idx, 1)
  localQuestions.value = normalizeRows(next)
}

// 保存：过滤空行后一次性写入
const save = async (): Promise<boolean> => {
  const questions = localQuestions.value.map((s) => s.trim()).filter((s) => s !== '')
  try {
    await handleUpdateDraftAppConfig(props.app_id, {
      opening_statement: localStatement.value,
      opening_questions: questions,
    })
    emits('update:opening_statement', localStatement.value)
    emits('update:opening_questions', questions)
    Message.success('对话开场白已保存')
    return true
  } catch {
    Message.error('保存失败，请重试')
    return false
  }
}

defineExpose({ save, loading })
</script>

<template>
  <div class="flex flex-col gap-4">
    <!-- 开场白文案 -->
    <div class="flex flex-col gap-2">
      <div class="flex items-center gap-2">
        <div class="text-gray-700 font-medium">开场白文案</div>
        <a-tooltip content="开场白是与Agent应用对话时，Agent默认展示的对话。">
          <icon-exclamation-circle />
        </a-tooltip>
      </div>
      <a-textarea
        v-model:model-value="localStatement"
        placeholder="在此处填写 AI 应用的开场白"
        class="bg-white text-gray-700 rounded-lg border border-gray-200"
        :auto-size="{ minRows: 4, maxRows: 4 }"
      />
    </div>
    <!-- 开场白建议问题 -->
    <div class="flex flex-col gap-2">
      <div class="flex items-center gap-2">
        <div class="text-gray-700 font-medium">开场白预设问题</div>
        <a-tooltip content="开场白预设问题是与Agent对话时，初始化提供的建议问题，最多不超过3个。">
          <icon-exclamation-circle />
        </a-tooltip>
      </div>
      <div class="flex flex-col gap-2">
        <div
          v-for="(question, idx) in localQuestions"
          :key="idx"
          class="flex items-center gap-2"
        >
          <a-input
            :model-value="question"
            placeholder="输入开场白引导问题"
            class="rounded-lg bg-white"
            @update:model-value="(value: string) => updateQuestionAt(idx, value)"
          />
          <a-button
            aria-label="删除"
            class="rounded-lg"
            :disabled="question === '' && localQuestions.length <= 1"
            @click="removeQuestion(idx)"
          >
            <template #icon>
              <icon-delete />
            </template>
          </a-button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped></style>
