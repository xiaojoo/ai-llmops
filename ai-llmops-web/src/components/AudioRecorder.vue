<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { uploadFile } from '@/services/upload-file.ts'
import { audioToText } from '@/services/audio.ts'
import { Message } from '@arco-design/web-vue'

interface Props {
  autoPlay?: boolean
  showPlayer?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  autoPlay: false,
  showPlayer: true,
})
void props

const emit = defineEmits<{
  (e: 'start'): void
  (e: 'stop'): void
  (e: 'change', blob: Blob): void
  (e: 'finish', payload: { blob: Blob; url: string }): void
  (e: 'transcribed', text: string): void
}>()

/**
 * 状态说明
 * 1 = 可开始
 * 2 = 处理中
 * 3 = 录音中
 */
const isRecording = ref(1)

const audioUrl = ref<string | null>(null)
const mediaRecorder = ref<MediaRecorder | null>(null)
const audioChunks: BlobPart[] = []

const MAX_SIZE_MB = 50

/* =========================
   浏览器能力检测
========================= */
const browserSupportsRecording = !!window?.MediaRecorder && !!navigator?.mediaDevices?.getUserMedia

const getMimeType = () => {
  if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
    return 'audio/webm;codecs=opus'
  }
  if (MediaRecorder.isTypeSupported('audio/ogg;codecs=opus')) {
    return 'audio/ogg;codecs=opus'
  }
  if (MediaRecorder.isTypeSupported('audio/mp4')) {
    return 'audio/mp4'
  }
  return ''
}

/* =========================
   开始录音
========================= */
const startRecording = async () => {
  if (!browserSupportsRecording) {
    Message.warning('当前浏览器不支持录音')
    return
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })

    const mimeType = getMimeType()
    const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream)

    mediaRecorder.value = recorder
    audioChunks.length = 0

    recorder.addEventListener('dataavailable', async (event: BlobEvent) => {
      if (event.data && event.data.size > 0) {
        audioChunks.push(event.data)

        // 实时大小检测
        const totalSize = audioChunks.reduce((acc, b) => {
          if (b instanceof Blob) return acc + b.size
          if (typeof b === 'string') return acc + new TextEncoder().encode(b).length
          if (b instanceof ArrayBuffer) return acc + b.byteLength
          if (ArrayBuffer.isView(b)) return acc + b.byteLength
          return acc
        }, 0)

        const sizeMB = totalSize / 1024 / 1024

        if (sizeMB >= MAX_SIZE_MB) {
          Message.error(`音频超过 ${MAX_SIZE_MB}MB，自动停止`)
          await stopRecording(3)
        }
      }
    })

    recorder.start()

    isRecording.value = 3
    emit('start')
  } catch {
    Message.error('录音失败，请检查麦克风权限')
  }
}

/* =========================
   停止录音
========================= */
const stopRecording = async (auto = 1) => {
  const recorder = mediaRecorder.value
  if (!recorder || recorder.state === 'inactive') return

  isRecording.value = 2
  emit('stop')

  // 给尾音 200ms 缓冲
  await new Promise((resolve) => setTimeout(resolve, 200))

  await new Promise<void>((resolve) => {
    recorder.addEventListener(
      'stop',
      async () => {
        recorder.stream.getTracks().forEach((track) => track.stop())

        if (audioChunks.length) {
          const mimeType = recorder.mimeType || 'audio/webm'
          const blob = new Blob(audioChunks, { type: mimeType })

          if (audioUrl.value) {
            URL.revokeObjectURL(audioUrl.value)
          }

          audioUrl.value = URL.createObjectURL(blob)

          emit('change', blob)
          emit('finish', { blob, url: audioUrl.value })

          const sizeMB = blob.size / 1024 / 1024
          if (auto === 3 || sizeMB >= MAX_SIZE_MB) {
            await uploadAudio(blob)
          }
        }

        audioChunks.length = 0
        resolve()
      },
      { once: true },
    )

    recorder.stop()
  })
}

/* =========================
   上传并识别
========================= */
const uploadAudio = async (blob: Blob) => {
  try {
    const file = new File([blob], 'voice_input.webm', { type: blob.type })

    const ossUrl = await uploadFile(file)
    const res = await audioToText(ossUrl.data.key)

    if (res.code === 'success') {
      const transcripts = (
        res?.data as { text?: { transcripts?: { text: string }[] }[] } | undefined
      )?.text?.[0]?.transcripts
      if (!transcripts || transcripts.length === 0) {
        Message.error('识别失败：未检测到语音内容')
        return
      }
      const text = transcripts[0]?.text
      if (!text || text.trim() === '') {
        Message.error('识别失败：语音内容为空')
        return
      }

      emit('transcribed', text)
    } else {
      Message.error('识别失败: ' + res.message)
    }
  } catch {
    Message.error('网络请求错误')
  } finally {
    isRecording.value = 1
  }
}

/* =========================
   重置
========================= */
const resetRecording = () => {
  audioUrl.value = null
  audioChunks.length = 0
}

/* =========================
   卸载清理
========================= */
onBeforeUnmount(() => {
  mediaRecorder.value?.stop()
})

defineExpose({
  startRecording,
  stopRecording,
  resetRecording,
})
</script>

<template>
  <a-tooltip v-if="isRecording === 2" content="语音处理中">
    <a-button type="text" shape="circle" aria-label="语音处理中">
      <template #icon>
        <icon-loading :size="16" />
      </template>
    </a-button>
  </a-tooltip>

  <a-tooltip v-if="isRecording === 1" content="语音转文字">
    <a-button type="text" shape="circle" class="!text-gray-700" aria-label="语音转文字" @click="startRecording">
      <template #icon>
        <icon-voice :size="16" />
      </template>
    </a-button>
  </a-tooltip>
  <a-tooltip v-if="isRecording === 3" content="停止录音">
    <a-button type="text" shape="circle" aria-label="停止录音" @click="stopRecording(3)">
      <template #icon>
        <icon-pause :size="16" />
      </template>
    </a-button>
  </a-tooltip>
</template>
