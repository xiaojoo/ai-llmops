<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import AudioRecorder from '@/components/AudioRecorder.vue'
import { uploadFile, uploadImage } from '@/services/upload-file.ts'
import type { ChatFileItem } from '@/models/chat-file.ts'

/**
 * 聊天输入栏：清空按钮（可选）+ 自适应高度输入框（图片/文件粘贴、上传、拖拽上传、预览，
 * 语音转文字、发送）+ 底部免责声明。
 * 三个聊天页（/home、web-apps、应用调试）共用；差异通过 props 控制显隐。
 */
const props = withDefaults(
  defineProps<{
    /** 输入文本（v-model） */
    modelValue: string
    /** 已上传图片 URL 列表（v-model:image-urls） */
    imageUrls: string[]
    /** 已上传附件文件列表（v-model:file-urls） */
    fileUrls?: ChatFileItem[]
    /** 输入框占位符 */
    placeholder?: string
    /** 发送按钮 loading（AI 回复生成中） */
    sending?: boolean
    /** 清空对话按钮 loading */
    clearLoading?: boolean
    /** 是否显示左侧清空对话按钮 */
    showClearButton?: boolean
    /** 是否显示图片上传（加号）按钮；为 false 时粘贴/拖拽图片同样禁用 */
    showImageButton?: boolean
    /** 是否支持普通文件（非图片）上传；为 false 时仅允许图片 */
    showFileButton?: boolean
    /** 是否显示语音转文字按钮 */
    showAudioRecorder?: boolean
    /** 是否显示底部"内容由AI生成…"提示 */
    showDisclaimer?: boolean
  }>(),
  {
    placeholder: '请输入消息...',
    sending: false,
    clearLoading: false,
    showClearButton: true,
    showImageButton: true,
    showFileButton: false,
    showAudioRecorder: true,
    showDisclaimer: true,
    fileUrls: () => [],
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:imageUrls': [urls: string[]]
  'update:fileUrls': [files: ChatFileItem[]]
  submit: []
  clear: []
}>()

const MAX_IMAGES = 5
const MAX_FILES = 5
/** 输入框最高高度，超出后内部滚动 */
const MAX_INPUT_HEIGHT = 160

const fileInput = ref<HTMLInputElement | null>(null)
const textareaEl = ref<HTMLTextAreaElement | null>(null)
const containerEl = ref<HTMLDivElement | null>(null)
const uploadFileLoading = ref(false)
/** 是否有文件拖入输入框（高亮遮罩） */
const dragOver = ref(false)

// 输入框固定为卡片形态：文本框独立一行，图标独立一行
const containerClass = 'rounded-2xl px-4 py-3'

// 文件选择器允许的类型：支持文件上传时附带常见文档格式
const fileAccept = computed(() =>
  props.showFileButton ? 'image/*,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.txt,.csv,.md' : 'image/*',
)

// 输入框高度自适应：单行 22px，多行自动长高，最高 MAX_INPUT_HEIGHT 后内部滚动
const autoResize = () => {
  const el = textareaEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, MAX_INPUT_HEIGHT)}px`
}

// 文件大小格式化：B / KB / MB
const formatSize = (size: number): string => {
  if (!size) return ''
  if (size < 1024) return `${size}B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)}KB`
  return `${(size / 1024 / 1024).toFixed(1)}MB`
}

// 点击上传按钮：附件数量未达上限时触发隐藏的 file input
const triggerFileInput = () => {
  const imageFull = props.imageUrls.length >= MAX_IMAGES
  const fileFull = props.showFileButton && props.fileUrls.length >= MAX_FILES
  if (imageFull && (!props.showFileButton || fileFull)) {
    Message.error('对话上传附件数量已达上限')
    return
  }
  fileInput.value?.click()
}

// 统一图片上传入口：一次处理多张图片（粘贴/拖拽/选择共用）
const uploadImageFiles = async (files: File[]) => {
  if (files.length === 0) return
  if (!props.showImageButton) {
    Message.warning('当前应用不支持图片上传')
    return
  }
  if (uploadFileLoading.value) {
    Message.info('图片上传中，请稍候')
    return
  }
  const remaining = MAX_IMAGES - props.imageUrls.length
  if (remaining <= 0) {
    Message.error('对话上传图片数量不能超过5张')
    return
  }
  const accepted = files.filter((file) => file.type.startsWith('image/')).slice(0, remaining)
  if (accepted.length === 0) return
  if (files.length > accepted.length) {
    Message.warning(`最多上传${MAX_IMAGES}张图片，已忽略多余文件`)
  }

  uploadFileLoading.value = true
  try {
    const newUrls: string[] = []
    for (const file of accepted) {
      const resp = await uploadImage(file)
      newUrls.push(resp.data.image_url)
    }
    if (newUrls.length > 0) {
      emit('update:imageUrls', [...props.imageUrls, ...newUrls])
      Message.success(`成功上传${newUrls.length}张图片`)
    }
  } catch {
    Message.error('图片上传失败')
  } finally {
    uploadFileLoading.value = false
  }
}

// 普通文件上传入口：上传后以附件卡片展示
const uploadOtherFiles = async (files: File[]) => {
  if (files.length === 0) return
  if (!props.showFileButton) {
    Message.warning('仅支持上传图片文件')
    return
  }
  if (uploadFileLoading.value) {
    Message.info('文件上传中，请稍候')
    return
  }
  const remaining = MAX_FILES - props.fileUrls.length
  if (remaining <= 0) {
    Message.error('对话上传文件数量不能超过5个')
    return
  }
  const accepted = files.slice(0, remaining)
  if (files.length > accepted.length) {
    Message.warning(`最多上传${MAX_FILES}个文件，已忽略多余文件`)
  }

  uploadFileLoading.value = true
  try {
    const newItems: ChatFileItem[] = []
    for (const file of accepted) {
      const resp = await uploadFile(file)
      newItems.push({
        id: resp.data.id,
        name: resp.data.name,
        size: resp.data.size,
        extension: resp.data.extension,
      })
    }
    if (newItems.length > 0) {
      emit('update:fileUrls', [...props.fileUrls, ...newItems])
      Message.success(`成功上传${newItems.length}个文件`)
    }
  } catch {
    Message.error('文件上传失败')
  } finally {
    uploadFileLoading.value = false
  }
}

// 按类型分流：图片走图片上传，其余走文件上传
const uploadFiles = async (files: File[]) => {
  const images = files.filter((file) => file.type.startsWith('image/'))
  const others = files.filter((file) => !file.type.startsWith('image/'))
  if (images.length > 0) await uploadImageFiles(images)
  if (others.length > 0) await uploadOtherFiles(others)
}

// 文件选择变化：复用统一上传逻辑；清空 input.value 以便重复选择同一文件
const handleFileChange = (event: Event) => {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  uploadFiles(files)
}

// Ctrl+V 粘贴：剪贴板含文件时按类型分流上传（图片→图片预览，文件→附件卡片），
// 剪贴板为纯文本时走默认文本粘贴
const handlePaste = (event: ClipboardEvent) => {
  const files = Array.from(event.clipboardData?.files ?? [])
  if (files.length === 0) return
  event.preventDefault()
  uploadFiles(files)
}

// 拖拽上传：进入/离开切换高亮遮罩，松手后按类型分流上传
const handleDragEnter = (event: DragEvent) => {
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
  dragOver.value = true
}
const handleDragOver = (event: DragEvent) => {
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
}
const handleDragLeave = (event: DragEvent) => {
  const related = event.relatedTarget as Node | null
  if (!containerEl.value || !containerEl.value.contains(related)) {
    dragOver.value = false
  }
}
const handleDrop = (event: DragEvent) => {
  event.preventDefault()
  dragOver.value = false
  const files = Array.from(event.dataTransfer?.files ?? [])
  uploadFiles(files)
}

// 全局阻止 dragover 默认行为：避免文件拖到页面其它区域时浏览器直接打开文件
const preventGlobalDragOver = (event: DragEvent) => event.preventDefault()

const handleInput = (event: Event) => {
  emit('update:modelValue', (event.target as HTMLTextAreaElement).value)
  autoResize()
}

// 回车发送，Shift+回车换行；中文输入法组词确认（Enter）时不触发发送
const handleKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    if (!props.sending) emit('submit')
  }
}

// 删除预览中的某张图片
const removeImage = (index: number) => {
  const next = props.imageUrls.slice()
  next.splice(index, 1)
  emit('update:imageUrls', next)
}

// 删除某个附件文件
const removeFile = (index: number) => {
  const next = props.fileUrls.slice()
  next.splice(index, 1)
  emit('update:fileUrls', next)
}

// 外部清空/回填文本或移除附件后，同步输入框高度与形态
watch(
  () => props.modelValue,
  () => nextTick(autoResize),
)
watch(
  () => props.imageUrls.length + props.fileUrls.length,
  () => nextTick(autoResize),
)

onMounted(() => {
  document.addEventListener('dragover', preventGlobalDragOver)
  nextTick(autoResize)
})
onUnmounted(() => {
  document.removeEventListener('dragover', preventGlobalDragOver)
})
</script>

<template>
  <div class="flex flex-col w-full">
    <div
      ref="containerEl"
      :class="[
        'relative flex flex-col border border-gray-200 bg-white transition-[border-radius] duration-300',
        containerClass,
      ]"
      @dragenter="handleDragEnter"
      @dragover="handleDragOver"
      @dragleave="handleDragLeave"
      @drop="handleDrop"
    >
      <div
        v-if="dragOver"
        class="absolute inset-0 z-10 border-2 border-dashed border-blue-500 bg-blue-50/90 flex items-center justify-center pointer-events-none rounded-2xl"
      >
        <div class="flex items-center gap-2 text-blue-600 text-sm">
          <icon-upload :size="18" />
          <span>松开上传{{ showFileButton ? '文件' : '图片' }}</span>
        </div>
      </div>
      <div v-if="imageUrls.length > 0" class="flex items-center gap-2 mb-2 px-1">
        <div
          v-for="(image_url, idx) in imageUrls"
          :key="image_url"
          class="w-12 h-12 relative rounded-lg overflow-hidden group cursor-pointer border border-gray-100"
        >
          <a-avatar shape="square" :image-url="image_url" class="!w-full !h-full" />
          <div
            class="hidden group-hover:flex items-center justify-center bg-gray-900/50 w-full h-full absolute top-0 left-0 transition-all"
          >
            <icon-close class="!text-white" @click="removeImage(idx)" />
          </div>
        </div>
      </div>
      <div v-if="fileUrls.length > 0" class="flex items-center flex-wrap gap-2 mb-2 px-1">
        <div
          v-for="(file, idx) in fileUrls"
          :key="file.id"
          class="flex items-center gap-1.5 h-8 px-2 rounded-lg bg-gray-100 border border-gray-200 text-xs text-gray-700"
        >
          <icon-file :size="14" class="flex-shrink-0" />
          <span class="max-w-[140px] truncate">{{ file.name }}</span>
          <span class="text-gray-400 flex-shrink-0">{{ formatSize(file.size) }}</span>
          <icon-close
            :size="12"
            class="!text-gray-400 hover:!text-red-500 cursor-pointer flex-shrink-0"
            @click="removeFile(idx)"
          />
        </div>
      </div>
      <textarea
        ref="textareaEl"
        :value="modelValue"
        rows="1"
        :placeholder="placeholder"
        class="w-full resize-none overflow-y-auto leading-[22px] min-h-[22px] max-h-[160px] outline-0 bg-transparent border-none focus:border-none focus:ring-0 focus:outline-none text-gray-700 placeholder-gray-400"
        @input="handleInput"
        @keydown="handleKeydown"
        @paste="handlePaste"
        @dragenter="handleDragEnter"
        @dragover="handleDragOver"
        @dragleave="handleDragLeave"
        @drop="handleDrop"
      />
      <input
        type="file"
        ref="fileInput"
        :accept="fileAccept"
        @change="handleFileChange"
        class="hidden"
      />
      <div class="flex items-center gap-2 pt-2">
        <a-tooltip v-if="showClearButton" content="清空对话">
          <a-button
            :loading="clearLoading"
            @click="emit('clear')"
            class="flex-shrink-0 !text-gray-700"
            type="text"
            shape="circle"
            aria-label="清空对话"
          >
            <template #icon><icon-empty :size="16" /></template>
          </a-button>
        </a-tooltip>
        <div class="flex items-center gap-2 ml-auto">
          <a-tooltip
            v-if="showImageButton"
            :content="showFileButton ? '上传图片/文件' : '上传图片'"
          >
            <a-button
              :loading="uploadFileLoading"
              type="text"
              shape="circle"
              class="!text-gray-500 hover:!text-gray-700"
              aria-label="上传图片"
              @click="triggerFileInput"
            >
              <template #icon><icon-plus :size="16" /></template>
            </a-button>
          </a-tooltip>
          <!-- 语音转文字按钮：识别结果直接回填输入框 -->
          <audio-recorder
            v-if="showAudioRecorder"
            @transcribed="(text: string) => emit('update:modelValue', text)"
          />
          <a-tooltip content="发送">
            <!-- 注意：不用 Arco 的 :loading 属性——loading 状态下 Arco 会在组件内部
                 拦截点击（emit('submit') 不触发），用户点发送毫无反应。改为自定义
                 loading 图标，按钮始终保持可点击：sending 中点击由父级 sendChat
                 弹出"上一次提问还未结束"提示，而不是静默失效。 -->
            <a-button
              type="text"
              shape="circle"
              class="!text-blue-600 hover:!bg-blue-50"
              aria-label="发送"
              @click="emit('submit')"
            >
              <template #icon>
                <icon-loading v-if="sending" :size="16" />
                <icon-send v-else :size="16" />
              </template>
            </a-button>
          </a-tooltip>
        </div>
      </div>
    </div>
    <div v-if="showDisclaimer" class="text-center text-gray-400 text-xs py-3">
      内容由AI生成，无法确保真实准确，仅供参考。
    </div>
  </div>
</template>
