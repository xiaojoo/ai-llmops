<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import type { ChromaFileItem } from '@/models/chroma.ts'
import {
  deleteChromaFile,
  downloadChromaFile,
  getChromaFiles,
  uploadChromaFile,
} from '@/services/chroma.ts'

const fileList = ref<ChromaFileItem[]>([])
const loadingFiles = ref(false)
const uploading = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const dragOver = ref(false)
const deleting = ref<string | null>(null)

// 格式化文件大小
const formatSize = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

// 获取文件图标
const getFileIcon = (name: string) => {
  const ext = name.split('.').pop()?.toLowerCase()
  const icons: Record<string, string> = {
    pdf: 'icon-file-pdf',
    doc: 'icon-file',
    docx: 'icon-file',
    txt: 'icon-file',
    md: 'icon-file',
    csv: 'icon-file',
    xlsx: 'icon-file',
    xls: 'icon-file',
    json: 'icon-code',
    py: 'icon-code',
    js: 'icon-code',
    ts: 'icon-code',
    png: 'icon-image',
    jpg: 'icon-image',
    jpeg: 'icon-image',
    gif: 'icon-image',
  }
  return icons[ext || ''] || 'icon-file'
}

// 获取文件列表
const fetchFiles = async () => {
  loadingFiles.value = true
  try {
    const resp = await getChromaFiles()
    fileList.value = resp.data?.files ?? []
  } catch {
    Message.error('获取文件列表失败')
  } finally {
    loadingFiles.value = false
  }
}

// 上传文件
const uploadFile = async (file: File) => {
  if (uploading.value) return
  uploading.value = true
  try {
    await uploadChromaFile(file)
    Message.success(`${file.name} 上传成功`)
    await fetchFiles()
  } catch {
    Message.error(`${file.name} 上传失败`)
  } finally {
    uploading.value = false
  }
}

// 触发文件选择
const triggerUpload = () => fileInput.value?.click()

// 文件选择回调
const handleFileChange = async (e: Event) => {
  const files = (e.target as HTMLInputElement).files
  if (!files?.length) return
  for (const file of Array.from(files)) await uploadFile(file)
  if (fileInput.value) fileInput.value.value = ''
}

// 拖拽上传
const handleDrop = async (e: DragEvent) => {
  dragOver.value = false
  const files = e.dataTransfer?.files
  if (!files?.length) return
  for (const file of Array.from(files)) await uploadFile(file)
}

// 下载文件
const downloadFile = async (path: string, name: string) => {
  try {
    const blob = await downloadChromaFile(path)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = name
    a.click()
    URL.revokeObjectURL(url)
  } catch {
    Message.error(`下载 ${name} 失败`)
  }
}

// 删除文件
const deleteFile = async (path: string, name: string) => {
  deleting.value = path
  try {
    await deleteChromaFile({ path })
    Message.success(`${name} 已删除`)
    await fetchFiles()
  } catch {
    Message.error(`删除 ${name} 失败`)
  } finally {
    deleting.value = null
  }
}

onMounted(fetchFiles)
</script>

<template>
  <div class="flex flex-col gap-4">
    <!-- 上传区域 -->
    <div
      class="border-2 border-dashed rounded-lg p-8 flex flex-col items-center justify-center gap-3 transition-colors cursor-pointer"
      :class="
        dragOver
          ? 'border-blue-400 bg-blue-50'
          : 'border-gray-200 bg-gray-50 hover:border-blue-300 hover:bg-blue-50/50'
      "
      @click="triggerUpload"
      @dragover.prevent="dragOver = true"
      @dragleave="dragOver = false"
      @drop.prevent="handleDrop"
    >
      <div class="w-12 h-12 rounded-full bg-blue-100 flex items-center justify-center">
        <icon-upload class="!text-blue-500 text-xl" />
      </div>
      <div class="text-center">
        <div class="text-sm font-medium text-gray-700">
          {{ uploading ? '上传中...' : '点击或拖拽文件到此处上传' }}
        </div>
        <div class="text-xs text-gray-400 mt-1">
          支持 txt / md / pdf / docx / csv / xlsx，上传后自动分段向量化
        </div>
      </div>
      <a-button type="primary" size="small" :loading="uploading" @click.stop="triggerUpload">
        选择文件
      </a-button>
    </div>
    <input ref="fileInput" type="file" multiple class="hidden" @change="handleFileChange" />

    <!-- 文件列表 -->
    <div class="border border-gray-200 rounded-lg bg-white overflow-hidden">
      <div class="flex items-center justify-between px-4 py-3 bg-gray-50 border-b border-gray-200">
        <div class="text-sm font-semibold text-gray-700">
          服务器文件
          <span class="ml-2 text-xs font-normal text-gray-400">{{ fileList.length }} 个文件</span>
        </div>
        <a-button size="mini" type="text" :loading="loadingFiles" @click="fetchFiles">
          <template #icon><icon-refresh /></template>
          刷新
        </a-button>
      </div>

      <!-- 加载中 -->
      <div v-if="loadingFiles" class="flex items-center justify-center py-4">
        <a-spin />
      </div>

      <!-- 空状态 -->
      <div
        v-else-if="fileList.length === 0"
        class="flex flex-col items-center justify-center text-gray-400"
      >
        <icon-folder class="mt-1.5 text-4xl" />
        <div class="text-sm">暂无文件</div>
      </div>

      <!-- 文件列表 -->
      <div v-else class="divide-y divide-gray-100">
        <div
          v-for="file in fileList"
          :key="file.path"
          class="flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-colors group"
        >
          <!-- 文件图标 -->
          <div class="w-8 h-8 rounded bg-blue-50 flex items-center justify-center shrink-0">
            <component :is="getFileIcon(file.name)" class="text-blue-500 text-sm" />
          </div>

          <!-- 文件信息 -->
          <div class="flex-1 min-w-0">
            <div class="text-sm text-gray-700 truncate font-medium">{{ file.name }}</div>
            <div class="text-xs text-gray-400 mt-0.5">
              {{ formatSize(file.size) }}
              <span class="mx-1">·</span>
              {{ file.modified }}
            </div>
          </div>

          <div class="flex items-center gap-1">
            <a-tooltip content="下载">
              <a-button aria-label="下载" size="mini" type="text" @click="downloadFile(file.path, file.name)">
                <template #icon><icon-download /></template>
              </a-button>
            </a-tooltip>
            <a-popconfirm
              content="确认删除该文件？"
              position="left"
              type="error"
              @ok="deleteFile(file.path, file.name)"
            >
              <a-button aria-label="删除"
                size="mini"
                type="text"
                class="!text-red-400 hover:!text-red-600"
                :loading="deleting === file.path"
              >
                <template #icon><icon-delete /></template>
              </a-button>
            </a-popconfirm>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
