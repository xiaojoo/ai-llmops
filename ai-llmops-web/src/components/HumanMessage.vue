<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { getUploadFileUrl } from '@/services/upload-file.ts'
import type { ChatFileItem } from '@/models/chat-file.ts'

const props = defineProps({
  account: {
    type: Object,
    default: () => {
      return {}
    },
    required: true,
  },
  query: { type: String, default: '', required: true },
  image_urls: { type: Array, default: () => [] },
  file_urls: { type: Array as () => ChatFileItem[], default: () => [] },
  /**
   * 可选。由父级接管编辑态（虚拟列表里组件会被复用/重建，本地状态会丢）。
   * 传了就用父级值；不传则回退到本地状态（原行为）。
   */
  editing: { type: Boolean, default: undefined },
})

const emit = defineEmits<{
  'submit-edit': [text: string]
  'edit-start': []
  'edit-cancel': []
}>()

// ===== 文件大小格式化：B / KB / MB =====
const formatSize = (size: number): string => {
  if (!size) return ''
  if (size < 1024) return `${size}B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)}KB`
  return `${(size / 1024 / 1024).toFixed(1)}MB`
}

// ===== 复制发送的用户输入文本 =====
const contentCopied = ref(false)
const copyQuery = async () => {
  try {
    await navigator.clipboard.writeText(props.query)
    contentCopied.value = true
    setTimeout(() => {
      contentCopied.value = false
    }, 2000)
  } catch {
    /* 忽略剪贴板失败 */
  }
}

// ===== 编辑用户消息：点击"编辑"后内容框变为可输入状态，发送后重新生成 =====
// 编辑态默认本地持有；父级传 editing 时由父级接管（避免虚拟列表复用/重建丢状态）。
const localEditing = ref(false)
const isEditing = computed(() => (props.editing === undefined ? localEditing.value : props.editing))
const editDraft = ref('')
const editRef = ref<HTMLTextAreaElement | null>(null)

const startEdit = () => {
  if (props.editing === undefined) localEditing.value = true
  editDraft.value = props.query
  emit('edit-start')
}

const cancelEdit = () => {
  if (props.editing === undefined) localEditing.value = false
  editDraft.value = ''
  emit('edit-cancel')
}

const submitEdit = () => {
  const text = editDraft.value.trim()
  if (!text) return
  if (props.editing === undefined) localEditing.value = false
  emit('submit-edit', text)
}

// 进入编辑态即聚焦（含虚拟列表复用/重建后重新挂载的情形），并把光标放到末尾
const focusEdit = () => {
  nextTick(() => {
    const el = editRef.value
    if (el) {
      el.focus()
      el.setSelectionRange(el.value.length, el.value.length)
    }
  })
}
watch(isEditing, (v) => {
  if (v) focusEdit()
})
onMounted(() => {
  if (isEditing.value) focusEdit()
})

// 点击附件卡片：先向后端取最新的可访问 URL（历史附件预签名链接可能已过期），
// 再新标签页打开。用 window.open 而非 <a href>：避免扩展对 href 的 HEAD 探测 403 刷屏。
const openFile = async (file: ChatFileItem) => {
  let url = file.url
  try {
    if (file.id) {
      const resp = await getUploadFileUrl(file.id)
      if (resp.data?.url) url = resp.data.url
    }
  } catch {
    // 刷新失败时回退到记录里的 URL（可能仍可用）
  }
  if (url) {
    window.open(url, '_blank', 'noopener')
  } else {
    Message.error('文件链接不可用')
  }
}
</script>

<template>
  <div class="flex gap-2 flex-row-reverse">
    <a-avatar :size="30" shape="circle" class="shrink-0" :image-url="props.account?.avatar" />
    <div class="flex flex-col items-end gap-2 w-[calc(100%-38px)]">
      <div class="text-gray-700 font-bold">
        {{ props.account?.name }}
      </div>

      <!-- 编辑态：内容框变为可输入，含取消/发送 -->
      <div v-if="isEditing" class="w-full max-w-[calc(100%-38px)]">
        <textarea
          ref="editRef"
          v-model="editDraft"
          class="w-full resize-y border border-gray-200 rounded-2xl bg-white text-gray-700 px-4 py-3 outline-none focus:border-blue-400 text-sm leading-6 wrap-break-word max-h-[180px]"
          placeholder="修改内容..."
          rows="3"
          spellcheck="false"
          @keydown.enter.exact.prevent="submitEdit"
          @keydown.esc="cancelEdit"
        />
        <div class="flex items-center justify-between mt-2">
          <span class="text-xs text-gray-400">编辑消息</span>
          <div class="flex items-center gap-2">
            <a-button type="text" size="mini" @click="cancelEdit">取消</a-button>
            <a-button type="primary" size="mini" @click="submitEdit">发送</a-button>
          </div>
        </div>
      </div>

      <!-- 展示态：气泡 + 复制/编辑 -->
      <template v-else>
        <div
          class="bg-blue-100 border border-blue-200 text-gray-700 px-4 py-3 rounded-2xl wrap-break-word max-w-[calc(100%-38px)]"
        >
          <a-image
            v-for="(image_url, idx) in props.image_urls"
            :key="idx"
            class="cursor-pointer mb-2 max-w-full"
            :src="String(image_url)"
          />
          <div v-if="props.file_urls.length > 0" class="flex items-center flex-wrap gap-2 mb-2">
            <button
              v-for="file in props.file_urls"
              :key="file.id"
              type="button"
              class="flex items-center gap-1.5 h-8 px-2 rounded-lg bg-white border border-blue-200 text-xs text-gray-700 hover:border-blue-400 cursor-pointer"
              @click="openFile(file)"
            >
              <icon-file :size="14" class="shrink-0" />
              <span class="max-w-[160px] truncate">{{ file.name }}</span>
              <span class="text-gray-400 shrink-0">{{ formatSize(file.size) }}</span>
            </button>
          </div>
          <div class="whitespace-pre-wrap wrap-break-word">{{ props.query }}</div>
        </div>
        <div class="flex items-center gap-1 -mt-0.5">
          <a-tooltip content="编辑">
            <icon-edit
              :size="25"
              class="rounded-full p-1 !text-gray-400 hover:bg-gray-100 hover:!text-gray-600 transition cursor-pointer"
              @click="startEdit"
            />
          </a-tooltip>
          <a-tooltip :content="contentCopied ? '已复制' : '复制'">
            <icon-copy
              v-if="!contentCopied"
              :size="25"
              class="rounded-full p-1 !text-gray-400 hover:bg-gray-100 hover:!text-gray-600 transition cursor-pointer"
              @click="copyQuery"
            />
            <icon-check v-else :size="25" class="rounded-full p-1 !text-green-600" />
          </a-tooltip>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped></style>
