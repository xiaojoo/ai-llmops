import { ref } from 'vue'
import type { GetLanguageModelResponse, GetLanguageModelsResponse } from '@/models/language-model.ts'
import { getLanguageModel, getLanguageModels } from '@/services/languafe-model.ts'

export const useGetLanguageModels = () => {
// 定义自定义hooks所需数据
  const loading = ref(false)
  const language_models = ref<GetLanguageModelsResponse['data']>([])

  const loadLanguageModels = async () => {
    try {
      loading.value = true
      const resp = await getLanguageModels()
      language_models.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, language_models, loadLanguageModels }
}

export const useGetLanguageModel = () => {
// 定义自定义hooks所需数据
  const loading = ref(false)
  const language_model = ref<Partial<GetLanguageModelResponse['data']>>({})

  const loadLanguageModel = async (provider_name: string, model_name: string) => {
    try {
      loading.value = true
      const resp = await getLanguageModel(provider_name, model_name)
      language_model.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, language_model, loadLanguageModel }
}
