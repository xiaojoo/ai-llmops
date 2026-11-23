import { http } from '@/utils/http'
import type { BaseResponse } from '@/models/base.ts'
import { stream } from '@/utils/http/stream.ts'

enum API {
  AUDIO_BASE = '/audio',
}

// 语音转文本输入接口
export const audioToText = (ossUrl: string) =>
  http.post<BaseResponse<unknown>>(API.AUDIO_BASE + '/audio_to_text', { ossUrl })

// 文本转语音输出接口
export const messageToAudio = (
  message_id: string,
  onData: (event_response: Record<string, unknown>) => void,
  signal?: AbortSignal,
) => {
  return stream({
    url: API.AUDIO_BASE + `/message_to_audio`,
    body: { message_id },
    signal,
    onMessage: (data, event) => {
      // 如果已中断则不处理
      if (signal?.aborted) return
      onData({ event: event.event, data })
    },
  })
}
