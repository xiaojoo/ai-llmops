import { ref } from 'vue'
import { generateSuggestedQuestions, optimizePrompt } from '@/services/ai.ts'

export const useGenerateSuggestedQuestions = () => {
  const loading = ref<boolean>(false)
  const suggested_questions = ref<string[]>([])

  const handleGenerateSuggestedQuestions = async (message_id: string) => {
    try {
      loading.value = true
      const resp = await generateSuggestedQuestions(message_id)
      suggested_questions.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, suggested_questions, handleGenerateSuggestedQuestions }
}

export const useOptimizePrompt = () => {
  const loading = ref(false)
  const optimize_prompt = ref('')

  const handleOptimizePrompt = async (prompt: string) => {
    try {
      loading.value = true
      optimize_prompt.value = ''
      await optimizePrompt(prompt, (event_response) => {
        const data = event_response.data as { optimize_prompt?: string } | undefined
        optimize_prompt.value += data?.optimize_prompt
      })
    } finally {
      loading.value = false
    }
  }
  return { loading, optimize_prompt, handleOptimizePrompt }
}
