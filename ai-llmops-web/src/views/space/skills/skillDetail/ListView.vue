<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { downloadSkill, getSkills } from '@/services/skill.ts'
import { Message } from '@arco-design/web-vue'
import MarkdownIt from 'markdown-it'
import 'github-markdown-css/github-markdown.css'
import type { SkillFile } from '@/models/skill.ts'
import FileTreeNode from './components/FileTreeNode.vue'

const route = useRoute()
const router = useRouter()
const skillId = route.params.skill_id as string
const md = new MarkdownIt({ html: true, linkify: true, typographer: true })

const loading = ref(false)
const selectedFile = ref<SkillFile | null>(null)
const viewMode = ref<'md' | 'code'>('code')
const downloadLoading = ref(false)

const skillDetail = reactive<{
  id: string
  name: string
  description: string
  icon: string
  files: SkillFile[]
  created_at: number
  updated_at: number
}>({
  id: '',
  name: '',
  description: '',
  icon: '',
  files: [],
  created_at: 0,
  updated_at: 0,
})

// 目录树结构：目录为嵌套子树，文件叶子节点为 { __file: SkillFile }
interface FileTree {
  [key: string]: FileTree | { __file: SkillFile }
}

// 构建目录树
const fileTree = computed(() => {
  const tree: FileTree = {}
  for (const file of skillDetail.files) {
    const parts = file.path.replace(/\\/g, '/').split('/')
    let node: FileTree = tree
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i] as string
      if (i === parts.length - 1) {
        node[part] = { __file: file }
      } else {
        if (!node[part]) node[part] = {}
        node = node[part] as FileTree
      }
    }
  }
  return tree
})

// 面包屑路径
const breadcrumbs = computed(() => {
  if (!selectedFile.value) return [skillDetail.name]
  const parts = selectedFile.value.path.replace(/\\/g, '/').split('/')
  return [skillDetail.name, ...parts]
})

const renderedMd = computed(() => {
  if (!selectedFile.value?.content) return ''
  return md.render(selectedFile.value.content)
})

const lineCount = computed(() => {
  if (!selectedFile.value?.content) return 0
  return selectedFile.value.content.split('\n').length
})

const fileSize = computed(() => {
  if (!selectedFile.value?.content) return '0 B'
  const bytes = new Blob([selectedFile.value.content]).size
  if (bytes < 1024) return `${bytes} B`
  return `${(bytes / 1024).toFixed(1)} KB`
})

const handleSelectFile = (file: SkillFile) => {
  selectedFile.value = file
  viewMode.value = file.path.endsWith('.md') ? 'md' : 'code'
}

const handleBack = () => {
  selectedFile.value = null
}

const loadDetail = async () => {
  try {
    loading.value = true
    const resp = await getSkills(skillId)
    const data = resp.data
    skillDetail.id = data.id
    skillDetail.name = data.name
    skillDetail.description = data.description
    skillDetail.icon = data.icon
    skillDetail.files = data.files
    skillDetail.created_at = data.created_at
    skillDetail.updated_at = data.updated_at
    // 默认选中 SKILL.md（兼容 zip 集合包：入口可能在子目录，回退到第一个 .md）
    const skillMd = data.files.find((f: SkillFile) => f.path === 'SKILL.md')
    if (skillMd) {
      handleSelectFile(skillMd)
    } else {
      const firstMd = data.files.find((f: SkillFile) => f.path.endsWith('.md'))
      if (firstMd) handleSelectFile(firstMd)
    }
  } finally {
    loading.value = false
  }
}

// 获取节点下所有 key（文件夹展开）
const expandedKeys = ref<string[]>([])
const toggleDir = (key: string) => {
  const idx = expandedKeys.value.indexOf(key)
  if (idx === -1) expandedKeys.value.push(key)
  else expandedKeys.value.splice(idx, 1)
}

const handleCopy = async () => {
  if (!selectedFile.value?.content) return
  try {
    await navigator.clipboard.writeText(selectedFile.value.content)
    Message.success('已复制到剪贴板')
  } catch {
    Message.error('复制失败')
  }
}

const handleDownload = async () => {
  try {
    downloadLoading.value = true
    const blob = await downloadSkill(skillId)
    const url = URL.createObjectURL(blob as Blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${skillDetail.name}.zip`
    link.click()
    URL.revokeObjectURL(url)
  } catch {
    Message.error('下载失败')
  } finally {
    downloadLoading.value = false
  }
}

onMounted(() => loadDetail())
</script>

<template>
  <a-spin :loading="loading" class="w-full h-full">
    <div class="flex flex-col h-full bg-white">
      <!-- 顶部导航 -->
      <div class="flex items-center justify-between px-2 py-3 border-b border-gray-200">
        <div class="flex items-center gap-2 text-sm">
          <a-button aria-label="返回" type="text" size="small" class="!text-gray-500 !px-1" @click="router.back()">
            <template #icon><icon-left /></template>
          </a-button>
          <!-- 面包屑 -->
          <span v-for="(crumb, idx) in breadcrumbs" :key="idx" class="flex items-center gap-1">
            <span class="text-gray-400" v-if="idx > 0">/</span>
            <span
              :class="
                idx === breadcrumbs.length - 1
                  ? 'text-gray-900 font-semibold'
                  : 'text-blue-600 cursor-pointer hover:underline'
              "
              @click="idx === 0 ? handleBack() : undefined"
              >{{ crumb }}</span
            >
          </span>
        </div>
      </div>

      <!-- 主体 -->
      <div class="flex flex-1 overflow-hidden">
        <!-- 左侧文件树 -->
        <div class="w-56 border-r border-gray-200 overflow-y-auto shrink-0">
          <div class="p-2">
            <file-tree-node
              :tree="fileTree"
              :selected-path="selectedFile?.path"
              :expanded-keys="expandedKeys"
              @select="handleSelectFile"
              @toggle="toggleDir"
            />
          </div>
        </div>

        <!-- 右侧内容区 -->
        <div class="flex-1 overflow-y-auto">
          <template v-if="selectedFile">
            <!-- 文件信息栏 -->
            <div
              class="sticky top-0 z-10 flex items-center justify-between px-4 py-2 border-b border-gray-200 bg-gray-50 text-xs text-gray-500"
            >
              <div class="flex items-center gap-3">
                <span>{{ lineCount }} lines</span>
                <span>{{ fileSize }}</span>
              </div>
              <div class="flex items-center gap-2">
                <!-- 下载按钮 -->
                <a-tooltip content="下载全部文件">
                  <a-button aria-label="下载"
                    type="text"
                    size="mini"
                    class="!text-gray-500 hover:!text-gray-900"
                    :loading="downloadLoading"
                    @click="handleDownload"
                  >
                    <template #icon><icon-download /></template>
                  </a-button>
                </a-tooltip>
                <!-- 复制按钮 -->
                <a-tooltip content="复制内容">
                  <a-button aria-label="复制"
                    type="text"
                    size="mini"
                    class="!text-gray-500 hover:!text-gray-900"
                    @click="handleCopy"
                  >
                    <template #icon><icon-copy /></template>
                  </a-button>
                </a-tooltip>
                <a-radio-group
                  v-if="selectedFile.path.endsWith('.md')"
                  v-model="viewMode"
                  type="button"
                  size="mini"
                >
                  <a-radio value="md">预览</a-radio>
                  <a-radio value="code">源码</a-radio>
                </a-radio-group>
              </div>
            </div>

            <!-- 文件内容 -->
            <div v-if="selectedFile.is_binary" class="p-8 text-center text-gray-400">
              二进制文件，无法预览
            </div>
            <template v-else>
              <!-- MD 预览 -->
              <div v-if="viewMode === 'md'" class="markdown-body p-6" v-html="renderedMd" />
              <!-- 源码，带行号 -->
              <div v-else class="flex text-xs font-mono bg-white">
                <!-- 行号 -->
                <div
                  class="select-none text-right text-gray-400 px-3 py-4 border-r border-gray-100 leading-5 bg-gray-50"
                >
                  <div v-for="n in lineCount" :key="n" class="leading-5">{{ n }}</div>
                </div>
                <!-- 代码 -->
                <pre
                  class="flex-1 m-0 p-4 leading-5 whitespace-pre-wrap wrap-break-word overflow-x-auto text-gray-800"
                  >{{ selectedFile.content?.trim() }}</pre
                >
              </div>
            </template>
          </template>

          <!-- 未选中文件时显示 README -->
          <div v-else class="p-6 text-gray-400 text-sm text-center mt-20">请从左侧选择文件查看</div>
        </div>
      </div>
    </div>
  </a-spin>
</template>
