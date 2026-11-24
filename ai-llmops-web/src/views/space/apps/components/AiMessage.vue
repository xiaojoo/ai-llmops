<script setup lang="ts">
import { computed, type PropType, ref, watch } from 'vue'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import c from 'highlight.js/lib/languages/c'
import cpp from 'highlight.js/lib/languages/cpp'
import css from 'highlight.js/lib/languages/css'
import dockerfile from 'highlight.js/lib/languages/dockerfile'
import go from 'highlight.js/lib/languages/go'
import java from 'highlight.js/lib/languages/java'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import markdown from 'highlight.js/lib/languages/markdown'
import python from 'highlight.js/lib/languages/python'
import rust from 'highlight.js/lib/languages/rust'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'
import DotFlashing from '@/components/DotFlashing.vue'
import AgentThought from '@/views/space/apps/components/AgentThought.vue'
import type { GetDebugConversationMessagesWithPageResponse } from '@/models/app.ts'
import 'github-markdown-css'
import 'highlight.js/styles/github.css'

// 按需注册常用语言（避免打包 highlight.js 全量 190+ 语言）。
// 未注册的语言会被 getLanguage() 拦截，代码块降级为纯文本展示。
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('python', python)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('json', json)
hljs.registerLanguage('xml', xml)
hljs.registerLanguage('css', css)
hljs.registerLanguage('markdown', markdown)
hljs.registerLanguage('yaml', yaml)
hljs.registerLanguage('sql', sql)
hljs.registerLanguage('dockerfile', dockerfile)
hljs.registerLanguage('go', go)
hljs.registerLanguage('java', java)
hljs.registerLanguage('c', c)
hljs.registerLanguage('cpp', cpp)
hljs.registerLanguage('rust', rust)

const props = defineProps({
  app: { type: Object, required: true, default: () => ({}) },
  enable_text_to_speech: { type: Boolean, default: false },
  message_id: { type: String, required: true },
  answer: { type: String, required: true, default: '' },
  loading: { type: Boolean, default: false },
  latency: { type: Number, default: 0 },
  total_token_count: { type: Number, default: 0 },
  agent_thoughts: {
    type: Array as PropType<
      GetDebugConversationMessagesWithPageResponse['data']['list'][number]['agent_thoughts']
    >,
    default: () => [],
  },
  suggested_questions: {
    type: Array as PropType<string[]>,
    default: () => [],
  },
  message_class: { type: String, default: 'bg-gray-100' },
  max_width: { type: String, default: 'calc(100%-38px)' },
  error: { type: String, default: '' },
  feedback: { type: String, default: '' },
  is_archived: { type: Boolean, default: false },
  query: { type: String, default: '' },
  is_playing: { type: Boolean, default: false },
  audio_loading: { type: Boolean, default: false },
  start_audio_stream: { type: Function, default: null },
  stop_audio_stream: { type: Function, default: null },
  // 运行流程步骤可点击跳转任务详情（web-apps 传入 true）
  jumpable: { type: Boolean, default: false },
  // 消息状态投影 + 最新 run 终态：用于区分"正在生成"与"已终态(超时/停止/出错)"，
  // 避免已终结但 answer 为空的消息永远显示"正在生成"的抖点
  status: { type: String, default: '' },
  run_status: { type: String, default: '' },
  // 可断点续跑：消息操作条显示"继续执行"图标按钮（点击触发 emit('continue')）
  can_resume: { type: Boolean, default: false },
})

const emits = defineEmits(['selectSuggestedQuestion', 'feedback', 'copyContent', 'step-click', 'regenerate', 'continue'])

const copiedCodeIndex = ref<number | null>(null)
const showArchivedHistory = ref(false)
const contentCopied = ref(false)

// 反馈状态：优先显示「本次点击」的意图（pending），否则直接派生自 props.feedback。
// 使用 computed 而非本地 ref，保证与后端/父组件数据始终一致，
// 虚拟滚动复用组件实例时不会把其他消息的点亮状态带过来
const pendingFeedback = ref<'like' | 'dislike' | null>(null)
const feedbackStatus = computed<'like' | 'dislike' | null>(() => {
  if (pendingFeedback.value) return pendingFeedback.value
  return props.feedback === 'like' || props.feedback === 'dislike' ? props.feedback : null
})

// 切换消息（虚拟滚动复用/重建）时清空本次点击意图，回落到该消息自身的反馈
watch(
  () => props.message_id,
  () => {
    pendingFeedback.value = null
  },
)

// 反馈处理（点赞/点踩，再次点击取消）
const handleFeedback = (type: 'like' | 'dislike') => {
  if (feedbackStatus.value === type) {
    pendingFeedback.value = null
    emits('feedback', { message_id: props.message_id, feedback: null })
  } else {
    pendingFeedback.value = type
    emits('feedback', { message_id: props.message_id, feedback: type })
  }
}

// 复制完整回答内容
const copyFullContent = async () => {
  try {
    await navigator.clipboard.writeText(props.answer)
    contentCopied.value = true
    emits('copyContent', { message_id: props.message_id, content: props.answer })
    setTimeout(() => {
      contentCopied.value = false
    }, 2000)
  } catch (err) {
    console.error('Failed to copy content:', err)
  }
}

// 重新生成：通知父级用该条回答对应的用户输入再发一次
const handleRegenerate = () => {
  emits('regenerate')
}

// 复制代码函数
const copyCode = async (code: string, index: number) => {
  try {
    await navigator.clipboard.writeText(code)
    copiedCodeIndex.value = index
    setTimeout(() => {
      copiedCodeIndex.value = null
    }, 2000)
  } catch (err) {
    console.error('Failed to copy code:', err)
  }
}

const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
  highlight(code: string, lang: string): string {
    const language = lang && hljs.getLanguage(lang) ? lang : 'plaintext'
    let highlightedCode = ''

    if (lang && hljs.getLanguage(lang)) {
      try {
        highlightedCode = hljs.highlight(code, { language: lang }).value
      } catch {
        highlightedCode = md.utils.escapeHtml(code)
      }
    } else {
      highlightedCode = md.utils.escapeHtml(code)
    }

    const codeIndex = Math.random().toString(36).substring(2, 9)

    return `<div class="code-block-wrapper relative group my-4 rounded-lg overflow-hidden" style="background-color: #f6f8fa;">
      <div class="flex items-center justify-between px-4 py-2 text-xs text-gray-600" style="background-color: #f0f2f5;">
        <span class="font-mono">${language}</span>
        <button
          class="copy-code-btn flex items-center gap-1 px-2 py-1 rounded hover:bg-gray-200 transition"
          data-code-index="${codeIndex}"
          data-code="${md.utils.escapeHtml(code)}"
        >
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
          </svg>
          <span>复制</span>
        </button>
      </div>
      <pre class="hljs m-0 p-4" style="background-color: #f6f8fa; margin: 0;"><code style="background-color: #f6f8fa;">${highlightedCode}</code></pre>
    </div>`
  },
})

// 添加自定义渲染规则
md.renderer.rules.fence = (tokens, idx) => {
  const token = tokens[idx]
  if (!token) return ''
  const code = token.content
  const lang = token.info || 'plaintext'

  return (
    md.options.highlight?.(code, lang, '') ||
    `<pre class="hljs" style="background-color: #f6f8fa;"><code style="background-color: #f6f8fa;">${md.utils.escapeHtml(code)}</code></pre>`
  )
}

const compiledMarkdown = computed(() => {
  let content = props.answer || ''

  const htmlStartRegex = /(\n|^)\s*(<!DOCTYPE html>|<html)/i
  const match = content.match(htmlStartRegex)

  if (match && typeof match.index === 'number') {
    const prefixStr = match[1] || ''
    const splitIndex = match.index + prefixStr.length

    const textBefore = content.slice(0, splitIndex)

    if (!textBefore.trim().endsWith('```') && !textBefore.trim().endsWith('```html')) {
      const textPart = content.slice(0, splitIndex)
      const codePart = content.slice(splitIndex)

      content = `${textPart}\n\`\`\`html\n${codePart}\n\`\`\``
    }
  }

  return md.render(content)
})

// 消息是否为终态（超时/停止/出错）：终态但 answer 为空时，不应永远显示"正在生成"抖点
const isTerminal = computed(
  () =>
    props.status === 'timeout' ||
    props.status === 'stop' ||
    props.status === 'error' ||
    ['timed_out', 'cancelled', 'failed'].includes(props.run_status || ''),
)

// 终态时展示的提示文案（answer 为空时替代"正在生成"抖动）
const terminalHint = computed(() => {
  if (props.run_status === 'timed_out' || props.status === 'timeout')
    return '任务执行超时，已中断。可点击「继续执行」从断点续跑。'
  if (props.status === 'stop' || props.run_status === 'cancelled')
    return '任务已停止。可点击「继续执行」从断点续跑。'
  return '任务执行出错，已中断。可点击「继续执行」重试。'
})

// 处理复制按钮点击事件
const handleMarkdownClick = (event: MouseEvent) => {
  const target = event.target as HTMLElement
  const copyBtn = target.closest('.copy-code-btn')

  if (copyBtn) {
    const code = copyBtn.getAttribute('data-code')
    const codeIndex = copyBtn.getAttribute('data-code-index')
    if (code && codeIndex) {
      // 解码HTML实体
      const decodedCode = code.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
      copyCode(decodedCode, parseInt(codeIndex, 36))

      const btnSpan = copyBtn.querySelector('span')
      if (btnSpan) {
        const originalText = btnSpan.innerText
        btnSpan.innerText = '已复制'
        setTimeout(() => {
          btnSpan.innerText = originalText
        }, 2000)
      }
    }
  }
}
</script>

<template>
  <div class="flex gap-2" @click="handleMarkdownClick">
    <!-- 左侧头像 -->
    <a-avatar :size="30" shape="circle" class="shrink-0" :image-url="props.app?.icon" />
    <!-- 右侧内容 -->
    <div class="flex flex-col items-start gap-2 flex-1" :style="{ maxWidth: props.max_width }">
      <!-- 归档消息：默认不展示原文，提供历史查询入口 -->
      <div v-if="props.is_archived" class="w-full">
        <div class="text-xs text-gray-400 mb-1">该轮对话已归档（压缩出短期记忆窗口）</div>
        <a-button size="mini" @click="showArchivedHistory = !showArchivedHistory">
          {{ showArchivedHistory ? '收起历史' : '查看历史' }}
        </a-button>
        <div v-if="showArchivedHistory" class="mt-2 w-full bg-gray-50 border border-gray-200 rounded-lg p-3">
          <div class="text-sm text-gray-800">{{ props.query }}</div>
          <div class="text-sm text-gray-800 mt-2">{{ props.answer }}</div>
        </div>
      </div>
      <template v-else>
        <!-- 应用名称 -->
        <div class="text-gray-700 font-bold">
          {{ props.app?.name }}
        </div>
        <agent-thought
          :message_id="props.message_id"
          :agent_thoughts="props.agent_thoughts"
          :loading="props.loading"
          :jumpable="props.jumpable"
          @step-click="(thought: unknown) => emits('step-click', thought)"
        />
        <div
          v-if="props.error"
          :class="`${props.message_class} w-[calc(100%-38px)] border border-red-200 bg-red-50 text-red-600 px-4 py-3 rounded-2xl break-all`"
        >
          {{ props.error }}
        </div>
        <div
          v-else-if="props.answer.trim() === ''"
          :class="`${props.message_class} w-[calc(100%-38px)] border border-gray-200 text-gray-700 px-4 py-3 rounded-2xl break-all`"
        >
          <!-- 终态（超时/停止/出错）且无答案：不显示"生成中"抖点，改为明确的状态提示 -->
          <template v-if="isTerminal">
            <span class="text-gray-400">{{ terminalHint }}</span>
          </template>
          <!-- 答案为空即视为生成中：等待第一条流式事件期间也显示左侧三连点加载 -->
          <dot-flashing v-else />
        </div>
        <div
          v-else
          :class="`${props.message_class} w-[calc(100%-38px)] markdown-body border border-gray-200 text-gray-700 px-4 py-3 rounded-2xl break-all`"
          v-html="compiledMarkdown"
        />
        <!-- 底部信息 + 操作按钮 -->
        <div class="flex items-center w-[calc(100%-38px)] my-1">
          <!-- 左侧信息 -->
          <div class="flex items-center gap-4 text-xs text-gray-500 flex-1">
            <div class="flex items-center gap-1">
              <icon-check />
              {{ props.latency.toFixed(2) }}s
            </div>
            <!-- 0 只可能是"这轮没有 token 数"（空回答/异常），不显示一个 0 Tokens -->
            <div v-if="props.total_token_count > 0">{{ props.total_token_count }} Tokens</div>
          </div>
          <!-- 右侧：反馈/复制/播放操作按钮（尺寸与间隙统一；图标带气泡提示） -->
          <div class="flex items-center gap-2">
            <!-- 断点续跑（仅可续跑消息显示）：与其他操作图标一致，纯图标无文字/背景 -->
            <a-tooltip v-if="props.can_resume" content="继续执行">
              <icon-launch
                :size="25"
                class="rounded-full p-1 !text-gray-400 hover:bg-gray-100 hover:!text-gray-600 transition cursor-pointer"
                @click.stop="emits('continue')"
              />
            </a-tooltip>
            <a-tooltip content="重新生成">
              <icon-refresh
                :size="25"
                class="rounded-full p-1 !text-gray-400 hover:bg-gray-100 hover:!text-gray-600 transition cursor-pointer"
                @click.stop="handleRegenerate"
              />
            </a-tooltip>
            <a-tooltip content="点踩">
              <icon-thumb-down
                :size="25"
                class="rounded-full p-1 !text-gray-400 hover:bg-gray-100 hover:!text-gray-600 transition cursor-pointer"
                :class="{ '!text-red-600 bg-red-100': feedbackStatus === 'dislike' }"
                @click.stop="handleFeedback('dislike')"
              />
            </a-tooltip>
            <a-tooltip content="点赞">
              <icon-thumb-up
                :size="25"
                class="rounded-full p-1 !text-gray-400 hover:bg-gray-100 hover:!text-gray-600 transition cursor-pointer"
                :class="{ '!text-red-600 bg-red-100': feedbackStatus === 'like' }"
                @click.stop="handleFeedback('like')"
              />
            </a-tooltip>
            <a-tooltip content="复制">
              <icon-copy
                :size="25"
                class="rounded-full p-1 !text-gray-400 hover:bg-gray-100 hover:!text-gray-600 transition cursor-pointer"
                @click.stop="copyFullContent"
              />
            </a-tooltip>
            <span v-if="contentCopied" class="text-xs text-gray-500">已复制</span>
            <!-- 播放区域（仅 TTS 开启时显示，播放图标 18px） -->
            <template v-if="props.enable_text_to_speech">
              <icon-loading
                v-if="props.audio_loading && !props.is_playing"
                :size="18"
                class="!text-gray-400"
              />
              <a-tooltip v-else-if="props.is_playing" content="暂停播放">
                <icon-pause
                  :size="18"
                  class="!text-blue-600 cursor-pointer hover:!text-blue-500 transition"
                  @click="props.stop_audio_stream?.()"
                />
              </a-tooltip>
              <a-tooltip v-else content="播放">
                <icon-play-circle
                  :size="18"
                  class="!text-gray-400 cursor-pointer hover:!text-gray-600 transition"
                  @click="props.start_audio_stream?.(props.message_id)"
                />
              </a-tooltip>
            </template>
          </div>
        </div>
        <!-- 建议问题 -->
        <div v-if="props.suggested_questions.length > 0" class="flex flex-col gap-2">
          <div
            v-for="(suggested_question, idx) in props.suggested_questions"
            :key="idx"
            class="px-4 py-1.5 border rounded-lg text-gray-700 cursor-pointer hover:bg-gray-50"
            @click="() => emits('selectSuggestedQuestion', suggested_question)"
          >
            {{ suggested_question }}
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.markdown-body {
  font-size: 14px;
  word-break: break-word;
  overflow-wrap: break-word;
}

.markdown-body p {
  margin-bottom: 12px;
}

.markdown-body :deep(pre) {
  padding: 0;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
  background-color: #f6f8fa !important;
}

.markdown-body :deep(code) {
  background-color: #f6f8fa !important;
}

.markdown-body :deep(pre code) {
  white-space: pre-wrap;
  word-break: break-all;
  display: block;
  padding: 16px;
  overflow-x: auto;
  background-color: #f6f8fa !important;
}

.markdown-body :deep(table) {
  width: 100%;
  table-layout: fixed;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  word-break: break-word;
  overflow-wrap: break-word;
}

.markdown-body :deep(.code-block-wrapper) {
  position: relative;
  background-color: #f6f8fa !important;
  border: none;
  box-shadow: none;
}

.markdown-body :deep(.code-block-wrapper .copy-code-btn) {
  background: transparent;
  border: none;
  cursor: pointer;
  font-size: 12px;
  color: #4b5563;
}

.markdown-body :deep(.code-block-wrapper .copy-code-btn:hover) {
  background-color: #e5e7eb;
}

.markdown-body :deep(.hljs) {
  background-color: #f6f8fa !important;
}

.markdown-body .code-block-wrapper {
  position: relative;
  background-color: #f6f8fa !important;
  border: none !important;
}

.markdown-body .code-block-wrapper pre {
  margin-top: 0 !important;
  margin-bottom: 0 !important;
  background-color: #f6f8fa !important;
  border: none !important;
}

.markdown-body .code-block-wrapper code {
  background-color: #f6f8fa !important;
}

.markdown-body .hljs {
  background-color: #f6f8fa !important;
}
</style>
