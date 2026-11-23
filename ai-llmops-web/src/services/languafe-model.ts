import { http } from '@/utils/http'
import type {
  GetLanguageModelResponse,
  GetLanguageModelsResponse,
} from '@/models/language-model.ts'

enum API {
  BASE_LANGUAGE_MODELS = '/language_models',
}

// 获取所有语言模型列表信息
export const getLanguageModels = () => http.get<GetLanguageModelsResponse>(API.BASE_LANGUAGE_MODELS)

// 获取指定模型的详细信息
export const getLanguageModel = (provider_name: string, model_name: string) =>
  http.get<GetLanguageModelResponse>(API.BASE_LANGUAGE_MODELS + `/${provider_name}/${model_name}`)
