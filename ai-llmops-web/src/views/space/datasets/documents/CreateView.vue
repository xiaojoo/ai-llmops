<script setup lang="ts">
import { useRoute } from 'vue-router'
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import type { RequestOption, UploadRequest } from '@arco-design/web-vue'
import { Message } from '@arco-design/web-vue'
import { showErrorToast } from '@/utils/http/error'
import { unescapeString } from '@/utils/helper.ts'
import { encryptText, decryptText } from '@/utils/crypto.ts'
import { createDocuments, getDocumentsStatus, previewChunks } from '@/services/dataset.ts'
import type {
  CreateDocumentsRequest,
  CustomFileItem,
  GetDocumentsStatusResponse,
  PreviewChunk,
} from '@/models/dataset.ts'
import { uploadFile, getPendingUploadFiles, deletePendingUploadFile } from '@/services/upload-file.ts'
import { useGetLanguageModels } from '@/hooks/use-language-model.ts'

type DocumentItem = GetDocumentsStatusResponse['data'][number]

interface FormState {
  file_list: CustomFileItem[]
  process_type: 'automatic' | 'heading' | 'custom'
  // 识别设置：图片/表格/扫描PDF + OCR 模型选择
  recognition: {
    image: boolean
    table: boolean
    pdf_ocr: boolean
    ocr_provider: 'local' | 'api' | 'custom'
    // 章节摘要：prefix（截取300字符）| llm（大模型生成，模型可选）
    summary_mode: 'prefix' | 'llm'
    summary_model: string // 格式 provider/model，如 deepseek/deepseek-v4-flash
    // 自定义 API（更多）：允许用户输入 API 配置
    custom: {
      api_base: string
      api_key: string
      model: string
    }
  }
}

// 分段规则：独立 reactive 对象（避免嵌套在 createDocumentsForm 里，
// 传给 a-form :model 时 Vue 3.5 toRefs 对嵌套代理误判产生警告）
const ruleForm = reactive<{
  separators: string[]
  chunk_size: number
  chunk_overlap: number
  pre_process_rules: string[]
}>({
  separators: ['\\n'],
  chunk_size: 500,
  chunk_overlap: 50,
  pre_process_rules: [],
})

// 手动校验分段规则（替代 a-form validate，避免 a-form-item 的 toRefs 警告）
const validateRuleForm = (): boolean => {
  if (!ruleForm.separators.length) {
    Message.error('分段标识符不能为空')
    return false
  }
  if (ruleForm.chunk_size < 100 || ruleForm.chunk_size > 1000) {
    Message.error('分段最大长度在100-1000之间')
    return false
  }
  if (ruleForm.chunk_overlap < 0 || ruleForm.chunk_overlap > ruleForm.chunk_size * 0.5) {
    Message.error(`块重叠数在0-${Math.floor(ruleForm.chunk_size * 0.5)}之间`)
    return false
  }
  return true
}

const route = useRoute()
const datasetId = computed(() => String(route.params.dataset_id))

let timer: ReturnType<typeof setInterval> | null = null
let batch = ''
let fetchCount = 0

const currentStep = ref(1)
const createDocumentsLoading = ref(false)

// OCR 自定义 API 配置的 localStorage 键（加密保存用户输入的 API Key）
const OCR_CUSTOM_KEY = 'llmops_ocr_custom_config'

// 默认自定义 OCR 配置
const DEFAULT_OCR_CUSTOM = { api_base: '', api_key: '', model: 'qwen-vl-ocr' }

// 从本地解密恢复自定义 OCR 配置（API Key 加密保存）
const loadOcrCustomConfig = async () => {
  try {
    const saved = localStorage.getItem(OCR_CUSTOM_KEY)
    if (saved) {
      const parsed = JSON.parse(saved)
      // 兼容历史明文数据；新数据 api_key 为加密串，解密还原
      if (parsed.api_key) {
        parsed.api_key = await decryptText(parsed.api_key)
      }
      return { ...DEFAULT_OCR_CUSTOM, ...parsed }
    }
  } catch (err) {
    console.error('读取 OCR 配置失败:', err)
  }
  return { ...DEFAULT_OCR_CUSTOM }
}

// 加密保存自定义 OCR 配置到本地（API Key 不落明文）
const saveOcrCustomConfig = async () => {
  try {
    const custom = { ...createDocumentsForm.recognition.custom }
    if (custom.api_key) {
      custom.api_key = await encryptText(custom.api_key)
    }
    localStorage.setItem(OCR_CUSTOM_KEY, JSON.stringify(custom))
  } catch (err) {
    console.error('保存 OCR 配置失败:', err)
  }
}

const createDocumentsForm = reactive<FormState>({
  file_list: [],
  process_type: 'automatic',
  recognition: {
    image: true,
    table: true,
    pdf_ocr: true,
    ocr_provider: 'local',
    summary_mode: 'prefix',
    summary_model: 'deepseek/deepseek-v4-flash',
    custom: { ...DEFAULT_OCR_CUSTOM },
  },
})

// 模型下拉数据（provider 分组，复用 apps 模型选择接口）
const { language_models, loadLanguageModels } = useGetLanguageModels()
const summaryModelOptions = computed(() => {
  return language_models.value.map((language_model) => ({
    isGroup: true,
    label: language_model.label,
    options: language_model.models.map((model) => ({
      label: model.label,
      value: `${language_model.name}/${model.model}`,
    })),
  }))
})
// 仅在开启"大模型生成摘要"且还没拉过模型时加载
watch(
  () => createDocumentsForm.recognition.summary_mode,
  async (mode) => {
    if (mode === 'llm' && language_models.value.length === 0) {
      await loadLanguageModels()
    }
  },
)

// 挂载后异步解密恢复自定义 OCR 配置（API Key）
onMounted(async () => {
  createDocumentsForm.recognition.custom = await loadOcrCustomConfig()
})

const documents = reactive<DocumentItem[]>([])

// 本页已上传 + 最近2小时内上传的待分段文件（避免扫描全量历史）
interface PendingFile {
  id: string
  name: string
  size: number
  created_at: number
  checked: boolean
  uploading?: boolean
}
const pendingFiles = ref<PendingFile[]>([])
const pendingLoading = ref(false)
// 本页文件分页
const pendingPageSize = 8
const pendingPage = ref(1)
const pagedPendingFiles = computed(() => {
  const start = (pendingPage.value - 1) * pendingPageSize
  return pendingFiles.value.slice(start, start + pendingPageSize)
})
const pendingSelectedCount = computed(
  () => pendingFiles.value.filter((f) => f.checked).length,
)

// 进入页面加载最近2小时内上传、未创建文档（孤儿）的文件；默认不选中，由用户点选
const loadPendingFiles = async () => {
  pendingLoading.value = true
  try {
    const resp = await getPendingUploadFiles()
    pendingFiles.value = (resp.data || []).map((f) => ({ ...f, checked: false }))
  } catch (err) {
    console.error('加载已上传文件失败:', err)
  } finally {
    pendingLoading.value = false
  }
}

const removePendingFile = async (file: PendingFile) => {
  try {
    await deletePendingUploadFile(file.id)
    pendingFiles.value = pendingFiles.value.filter((f) => f.id !== file.id)
    // 当前页删空则回退一页
    const maxPage = Math.max(1, Math.ceil(pendingFiles.value.length / pendingPageSize))
    if (pendingPage.value > maxPage) pendingPage.value = maxPage
    Message.success('文件已删除')
  } catch (err) {
    Message.error('删除失败')
    console.error(err)
  }
}

loadPendingFiles()

// 构造创建/预览文档请求（按当前分段方式与规则）
const buildCreateDocumentsReq = (uploadFileIds: string[]): CreateDocumentsRequest => {
  // 构造请求时加密保存自定义 OCR 配置（API Key 不落明文）
  void saveOcrCustomConfig()

  const req: CreateDocumentsRequest = {
    upload_file_ids: uploadFileIds,
    process_type: createDocumentsForm.process_type,
  }

  if (createDocumentsForm.process_type === 'custom') {
    req.rule = {
      pre_process_rules: [
        {
          id: 'remove_extra_space',
          enabled: ruleForm.pre_process_rules.includes('remove_extra_space'),
        },
        {
          id: 'remove_url_and_email',
          enabled: ruleForm.pre_process_rules.includes('remove_url_and_email'),
        },
      ],
      segment: {
        separators: ruleForm.separators.map((sep) => unescapeString(sep)),
        chunk_size: ruleForm.chunk_size,
        chunk_overlap: ruleForm.chunk_overlap,
      },
      recognition: {
        image: createDocumentsForm.recognition.image,
        table: createDocumentsForm.recognition.table,
        pdf_ocr: createDocumentsForm.recognition.pdf_ocr,
        ocr_provider: createDocumentsForm.recognition.ocr_provider,
        summary_mode: createDocumentsForm.recognition.summary_mode,
        summary_model: createDocumentsForm.recognition.summary_model,
        custom: createDocumentsForm.recognition.custom,
      },
    }
  } else if (createDocumentsForm.process_type === 'heading') {
    req.rule = {
      pre_process_rules: [
        {
          id: 'remove_extra_space',
          enabled: ruleForm.pre_process_rules.includes('remove_extra_space'),
        },
        {
          id: 'remove_url_and_email',
          enabled: ruleForm.pre_process_rules.includes('remove_url_and_email'),
        },
      ],
      segment: {
        mode: 'heading',
        separators: ruleForm.separators.map((sep) => unescapeString(sep)),
        chunk_size: ruleForm.chunk_size,
        chunk_overlap: ruleForm.chunk_overlap,
      },
      recognition: {
        image: createDocumentsForm.recognition.image,
        table: createDocumentsForm.recognition.table,
        pdf_ocr: createDocumentsForm.recognition.pdf_ocr,
        ocr_provider: createDocumentsForm.recognition.ocr_provider,
        summary_mode: createDocumentsForm.recognition.summary_mode,
        summary_model: createDocumentsForm.recognition.summary_model,
        custom: createDocumentsForm.recognition.custom,
      },
    }
  }

  return req
}

// 切片预览：按当前规则切分第一个勾选文件，弹窗展示前几块
const previewModalVisible = ref(false)
const previewLoading = ref(false)
const previewChunksList = ref<PreviewChunk[]>([])
const onPreviewChunks = async () => {
  const uploadFileIds = pendingFiles.value.filter((f) => f.checked).map((f) => f.id)
  if (uploadFileIds.length === 0) {
    Message.error('请先勾选要预览的文件')
    return
  }
  if (createDocumentsForm.process_type === 'custom') {
    if (!validateRuleForm()) return
  }
  previewLoading.value = true
  try {
    const resp = await previewChunks(datasetId.value, buildCreateDocumentsReq(uploadFileIds))
    previewChunksList.value = resp.data || []
    previewModalVisible.value = true
  } catch (err) {
    showErrorToast(err instanceof Error ? err.message : '切片预览失败')
  } finally {
    previewLoading.value = false
  }
}

const nextStep = async () => {
  if (currentStep.value === 1) {
    const hasUploading =
      createDocumentsForm.file_list.some(
        (fileItem: CustomFileItem) =>
          fileItem.status === 'uploading' || !fileItem.response?.data?.id,
      ) || pendingFiles.value.some((f) => f.uploading)
    if (pendingSelectedCount.value === 0) {
      Message.error('请勾选需要添加到知识库的文件')
      return
    }
    if (hasUploading) {
      Message.warning('文件正在上传中，请稍后')
      return
    }
    currentStep.value++
  } else {
    if (createDocumentsForm.process_type === 'custom') {
      if (!validateRuleForm()) return
    }

    try {
      createDocumentsLoading.value = true

      // 只取勾选的文件（含新上传的 + 历史孤儿文件）
      const uploadFileIds = pendingFiles.value
        .filter((file) => file.checked)
        .map((file) => file.id)

      const req = buildCreateDocumentsReq(uploadFileIds)

      const resp = await createDocuments(datasetId.value, req)
      batch = resp.data.batch

      // 已使用的孤儿文件从列表中移除，避免下次重复创建
      pendingFiles.value = []
      pendingPage.value = 1

      fetchCount = 0
      stopTimer()

      await fetchDocumentsStatus()
      startTimer()

      currentStep.value++
    } finally {
      createDocumentsLoading.value = false
    }
  }
}

const prevStep = () => {
  if (currentStep.value > 1) {
    currentStep.value--
  }
}

const fetchDocumentsStatus = async () => {
  fetchCount++
  const resp = await getDocumentsStatus(datasetId.value, batch)
  const data = resp.data || []
  documents.splice(0, documents.length, ...data)

  if (fetchCount >= 30) {
    stopTimer()
    return
  }

  const isCompleted = data.every(
    (document) => document.status === 'completed' || document.status === 'error',
  )
  if (isCompleted && data.length > 0) stopTimer()
}

const startTimer = () => {
  stopTimer()
  timer = setInterval(fetchDocumentsStatus, 5000)
}

const stopTimer = () => {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

// a-upload 的 custom-request 需同步返回 UploadRequest（{ abort }），异步逻辑在内部任务中执行
const handleUpload = (option: RequestOption): UploadRequest => {
  const { fileItem, onSuccess, onError } = option

  const uploadTask = async () => {
    // 上传中：插入占位项显示加载动画（无 id，不参与勾选/分段）
    const tempKey = `uploading-${Date.now()}-${Math.random().toString(36).slice(2)}`
    pendingFiles.value.unshift({
      id: tempKey,
      name: fileItem.name || '上传中…',
      size: fileItem.file?.size || 0,
      created_at: Math.floor(Date.now() / 1000),
      checked: false,
      uploading: true,
    })
    pendingPage.value = 1
    try {
      const resp = await uploadFile(fileItem.file as File)
      // 上传成功：将占位项替换为真实文件并自动选中
      const idx = pendingFiles.value.findIndex((f) => f.id === tempKey)
      if (resp.data?.id && idx !== -1) {
        pendingFiles.value.splice(idx, 1, {
          id: resp.data.id,
          name: resp.data.name,
          size: resp.data.size,
          created_at: resp.data.created_at,
          checked: true,
          uploading: false,
        })
      } else if (idx !== -1) {
        pendingFiles.value.splice(idx, 1)
      }
      // 从上传组件内部列表移除避免重复
      const li = createDocumentsForm.file_list.findIndex(
        (f: CustomFileItem) => f.uid === fileItem.uid || f.name === fileItem.name,
      )
      if (li !== -1) createDocumentsForm.file_list.splice(li, 1)
      onSuccess?.(resp)
    } catch (err) {
      // 上传失败：移除占位项
      const idx = pendingFiles.value.findIndex((f) => f.id === tempKey)
      if (idx !== -1) pendingFiles.value.splice(idx, 1)
      onError?.(err as Error)
    }
  }
  uploadTask()

  return { abort: () => {} }
}

onUnmounted(() => stopTimer())
</script>

<template>
  <div class="p-6">
    <div class="flex items-center mb-6 gap-4">
      <router-link
        :to="{
          name: 'space-datasets-documents-list',
          params: { dataset_id: datasetId },
        }"
      >
        <a-button aria-label="返回" size="mini" type="text" class="!text-gray-700">
          <template #icon>
            <icon-left />
          </template>
        </a-button>
      </router-link>
      <div class="text-lg font-bold text-gray-700">添加文件</div>
    </div>

    <div class="w-[520px] mx-auto">
      <a-steps :current="currentStep">
        <a-step>上传</a-step>
        <a-step>分段设置</a-step>
        <a-step>数据处理</a-step>
      </a-steps>
    </div>

    <div class="min-h-[calc(100vh-160pc)] py-[24px]">
      <!-- 步骤 1 -->
      <div v-if="currentStep === 1">
        <a-upload
          v-model:file-list="createDocumentsForm.file_list"
          draggable
          accept=".doc, .docx, .pdf, .txt, .md, .markdown"
          :limit="10"
          multiple
          :show-file-list="false"
          tip="支持PDF、TXT、DOC、MD，最多可上次10个文件，每个文件大小10MB"
          :custom-request="handleUpload"
        />

        <!-- 最近2小时上传待分段文件 + 本页上传 -->
        <div v-if="pendingFiles.length > 0" class="mt-4">
          <div class="flex items-center justify-between mb-2">
            <div class="text-sm font-bold text-gray-700">
              已上传待分段文件（已选 {{ pendingSelectedCount }} 个）
            </div>
            <div class="text-gray-500 text-xs">勾选后可继续分段，未勾选的不参与；可删除</div>
          </div>
          <div
            v-for="file in pagedPendingFiles"
            :key="file.id"
            :class="`flex items-center justify-between px-4 py-3 bg-white rounded-lg border mb-2 transition-colors ${file.uploading ? 'opacity-70 cursor-wait' : 'cursor-pointer'} ${file.checked ? 'border-blue-500' : 'border-gray-200'}`"
            @click="!file.uploading && (file.checked = !file.checked)"
          >
            <div class="flex items-center gap-2.5 min-w-0">
              <!-- 上传中：spinner 动画；上传完成：勾选框（仅作选中状态展示，隐藏图标） -->
              <a-spin v-if="file.uploading" :size="14" />
              <a-checkbox
                v-else
                :model-value="file.checked"
                class="pending-checkbox"
                @click.stop
              />
              <a-avatar shape="square" class="bg-blue-700" :size="32">
                <icon-file />
              </a-avatar>
              <div class="min-w-0">
                <div class="text-gray-700 truncate">
                  {{ file.name }}
                  <span v-if="file.uploading" class="text-blue-500 text-xs ml-1">上传中…</span>
                </div>
                <div class="text-gray-500 text-xs">
                  {{ file.uploading ? '正在上传到对象存储' : `${(file.size / 1024).toFixed(2)}KB · ${new Date(file.created_at * 1000).toLocaleString()}` }}
                </div>
              </div>
            </div>
            <a-button
              v-if="!file.uploading"
              size="mini"
              type="text"
              status="danger"
              @click.stop="removePendingFile(file)"
            >
              <template #icon><icon-delete /></template>
              删除
            </a-button>
          </div>
          <a-pagination
            v-if="pendingFiles.length > pendingPageSize"
            v-model:current="pendingPage"
            :page-size="pendingPageSize"
            :total="pendingFiles.length"
            size="small"
            class="mt-3"
          />
        </div>
      </div>

      <!-- 步骤 2 -->
      <div v-else-if="currentStep === 2">
        <div
          :class="`px-5 py-4 bg-white rounded-lg border cursor-pointer mb-4 hover:border-blue-700 ${createDocumentsForm.process_type === 'automatic' ? 'border-blue-700' : ''}`"
          @click="createDocumentsForm.process_type = 'automatic'"
        >
          <div class="font-bold text-gray-700 mb-2">自动分段与清洗</div>
          <div class="text-gray-500 leading-relaxed">
            自动分段与预处理规则。切分方式：优先按分隔符（段落→换行→句号→逗号）递归切分，单块不超过
            500 字符，相邻块重叠 50 字符；自动启用文本清洗（去除多余空格、URL 与邮箱）。
          </div>
        </div>

        <div
          :class="`px-5 py-4 bg-white rounded-lg border cursor-pointer mb-4 hover:border-blue-700 ${createDocumentsForm.process_type === 'heading' ? 'border-blue-700' : ''}`"
          @click="createDocumentsForm.process_type = 'heading'"
        >
          <div class="font-bold text-gray-700 mb-2">标题感知分段</div>
          <div class="text-gray-500 leading-relaxed">
            按 Markdown 标题层级（# ~ ######）把文档切成章节，子块保留完整标题路径作为上下文；章节超过设定长度时再按分隔符细分。
          </div>

          <div v-show="createDocumentsForm.process_type === 'heading'">
            <a-divider />
            <div class="space-y-4">
              <div>
                <div class="block text-sm text-gray-700 mb-1.5">分段标识符</div>
                <a-input-tag
                  v-model:model-value="ruleForm.separators"
                  placeholder="请输入分段标识符，按下Enter结束"
                />
              </div>
              <div>
                <label class="block text-sm text-gray-700 mb-1.5" for="rule-chunk-size">分段最大长度</label>
                <a-input-number
                  :input-attrs="{ id: 'rule-chunk-size' }"
                  v-model:model-value="ruleForm.chunk_size"
                  :min="100"
                  :max="1000"
                  :default-value="500"
                  class="w-full"
                />
              </div>
              <div>
                <label class="block text-sm text-gray-700 mb-1.5" for="rule-chunk-overlap">块重叠数</label>
                <a-input-number
                  :input-attrs="{ id: 'rule-chunk-overlap' }"
                  v-model:model-value="ruleForm.chunk_overlap"
                  :min="0"
                  :max="500"
                  :default-value="50"
                  class="w-full"
                />
              </div>
              <div>
                <div class="block text-sm text-gray-700 mb-1.5">文本预处理规则</div>
                <a-checkbox-group
                  direction="vertical"
                  v-model:model-value="ruleForm.pre_process_rules"
                >
                  <a-checkbox value="remove_extra_space"
                    >替换掉连续的空格、换行符和制表符</a-checkbox
                  >
                  <a-checkbox value="remove_url_and_email">删除所有的url和邮箱地址</a-checkbox>
                </a-checkbox-group>
              </div>
            </div>
          </div>
        </div>

        <div
          :class="`px-5 py-4 bg-white rounded-lg border cursor-pointer mb-4 hover:border-blue-700 ${createDocumentsForm.process_type === 'custom' ? 'border-blue-700' : ''}`"
          @click="createDocumentsForm.process_type = 'custom'"
        >
          <div class="font-bold text-gray-700 mb-2">自定义</div>
          <div class="text-gray-500">自定义分段规则、分段长度与预处理规则</div>

          <div v-show="createDocumentsForm.process_type === 'custom'">
            <a-divider />
            <div class="space-y-4">
              <div>
                <div class="block text-sm text-gray-700 mb-1.5">分段标识符</div>
                <a-input-tag
                  v-model:model-value="ruleForm.separators"
                  placeholder="请输入分段标识符，按下Enter结束"
                />
              </div>
              <div>
                <label class="block text-sm text-gray-700 mb-1.5" for="rule-chunk-size-custom">分段最大长度</label>
                <a-input-number
                  :input-attrs="{ id: 'rule-chunk-size-custom' }"
                  v-model:model-value="ruleForm.chunk_size"
                  :min="100"
                  :max="1000"
                  :default-value="500"
                  class="w-full"
                />
              </div>
              <div>
                <label class="block text-sm text-gray-700 mb-1.5" for="rule-chunk-overlap-custom">块重叠数</label>
                <a-input-number
                  :input-attrs="{ id: 'rule-chunk-overlap-custom' }"
                  v-model:model-value="ruleForm.chunk_overlap"
                  :min="0"
                  :max="500"
                  :default-value="50"
                  class="w-full"
                />
              </div>
              <div>
                <div class="block text-sm text-gray-700 mb-1.5">文本预处理规则</div>
                <a-checkbox-group
                  direction="vertical"
                  v-model:model-value="ruleForm.pre_process_rules"
                >
                  <a-checkbox value="remove_extra_space"
                    >替换掉连续的空格、换行符和制表符</a-checkbox
                  >
                  <a-checkbox value="remove_url_and_email">删除所有的url和邮箱地址</a-checkbox>
                </a-checkbox-group>
              </div>
            </div>
          </div>
        </div>

        <!-- 识别设置：图片/表格/扫描PDF 与 OCR 模型选择 -->
        <div class="px-5 py-4 bg-white rounded-lg border border-gray-200 mb-4">
          <div class="font-bold text-gray-700 mb-2">识别设置</div>
          <div class="text-gray-500 text-xs mb-3">
            图片、表格、扫描版 PDF 的识别方式；识别结果会参与分段与检索。
          </div>
          <div class="space-y-2 mb-3">
            <a-checkbox v-model="createDocumentsForm.recognition.image"
              >识别图片（OCR 提取图片中的文字）</a-checkbox
            >
            <a-checkbox v-model="createDocumentsForm.recognition.table"
              >识别表格（Excel/CSV 转为 Markdown 表格结构）</a-checkbox
            >
            <a-checkbox v-model="createDocumentsForm.recognition.pdf_ocr"
              >扫描版 PDF 逐页识别（无文本层的 PDF 自动 OCR）</a-checkbox
            >
          </div>
          <div class="mt-4">
            <div class="block text-sm text-gray-700 mb-1.5">OCR 模型</div>
            <a-radio-group v-model="createDocumentsForm.recognition.ocr_provider">
              <a-radio value="local">本地（RapidOCR，免费，无需外部依赖）</a-radio>
              <a-radio value="api">
                API（DashScope qwen-vl-ocr，多模态，表格版面识别强）
              </a-radio>
              <a-radio value="custom">更多（自定义 API）</a-radio>
            </a-radio-group>

            <!-- 自定义 API 配置：用户输入 API 地址/Key/模型，永久保存 -->
            <div
              v-if="createDocumentsForm.recognition.ocr_provider === 'custom'"
              class="mt-3 space-y-3 rounded-lg border border-gray-200 p-3 bg-gray-50"
            >
              <div>
                <label class="block text-xs text-gray-600 mb-1" for="ocr-api-base">API 地址（Base URL）</label>
                <a-input
                  :input-attrs="{ id: 'ocr-api-base' }"
                  v-model="createDocumentsForm.recognition.custom.api_base"
                  placeholder="https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation"
                />
              </div>
              <div>
                <label class="block text-xs text-gray-600 mb-1" for="ocr-api-key">API Key</label>
                <a-input-password
                  :input-attrs="{ id: 'ocr-api-key' }"
                  v-model="createDocumentsForm.recognition.custom.api_key"
                  placeholder="请输入 API Key（保存后永久有效）"
                />
              </div>
              <div>
                <label class="block text-xs text-gray-600 mb-1" for="ocr-model">模型名</label>
                <a-input
                  :input-attrs="{ id: 'ocr-model' }"
                  v-model="createDocumentsForm.recognition.custom.model"
                  placeholder="qwen-vl-ocr"
                />
              </div>
              <div class="text-xs text-gray-400">
                API Key 保存在浏览器本地（localStorage），仅用于本机 OCR 调用。
              </div>
            </div>
          </div>

          <!-- 章节摘要：方式选择 + LLM 模型下拉（复用 apps 模型选择接口） -->
          <div class="mt-4">
            <div class="block text-sm text-gray-700 mb-1.5">章节摘要</div>
            <a-radio-group v-model="createDocumentsForm.recognition.summary_mode" direction="vertical">
              <a-radio value="prefix"
                >截取章节前 300 字符（快速、零成本、无延迟）</a-radio
              >
              <a-radio value="llm">大模型生成摘要（调用下方选择的模型，质量更高）</a-radio>
            </a-radio-group>
            <div
              v-if="createDocumentsForm.recognition.summary_mode === 'llm'"
              class="mt-3 rounded-lg border border-gray-200 p-3 bg-gray-50"
            >
              <div class="block text-xs text-gray-600 mb-1">摘要模型</div>
              <a-select
                v-model="createDocumentsForm.recognition.summary_model"
                :options="summaryModelOptions"
                class="rounded-lg"
                placeholder="请选择摘要模型"
              >
                <template #label="{ data }">
                  <div class="flex items-center gap-2 text-xs">
                    <span class="text-gray-700">{{ data.value.split('/')[0] }}</span>
                    <span class="text-gray-400">·</span>
                    <span class="text-gray-700">{{ data.value.split('/')[1] }}</span>
                  </div>
                </template>
                <template #option="{ data }">
                  <div class="flex items-center gap-2 text-xs py-1">
                    <span class="text-gray-700">{{ data.value.split('/')[0] }}</span>
                    <span class="text-gray-400">·</span>
                    <span class="text-gray-700">{{ data.label }}</span>
                  </div>
                </template>
              </a-select>
              <div class="text-xs text-gray-400 mt-1.5">
                摘要用于检索命中章节块时的上下文前缀（[章节摘要] xxx）。未配置模型 Key 时自动回退截取。
              </div>
            </div>
          </div>
        </div>
      </div>
      <div v-else>
        <div class="text-gray-900 mb-4 text-base">服务器正在处理中</div>
        <div class="flex flex-col gap-2">
          <div
            v-for="document in documents"
            :key="document.id"
            class="flex items-center justify-between px-4 py-3 bg-white rounded-lg border"
          >
            <div class="flex items-center gap-2.5">
              <a-avatar shape="square" class="bg-blue-700" :size="32">
                <icon-file />
              </a-avatar>
              <div>
                <div class="text-gray-700">{{ document.name }}</div>
                <div class="text-gray-500">{{ (document.size / 1024).toFixed(2) }}KB</div>
              </div>
            </div>

            <div v-if="document.status === 'error'" class="text-red-500">
              处理失败: {{ document.error }}
            </div>
            <div v-else-if="document.status === 'completed'" class="text-green-600">处理完成</div>
            <div v-else-if="!document.segment_count" class="text-gray-500">0.00%</div>
            <div v-else class="text-blue-600">
              {{ ((document.completed_segment_count / document.segment_count) * 100).toFixed(2) }}%
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 底部按钮 -->
    <div class="flex items-center justify-between">
      <div></div>
      <div class="flex items-center gap-2">
        <a-button
          v-if="currentStep === 2"
          class="rounded-lg"
          :loading="previewLoading"
          @click="onPreviewChunks"
        >
          <template #icon><icon-eye /></template>
          切片预览
        </a-button>
        <a-button class="rounded-lg" v-if="currentStep === 2" @click="prevStep">上一步</a-button>
        <a-button
          :loading="createDocumentsLoading"
          v-if="currentStep <= 2"
          type="primary"
          class="rounded-lg"
          @click="nextStep"
        >
          下一步
        </a-button>
        <div v-if="currentStep === 3" class="flex items-center gap-2">
          <div class="text-gray-500">点击确认不影响数据处理，处理完毕后可进行引用</div>
          <router-link
            :to="{
              name: 'space-datasets-documents-list',
              params: { dataset_id: datasetId },
            }"
          >
            <a-button type="primary" class="rounded-lg">确定</a-button>
          </router-link>
        </div>
      </div>
    </div>

    <!-- 切片预览弹窗：展示当前规则切分后的前几块 -->
    <a-modal
      :visible="previewModalVisible"
      hide-title
      :footer="false"
      modal-class="recall-modal rounded-xl"
      @cancel="previewModalVisible = false"
    >
      <div class="flex items-center justify-between mb-4">
        <div class="text-lg font-bold text-gray-700">切片预览</div>
        <a-button aria-label="关闭" size="small" type="text" class="!text-gray-700" @click="previewModalVisible = false">
          <template #icon><icon-close /></template>
        </a-button>
      </div>
      <div class="text-gray-500 text-xs mb-3">
        按当前分段方式与参数对勾选的第一个文件切分，展示前 {{ previewChunksList.length }} 块；可调整参数后再次预览对比。
      </div>
      <div v-if="previewChunksList.length === 0" class="py-10 text-center text-gray-400">
        暂无预览结果，请调整参数后重试
      </div>
      <div v-else class="max-h-[60vh] overflow-y-auto space-y-3">
        <div
          v-for="chunk in previewChunksList"
          :key="chunk.index"
          class="rounded-lg border border-gray-200 p-3 bg-gray-50"
        >
          <div class="flex items-center justify-between mb-1.5">
            <div class="text-xs font-bold text-gray-500">第 {{ chunk.index }} 块</div>
            <div class="text-xs text-gray-400">{{ chunk.character_count }} 字符</div>
          </div>
          <div v-if="chunk.headings && chunk.headings.length" class="mb-1.5">
            <a-tag
              v-for="h in chunk.headings"
              :key="h"
              size="small"
              color="arcoblue"
              class="rounded mr-1"
            >{{ h }}</a-tag>
          </div>
          <div class="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed break-all">
            {{ chunk.content }}
          </div>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<style scoped>
/* 勾选框仅作为选中状态展示：隐藏对勾图标，点击整行切换选中 */
.pending-checkbox :deep(.arco-checkbox-icon-check) {
  display: none;
}
.pending-checkbox :deep(.arco-checkbox-icon-hover) {
  display: none;
}
</style>

<!-- 切片预览弹窗宽度：视口 <1125px 时占 80%，≥1125px 固定 900px 封顶（纯 CSS）。
     模态框 teleport 到 body，需用非 scoped 样式通过 modal-class 命中 .arco-modal -->
<style>
.recall-modal {
  width: clamp(320px, 80vw, 900px);
}
</style>
