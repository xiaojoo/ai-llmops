<script setup lang="ts">
import { useUpdateDraftAppConfig } from '@/hooks/use-app.ts'
import { computed, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useOptimizePrompt } from '@/hooks/use-ai.ts'
import MarkdownIt from 'markdown-it'

const props = defineProps({
  app_id: { type: String, required: true },
  preset_prompt: { type: String, required: true, default: '' },
  // 草稿配置数据库最近保存时间（秒）
  draft_updated_at: { type: Number, default: 0 },
})

const emits = defineEmits(['update:preset_prompt', 'saved'])
const { handleUpdateDraftAppConfig } = useUpdateDraftAppConfig()
const { loading, optimize_prompt, handleOptimizePrompt } = useOptimizePrompt()

const optimizeVisible = ref(false)
const origin_prompt = ref('')

// AI 优化弹窗开关
const openOptimizeModal = () => {
  optimizeVisible.value = true
}
const closeOptimizeModal = () => {
  optimizeVisible.value = false
}

// ===== 预览 / 编辑模式（对齐 demo：markdown 工具栏 + 预览区） =====
const previewMode = ref<'preview' | 'edit'>('preview')
const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
})

const promptText = computed(() => props.preset_prompt || '')
const wordCount = computed(() => promptText.value.length)
// 预览局部刷新：预览内容变化时（如应用 AI 优化结果）递增版本号，驱动 markdown 重新渲染
const previewTick = ref(0)
const renderedMarkdown = computed(() => {
  void previewTick.value
  return md.render(promptText.value)
})

const toHHMMSS = (d: Date) => {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

// 数据库中的最近保存时间（草稿配置 updated_at）
const dbSavedAt = computed(() =>
  props.draft_updated_at ? toHHMMSS(new Date(props.draft_updated_at * 1000)) : '',
)

const onBlur = async () => {
  await handleUpdateDraftAppConfig(props.app_id, {
    preset_prompt: props.preset_prompt,
  })
  // 通知父级重新拉取草稿配置，以取回数据库里的最新保存时间
  emits('saved')
}

const handleReplacePresetPrompt = async () => {
  if (optimize_prompt.value.trim() === '') {
    Message.warning('优化prompt为空，请重新生成')
    return
  }
  emits('update:preset_prompt', optimize_prompt.value)

  // 先等数据库写入完成，再通知父级重拉草稿，避免拉到旧值覆盖
  await handleUpdateDraftAppConfig(props.app_id, { preset_prompt: optimize_prompt.value })
  emits('saved')
  optimizeVisible.value = false
  // 局部刷新系统提示词预览
  previewTick.value += 1
}

const handleSubmit = async () => {
  if (origin_prompt.value.trim() === '') {
    Message.warning('原始prompt不能为空')
    return
  }
  await handleOptimizePrompt(origin_prompt.value)
}
</script>

<template>
  <div class="flex flex-col ab-prompt-root">
    <!-- 卡片头部（对齐 demo .card-head） -->
    <div class="ab-card-head">
      <div class="ab-card-title">系统提示词</div>
      <button type="button" class="ab-btn ab-btn-ai" @click="openOptimizeModal">
        <span>✦</span> AI 优化
      </button>
    </div>
    <!-- ===== AI 优化弹窗（参考 ai_app_builder_demo：标题 + 优化目标 + 当前提示词 + 分析结果） ===== -->
    <a-modal
      v-model:visible="optimizeVisible"
      width="max(500px, min(650px, calc(100vw - 32px)))"
      modal-class="rounded-xl"
      @cancel="closeOptimizeModal"
    >
      <template #title>
        <span class="ab-mid-title">AI 优化提示词</span>
      </template>
      <div class="pt-3">
        <!-- 优化目标 -->
        <div class="ab-optimize-label">优化目标</div>
        <input
          v-model="origin_prompt"
          type="text"
          class="ab-optimize-input"
          placeholder="例如：让提示词更加清晰、结构化，并提高 AI 输出稳定性"
        />
        <!-- 当前系统提示词 -->
        <div class="ab-optimize-label" style="margin-top: 17px">当前系统提示词</div>
        <textarea
          class="ab-optimize-textarea"
          :value="promptText"
          readonly
          placeholder="暂无提示词内容"
        ></textarea>
        <!-- AI 优化分析 -->
        <div v-if="optimize_prompt" class="ab-optimize-result">
          <b class="!text-[#344054]">✦ AI 优化分析</b>
          <div class="whitespace-pre-line text-[#667085] leading-relaxed mt-1">
            {{ optimize_prompt }}
          </div>
        </div>
        <div v-else class="ab-optimize-result">
          <b class="!text-[#344054]">✦ AI 优化分析</b>
          <p class="text-[#98a2b3] mt-1">
            输入优化目标后，点击右下角「AI 优化」，结果将展示在这里。
          </p>
        </div>
      </div>
      <template #footer>
        <div class="flex w-full items-center justify-end">
          <a-space :size="12">
            <a-button class="rounded-lg" @click="closeOptimizeModal">取消</a-button>
            <a-button
              v-if="!optimize_prompt || loading"
              :loading="loading"
              type="primary"
              class="rounded-lg"
              @click="handleSubmit"
            >
              AI 优化
            </a-button>
            <template v-else>
              <a-button type="primary" class="rounded-lg" @click="handleReplacePresetPrompt">
                应用优化
              </a-button>
            </template>
          </a-space>
        </div>
      </template>
    </a-modal>
    <!-- Markdown 工具栏 -->
    <div class="ab-md-toolbar">
      <div class="ab-md-tabs">
        <button
          type="button"
          class="ab-md-tab"
          :class="{ active: previewMode === 'preview' }"
          @click="previewMode = 'preview'"
        >
          预览
        </button>
        <button
          type="button"
          class="ab-md-tab"
          :class="{ active: previewMode === 'edit' }"
          @click="previewMode = 'edit'"
        >
          编辑
        </button>
      </div>
    </div>
    <!-- 编辑器主体 -->
    <div class="ab-editor-body">
      <!-- 内容区：固定高度，内容超出后在区域内滚动（避免把整张卡片撑得过高） -->
      <div class="ab-editor-area">
        <!-- Markdown 预览 -->
        <div v-show="previewMode === 'preview'" class="ab-md-preview" v-html="renderedMarkdown"></div>
        <!-- 编辑输入框 -->
        <textarea
          v-show="previewMode === 'edit'"
          class="ab-prompt-input"
          placeholder="请在这里输入Agent的人设与回复逻辑(预设prompt)"
          :maxlength="20000"
          :value="promptText"
          @input="(event: Event) => emits('update:preset_prompt', (event.target as HTMLTextAreaElement).value)"
          @blur="onBlur"
        ></textarea>
      </div>
      <!-- 底部：字数 + 自动保存（灰色文字，无背景，同字数样式） -->
      <div class="ab-editor-foot">
        <span>共 {{ wordCount }} 字</span>
        <span>{{ dbSavedAt ? `已自动保存 ${dbSavedAt}` : '编辑后自动保存' }}</span>
      </div>
      </div>
    </div>
</template>
