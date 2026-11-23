import { stream } from '@/utils/http/stream.ts'
import { http } from '@/utils/http'
import type { BaseResponse } from '@/models/base.ts'

enum API {
  APP = '/ai',
}

// 优化预设prompt服务接口
export const optimizePrompt = (
  prompt: string,
  onData: (event_response: Record<string, unknown>) => void,
) => {
  return stream({
    url: API.APP + `/optimize_prompt`,
    body: { prompt },
    onMessage: (data, event) => {
      onData({ event: event.event, data })
    },
  })
}

// 生成建议问题列表接口
export const generateSuggestedQuestions = (message_id: string) =>
  http.post<BaseResponse<string[]>>(API.APP + `/suggested_questions`, { message_id })
