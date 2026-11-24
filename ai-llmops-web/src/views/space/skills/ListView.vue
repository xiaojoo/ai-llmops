<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import {
  deleteSkill,
  getSkill,
  getSkillListWithPage,
  toggleSkillVisibility,
  uploadSkill,
} from '@/services/skill.ts'
import { useRoute, useRouter } from 'vue-router'
import moment from 'moment'
import { Message, Modal, type FileItem, type RequestOption, type UploadRequest } from '@arco-design/web-vue'
import { showErrorToast } from '@/utils/http/error'
import MarkdownIt from 'markdown-it'
import 'github-markdown-css/github-markdown.css'
import { uploadImage } from '@/services/upload-file.ts'
import { RouteNames } from '@/router/routes.ts'
import type { GetSkillListWithPageResponse } from '@/models/skill.ts'

const route = useRoute()
const router = useRouter()
const props = defineProps({
  createType: {
    type: String,
    required: true,
  },
})
const emits = defineEmits(['update-create-type'])
type SkillListItem = GetSkillListWithPageResponse['data']['list'][number]
const skills = reactive<SkillListItem[]>([])
const paginator = reactive({
  current_page: 1,
  page_size: 20,
  total_page: 0,
  total_record: 0,
})

const loading = ref<boolean>(false)
const uploadLoading = ref<boolean>(false)
const showModal = ref<boolean>(false)
const detailLoading = ref<boolean>(false)

// 当前选中的技能详情
const skillDetail = reactive<{
  id: string
  name: string
  description: string
  icon: string
  visibility: string
  is_owner: boolean
  file_content: string | null
  created_at: number
  updated_at: number
}>({
  id: '',
  name: '',
  description: '',
  icon: '',
  visibility: 'private',
  is_owner: false,
  file_content: null,
  created_at: 0,
  updated_at: 0,
})

const form = reactive<{
  icon: string
  file: File | null
  fileList: FileItem[]
}>({
  icon: '',
  file: null,
  fileList: [],
})

// 显示模式：code | md
const viewMode = ref<'code' | 'md'>('md')

const md = new MarkdownIt({ html: true, linkify: true, typographer: true })

const renderedMd = computed(() => {
  if (!skillDetail.file_content) return ''
  return md.render(skillDetail.file_content)
})

const searchWord = computed(() => {
  return Array.isArray(route.query.search_word)
    ? (route.query.search_word[0] ?? '')
    : (route.query.search_word ?? '')
})

// ─── 加载列表 ────
const loadMoreData = async (init: boolean = false) => {
  if (!init && paginator.current_page > paginator.total_page) return
  try {
    loading.value = true
    const resp = await getSkillListWithPage({
      current_page: paginator.current_page,
      page_size: paginator.page_size,
      search_word: searchWord.value,
    })
    const data = resp.data
    paginator.current_page = data.paginator.current_page
    paginator.page_size = data.paginator.page_size
    paginator.total_page = data.paginator.total_page
    paginator.total_record = data.paginator.total_record
    if (paginator.current_page <= paginator.total_page) {
      paginator.current_page += 1
    }
    if (init) {
      skills.splice(0, skills.length, ...data.list)
    } else {
      skills.push(...data.list)
    }
  } finally {
    loading.value = false
  }
}

const initData = async () => {
  paginator.current_page = 1
  paginator.page_size = 20
  paginator.total_page = 0
  paginator.total_record = 0
  await loadMoreData(true)
}

const handleScroll = (event: UIEvent) => {
  const { scrollTop, scrollHeight, clientHeight } = event.target as HTMLElement
  if (scrollTop + clientHeight >= scrollHeight - 10) {
    if (loading.value) return
    loadMoreData()
  }
}

// ─── 点击卡片打开 Modal ────
const handleShowDetail = async (skill_id: string) => {
  showModal.value = true
  viewMode.value = 'md'
  try {
    detailLoading.value = true
    // 归属信息从列表项获取（避免额外请求）
    const listItem = skills.find((s) => s.id === skill_id)
    const resp = await getSkill(skill_id)
    const data = resp.data
    skillDetail.id = data.id
    skillDetail.name = data.name
    skillDetail.description = data.description
    skillDetail.icon = data.icon
    skillDetail.visibility = data.visibility
    skillDetail.is_owner = listItem?.is_owner ?? false
    skillDetail.file_content = data.file_content
    skillDetail.created_at = data.created_at
    skillDetail.updated_at = data.updated_at
  } finally {
    detailLoading.value = false
  }
}

const handleCancel = () => {
  showModal.value = false
}

// ─── 切换可见性（独占 <-> 分享） ────
const handleToggleVisibility = async (skill_id: string) => {
  try {
    const resp = await toggleSkillVisibility(skill_id)
    Message.success(resp.message)
    await initData()
  } catch (err) {
    showErrorToast((err as Error).message || '切换失败')
  }
}

// ─── 删除 ────
const handleDelete = (skill_id: string) => {
  Modal.warning({
    title: '确认删除这个技能？',
    content: '删除技能是不可逆的，AI应用将无法访问该技能',
    hideCancel: false,
    onOk: async () => {
      try {
        const resp = await deleteSkill(skill_id)
        Message.success(resp.message)
      } finally {
        showModal.value = false
        await initData()
      }
    },
  })
}

// a-upload 的 custom-request 需同步返回 UploadRequest（{ abort }），异步逻辑在内部任务中执行
const handleIconUpload = (option: RequestOption): UploadRequest => {
  const { fileItem, onSuccess, onError } = option

  const uploadTask = async () => {
    try {
      const uploadResp = await uploadImage(fileItem.file as File)
      form.icon = uploadResp.data.image_url
      onSuccess(uploadResp)
    } catch (err) {
      onError?.(err)
      Message.error('图标上传失败')
    }
  }
  uploadTask()

  return { abort: () => {} }
}

const handleSubmit = async () => {
  if (uploadLoading.value) return // 防重复

  if (!form.file) {
    Message.warning('请选择要上传的技能文件')
    return
  }
  try {
    uploadLoading.value = true
    const resp = await uploadSkill(form.file, form.icon)
    Message.success(resp.message)
    handleCancel()
    await initData()
  } finally {
    uploadLoading.value = false
  }
}

const handleCancelUpload = () => {
  Message.clear() // 清掉残留的 message
  form.icon = ''
  form.file = null
  form.fileList = []
  emits('update-create-type', '')
}
const fileInputRef = ref<HTMLInputElement | null>(null)
const isDragging = ref(false)

const triggerFileInput = () => {
  fileInputRef.value?.click()
}

const handleFileChange = (e: Event) => {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) {
    form.file = file
  }
  // 清空 input，允许重复选同一文件
  input.value = ''
}

const handleDrop = (e: DragEvent) => {
  isDragging.value = false
  const file = e.dataTransfer?.files?.[0]
  if (!file) return
  const ext = file.name.split('.').pop()?.toLowerCase()
  if (!['md', 'zip'].includes(ext ?? '')) {
    Message.error('仅支持 .md 或 .zip 文件')
    return
  }
  form.file = file
}

const handleDetail = (skill_id: string) => {
  router.push({ name: RouteNames.SPACE_SKILLS_DETAIL, params: { skill_id: skill_id } })
}

onMounted(async () => {
  await loadMoreData(true)
})

watch(searchWord, () => {
  initData()
})
</script>

<template>
  <a-spin
    :loading="loading"
    class="h-full w-full scrollbar-w-none overflow-scroll"
    @scroll="handleScroll"
  >
    <!-- 列表 -->
    <a-row :gutter="[20, 20]" class="flex-1">
      <a-col
        v-for="skill in skills"
        :key="skill.id"
        :xs="24"
        :sm="12"
        :md="8"
        :lg="6"
        :xl="6"
        :xxl="6"
      >
        <a-card hoverable class="cursor-pointer rounded-lg" @click="handleShowDetail(skill.id)">
          <div class="flex items-center justify-between gap-3 mb-3">
            <div class="flex items-center gap-3 min-w-0">
              <a-avatar
                v-if="skill.icon"
                :size="40"
                shape="square"
                class="bg-blue-600 shrink-0"
                :image-url="skill.icon"
              />
              <a-avatar v-else :size="40" shape="square" class="bg-blue-600 shrink-0">
                <icon-code />
              </a-avatar>
              <div class="flex flex-col gap-0.5 min-w-0">
                <div class="flex items-center gap-2 min-w-0">
                  <!-- 名称超长时截断显示省略号，不撑出卡片 -->
                  <div class="text-base text-gray-900 font-bold line-clamp-1 min-w-0 flex-1">
                    {{ skill.name }}
                  </div>
                  <a-tag
                    :color="skill.visibility === 'public' ? 'green' : 'gray'"
                    size="small"
                    class="shrink-0"
                  >
                    {{ skill.visibility === 'public' ? '公共' : '独占' }}
                  </a-tag>
                </div>
              </div>
            </div>
            <!-- 操作按钮：仅归属者可删除/切换可见性 -->
            <a-dropdown
              v-if="skill.is_owner"
              position="br"
              class="shrink-0"
              @click.stop
            >
              <a-button aria-label="更多操作" type="text" size="small" class="rounded-lg text-gray-700">
                <template #icon>
                  <icon-more />
                </template>
              </a-button>
              <template #content>
                <a-doption @click="handleToggleVisibility(skill.id)">
                  {{ skill.visibility === 'public' ? '改为独占' : '设为公共' }}
                </a-doption>
                <a-doption @click="handleDelete(skill.id)">删除</a-doption>
              </template>
            </a-dropdown>
          </div>
          <div class="leading-[18px] text-gray-500 h-[72px] line-clamp-4 mb-2">
            {{ skill.description }}
          </div>
          <div class="flex items-center gap-1.5">
            <a-avatar :size="18" class="bg-blue-700"><icon-user /></a-avatar>
            <div class="text-xs text-gray-400">
              创建时间 {{ moment.unix(skill.updated_at).format('YYYY-MM-DD HH:mm:ss') }}
            </div>
          </div>
        </a-card>
      </a-col>
      <a-col v-if="skills.length === 0" :span="24">
        <a-empty
          description="暂无技能，请上传 .md 或 .zip 文件"
          class="h-[400px] flex flex-col items-center justify-center"
        />
      </a-col>
    </a-row>
    <!-- 加载更多 -->
    <a-row v-if="paginator.total_page >= 2">
      <a-col v-if="paginator.current_page <= paginator.total_page" :span="24" class="text-center">
        <a-space class="my-4">
          <a-spin />
          <div class="text-gray-400">加载中</div>
        </a-space>
      </a-col>
      <a-col v-else :span="24" class="text-center">
        <div class="text-gray-400 my-4">数据已全部加载</div>
      </a-col>
    </a-row>
    <!-- 详情 Modal -->
    <a-modal
      :visible="showModal"
      :width="'clamp(320px, 80vw, 760px)'"
      hide-title
      :footer="false"
      modal-class="rounded-xl"
      @cancel="handleCancel"
    >
      <a-spin :loading="detailLoading" class="w-full">
        <!-- 顶部标题栏 -->
        <div class="flex items-start justify-between mb-4">
          <div class="flex items-center gap-3">
            <a-avatar
              v-if="skillDetail.icon"
              :size="36"
              shape="square"
              class="bg-blue-600"
              :image-url="skillDetail.icon"
            />
            <a-avatar v-else :size="36" shape="square" class="bg-blue-600">
              <icon-code />
            </a-avatar>
            <div>
              <div class="text-base font-bold text-gray-900">{{ skillDetail.name }}</div>
              <div class="text-xs text-gray-400">
                更新于 {{ moment(skillDetail.created_at).format('MM-DD HH:mm:ss') }}
              </div>
            </div>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <a-radio-group v-model="viewMode" type="button" size="small" class="py-0.5 rounded">
              <a-radio value="md">预览</a-radio>
              <a-radio value="code">源码</a-radio>
            </a-radio-group>
            <button
              class="arco-btn arco-btn-primary arco-btn-shape-square arco-btn-size-small rounded-lg"
              type="button"
              size="small"
              @click="handleDetail(skillDetail.id)"
            >
              详细信息
            </button>
          </div>
        </div>
        <!-- 描述 -->
        <div class="text-sm text-gray-500 mb-4">{{ skillDetail.description }}</div>
        <hr class="mb-4" />
        <!-- 内容区 -->
        <div
          :key="viewMode"
          class="content-scroll max-h-[480px] overflow-y-auto overflow-hidden"
          :class="viewMode === 'md' ? 'is-md' : 'is-code'"
        >
          <!-- MD 预览模式 -->
          <div v-if="viewMode === 'md'" class="markdown-body p-4 bg-white" v-html="renderedMd" />
          <!-- 源码模式 -->
          <pre
            v-else
            class="m-0 p-4 bg-gray-900 text-green-400 text-xs leading-relaxed overflow-x-auto whitespace-pre-wrap wrap-break-word font-mono"
            >{{ skillDetail.file_content?.trim() }}</pre
          >
        </div>
        <hr class="my-4" />
        <!-- 底部按钮 -->
        <div class="flex justify-end">
          <a-button class="rounded-lg" @click="handleCancel">关闭</a-button>
        </div>
      </a-spin>
    </a-modal>
    <a-modal
      :width="'clamp(200px, 80vw, 520px)'"
      :visible="props.createType === 'skills'"
      hide-title
      :footer="false"
      modal-class="rounded-xl"
      @cancel="handleCancelUpload"
    >
      <!-- 顶部标题 -->
      <div class="flex items-center justify-between">
        <div class="text-lg font-bold text-gray-700">上传技能</div>
        <a-button aria-label="关闭" @click="handleCancelUpload" type="text" class="!text-gray-700" size="small">
          <template #icon>
            <icon-close />
          </template>
        </a-button>
      </div>

      <!-- 表单 -->
      <div class="pt-6">
        <div class="flex flex-col gap-5">
          <!-- 图标上传 -->
          <div class="flex flex-col gap-2">
            <div class="text-sm text-gray-700">技能图标</div>
            <a-upload
              v-model:file-list="form.fileList"
              list-type="picture-card"
              :limit="1"
              image-preview
              :custom-request="handleIconUpload"
              :show-remove-button="true"
            />
          </div>
          <!-- 技能文件上传 -->
          <div class="flex flex-col gap-2">
            <div class="text-sm text-gray-700">
              技能文件
              <span class="text-gray-400 text-xs ml-1">支持 .md / .zip</span>
            </div>

            <!-- 拖拽区域 -->
            <div
              class="w-full border-2 border-dashed rounded-lg p-8 flex flex-col items-center gap-2 cursor-pointer transition-colors"
              :class="
                isDragging ? 'border-blue-400 bg-blue-50' : 'border-gray-200 hover:border-blue-400'
              "
              @click="triggerFileInput"
              @dragover.prevent="isDragging = true"
              @dragleave.prevent="isDragging = false"
              @drop.prevent="handleDrop"
            >
              <icon-upload class="text-2xl !text-gray-400" />
              <div class="text-sm text-gray-500">点击或拖拽文件到此处上传</div>
              <div class="text-xs text-gray-400">支持 .md 文件或 .zip 压缩包</div>
            </div>
            <!-- 隐藏的原生 input -->
            <input
              ref="fileInputRef"
              type="file"
              accept=".md,.zip"
              class="hidden"
              @change="handleFileChange"
            />
            <!-- 已选文件展示 -->
            <div
              v-if="form.file"
              class="flex items-center justify-between px-3 py-2 bg-gray-50 rounded-lg border border-gray-200"
            >
              <div class="flex items-center gap-2 text-sm text-gray-700">
                <icon-file class="!text-blue-500" />
                <span>{{ form.file.name }}</span>
                <span class="text-xs text-gray-400"
                  >({{ (form.file.size / 1024).toFixed(1) }} KB)</span
                >
              </div>
              <a-button aria-label="关闭"
                type="text"
                size="mini"
                class="!text-gray-400 hover:!text-red-500"
                @click.stop="form.file = null"
              >
                <template #icon><icon-close /></template>
              </a-button>
            </div>
          </div>

          <!-- 底部按钮 -->
          <div class="flex items-center justify-end">
            <a-space :size="16">
              <a-button class="rounded-lg" @click="handleCancelUpload">取消</a-button>
              <a-button
                type="primary"
                :loading="uploadLoading"
                class="rounded-lg"
                @click="handleSubmit"
              >
                上传
              </a-button>
            </a-space>
          </div>
        </div>
      </div>
    </a-modal>
  </a-spin>
</template>

<style scoped>
.content-scroll {
  border-radius: 0.3rem;
}

.text-center {
  text-align: center;
}

.content-scroll::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

.content-scroll.is-code::-webkit-scrollbar-track {
  background: #1f2937;
  border-radius: 0 0.5rem 0.5rem 0;
}

.content-scroll.is-code::-webkit-scrollbar-thumb {
  background-color: #4b5563;
  border-radius: 4px;
}

.content-scroll.is-code::-webkit-scrollbar-thumb:hover {
  background-color: #6b7280;
}

.content-scroll.is-md::-webkit-scrollbar-track {
  background: #f9fafb;
  border-radius: 0 0.5rem 0.5rem 0;
}

.content-scroll.is-md::-webkit-scrollbar-thumb {
  background-color: #d1d5db;
  border-radius: 4px;
}

.content-scroll.is-md::-webkit-scrollbar-thumb:hover {
  background-color: #9ca3af;
}
</style>
