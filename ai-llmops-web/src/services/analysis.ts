import { http } from '@/utils/http'
import type { GetAppAnalysisResponse } from '@/models/analysis.ts'

enum API {
  ANALYSIS_API_BASE = '/analysis',
}

export const getAppAnalysis = (app_id: string) =>
  http.get<GetAppAnalysisResponse>(API.ANALYSIS_API_BASE + `/${app_id}`)
