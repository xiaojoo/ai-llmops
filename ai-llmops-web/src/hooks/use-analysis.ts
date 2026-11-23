import { ref } from 'vue'
import type { GetAppAnalysisResponse } from '@/models/analysis.ts'
import { getAppAnalysis } from '@/services/analysis.ts'

export const useGetAppAnalysis = () => {
  const loading = ref(false)
  const app_analysis = ref<GetAppAnalysisResponse['data'] | null>(null)

  const loadAppAnalysis = async (app_id: string) => {
    try {
      loading.value = true
      const resp: GetAppAnalysisResponse = await getAppAnalysis(app_id)
      app_analysis.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, app_analysis, loadAppAnalysis }
}
