import { onUnmounted, ref, shallowRef } from 'vue'
import { Message } from '@arco-design/web-vue'
import { audioToText, messageToAudio } from '@/services/audio.ts'

export const useAudioToText = () => {
  const loading = ref(false)
  const text = ref('')

  const handleAudioToText = async (ossUrl: string) => {
    try {
      loading.value = true
      const resp = await audioToText(ossUrl)
      Message.success('语音转文本成功')
      text.value = (resp.data as { text?: string } | undefined)?.text ?? ''
    } finally {
      loading.value = false
    }
  }

  return { loading, text, handleAudioToText }
}

// 消息转音频（新增 signal 参数）
export const useMessageToAudio = () => {
  const loading = ref(false)

  const handleMessageToAudio = async (
    message_id: string,
    onData: (event_response: Record<string, unknown>) => void,
    signal?: AbortSignal,
  ) => {
    try {
      loading.value = true
      await messageToAudio(message_id, onData, signal)
    } catch (e: unknown) {
      // AbortError 是主动取消，不报错
      if ((e as { name?: string } | undefined)?.name !== 'AbortError') {
        console.error('messageToAudio error:', e)
      }
    } finally {
      loading.value = false
    }
  }

  return { loading, handleMessageToAudio }
}

// 音频播放器 (流式播放版：Web Audio API)
export const useAudioPlayer = () => {
  const isPlaying = ref(false)
  const { loading: textToAudioLoading, handleMessageToAudio } = useMessageToAudio()

  const audioContext = shallowRef<AudioContext | null>(null)
  let nextStartTime = 0
  let abortController: AbortController | null = null
  let checkInterval: ReturnType<typeof setInterval> | null = null

  const DEFAULT_SAMPLE_RATE = 24000

  // 清除轮询
  const clearCheckInterval = () => {
    if (checkInterval) {
      clearInterval(checkInterval)
      checkInterval = null
    }
  }

  // 初始化 AudioContext
  const initAudioContext = async () => {
    if (audioContext.value) {
      await audioContext.value.close()
      audioContext.value = null
    }
    const AudioContextClass = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
    audioContext.value = new AudioContextClass()
    if (audioContext.value.state === 'suspended') {
      await audioContext.value.resume()
    }
  }

  // Base64 -> Float32Array
  const decodeChunk = (base64Data: string): Float32Array | null => {
    try {
      const binaryString = atob(base64Data.replace(/[\r\n\s]/g, ''))
      const len = binaryString.length
      const buffer = new ArrayBuffer(len)
      const view = new DataView(buffer)
      for (let i = 0; i < len; i++) {
        view.setUint8(i, binaryString.charCodeAt(i))
      }
      const int16Data = new Int16Array(buffer)
      const float32Data = new Float32Array(int16Data.length)
      for (let i = 0; i < int16Data.length; i++) {
        const sample = int16Data[i] ?? 0
        float32Data[i] = sample / 32768.0
      }
      return float32Data
    } catch {
      return null
    }
  }

  // 播放单个音频片段
  const playChunk = (float32Data: Float32Array) => {
    if (!audioContext.value) return
    const ctx = audioContext.value
    const audioBuffer = ctx.createBuffer(1, float32Data.length, DEFAULT_SAMPLE_RATE)
    audioBuffer.copyToChannel(new Float32Array(float32Data), 0)
    const source = ctx.createBufferSource()
    source.buffer = audioBuffer
    source.connect(ctx.destination)
    if (nextStartTime < ctx.currentTime) {
      nextStartTime = ctx.currentTime
    }
    source.start(nextStartTime)
    nextStartTime += audioBuffer.duration
    isPlaying.value = true
  }

  // 轮询检查音频是否播放完毕
  const checkPlaybackEnd = () => {
    clearCheckInterval()
    checkInterval = setInterval(() => {
      if (audioContext.value && audioContext.value.currentTime >= nextStartTime) {
        isPlaying.value = false
        clearCheckInterval()
      }
    }, 500)
  }

  const startAudioStream = async (messageId: string) => {
    // 中断上一次请求和轮询
    abortController?.abort()
    clearCheckInterval()

    // 重置状态
    isPlaying.value = false
    nextStartTime = 0

    // 创建新的 AbortController
    abortController = new AbortController()
    const signal = abortController.signal

    // 等待 AudioContext 完全初始化
    await initAudioContext()

    if (audioContext.value) {
      nextStartTime = audioContext.value.currentTime
    }

    isPlaying.value = true

    await handleMessageToAudio(
      messageId,
      (event_response) => {
        // 已中断则忽略
        if (signal.aborted) return

        const event = event_response.event
        let raw: unknown = event_response.data

        if (typeof raw === 'string') {
          try {
            raw = JSON.parse(raw)
          } catch {
            /* ignore parse error */
          }
        }

        // TTS 事件负载：audio 为 Base64 音频片段，error 为错误信息
        const payload = (raw && typeof raw === 'object' ? raw : {}) as {
          audio?: string
          error?: string
        }

        if (event === 'tts_error') {
          Message.error(payload.error || '文字转语音失败')
          isPlaying.value = false
          nextStartTime = 0
          clearCheckInterval()
          return
        }

        if (event === 'tts_message' && payload.audio) {
          const float32Data = decodeChunk(payload.audio)
          if (float32Data && float32Data.length > 0) {
            playChunk(float32Data)
          }
        }

        if (event === 'tts_end') {
          checkPlaybackEnd()
        }
      },
      signal,
    )
  }

  const stopAudioStream = () => {
    // 中断 HTTP 请求
    abortController?.abort()
    abortController = null

    // 清除播放完成轮询
    clearCheckInterval()

    // 关闭 AudioContext 立即停止声音
    if (audioContext.value) {
      audioContext.value.close().then(() => {
        audioContext.value = null
      })
    }

    isPlaying.value = false
    nextStartTime = 0
  }

  onUnmounted(() => {
    stopAudioStream()
  })

  return {
    textToAudioLoading,
    isPlaying,
    startAudioStream,
    stopAudioStream,
  }
}
