<script setup lang="ts">
/**
 * MessageList — 聊天消息列表（Web 端样式）
 * - 助手消息：头像 + 应用名 + Markdown 正文（代码高亮/复制）+ 点赞/点踩/复制 + ask_user 交互卡片
 * - 用户消息：右对齐蓝色气泡
 */
import { nextTick, onMounted, reactive, ref, watch } from 'vue'
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
import { IconThumbUp, IconThumbDown, IconCopy, IconCheck, IconRefresh, IconEdit, IconLaunch } from '@arco-design/web-vue/es/icon'
import DotFlashing from '../DotFlashing.vue'
import type { AskUserSubmitPayload, ChatMessage } from './types'
import 'github-markdown-css'
import 'highlight.js/styles/github-dark.css'

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

const props = withDefaults(
  defineProps<{
    // 必填（带默认值）：避免模板里 messages.length 触发 TS18048（possibly undefined）
    messages: ChatMessage[]
    /** 应用名（助手消息头部显示） */
    appName?: string
    /** 应用图标 URL */
    appIcon?: string
  }>(),
  {
    messages: () => [],
    appName: '',
    appIcon: '',
  },
)

const emit = defineEmits<{
  feedback: [payload: { message: ChatMessage; feedback: '' | 'like' | 'dislike' }]
  'ask-user-submit': [payload: { message: ChatMessage; payload: AskUserSubmitPayload }]
  /** 重新生成：回发该回答对应的上一条用户输入文本 */
  regenerate: [query: string]
  /** 断点续跑：对已停止/超时/出错但可恢复的消息继续执行 */
  continue: [message: ChatMessage]
}>()

// 消息所属任务是否已终态（停止/取消/超时/出错）：终态消息不再显示"生成中"，避免无限抖点
const isTerminalTask = (m: ChatMessage): boolean => {
  const s = m.status ?? ''
  const rs = m.runStatus ?? ''
  return (
    s === 'stop' || s === 'timeout' || s === 'error' ||
    ['cancelled', 'timed_out', 'failed'].includes(rs)
  )
}

// 终态提示文案（answer 为空时替代"生成中"抖点）
const terminalHint = (m: ChatMessage): string => {
  if (m.runStatus === 'timed_out' || m.status === 'timeout') return '任务执行超时，已中断。可点击「继续执行」从断点续跑。'
  if (m.status === 'stop' || m.runStatus === 'cancelled') return '任务已停止。可点击「继续执行」从断点续跑。'
  return '任务执行出错，已中断。可点击「继续执行」重试。'
}

/** 展示 ask_user 卡片是否应强制只读（任务已终态→不能选，避免"看似可选实则卡住"） */
const askReadonlyFor = (m: ChatMessage): boolean => isTerminalTask(m)

// ===== Markdown =====
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
    // 注意：embed 无 Tailwind，布局必须用内联样式（flex/space-between 等），否则按钮会挤到左边
    return `<div class="code-block-wrapper" style="margin:16px 0; border-radius:8px; overflow:hidden; background-color:#0c0d0f; border:1px solid rgba(255,255,255,0.09);">
      <div style="display:flex; align-items:center; justify-content:space-between; padding:6px 12px; font-size:12px; background-color:#16181b;">
        <span style="font-family:ui-monospace,SFMono-Regular,Consolas,monospace; color:#9aa3b2;">${language}</span>
        <button
          class="copy-code-btn"
          style="display:inline-flex; align-items:center; gap:4px; padding:3px 8px; border-radius:4px; color:#cbd5e1; background:transparent; border:none; cursor:pointer; font-size:12px;"
          data-code-index="${codeIndex}"
          data-code="${md.utils.escapeHtml(code)}"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0;">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
          </svg>
          <span>复制</span>
        </button>
      </div>
      <pre class="hljs" style="background-color:#0c0d0f; margin:0; overflow-x:auto;"><code style="background-color:#0c0d0f; font-family:ui-monospace,SFMono-Regular,Consolas,monospace; font-size:12.5px;">${highlightedCode}</code></pre>
    </div>`
  },
})

md.renderer.rules.fence = (tokens, idx) => {
  const token = tokens[idx]
  if (!token) return ''
  const code = token.content
  const lang = token.info || 'plaintext'
  return (
    md.options.highlight?.(code, lang, '') ||
    `<pre class="hljs" style="background-color:#0c0d0f; margin:0;"><code style="background-color:#0c0d0f;">${md.utils.escapeHtml(code)}</code></pre>`
  )
}

// ===== Markdown 渲染节流 + 分批 =====
// 流式回复时每个 SSE 增量都会改 content，若每次都全量跑 markdown-it + highlight.js（开销大），
// 主线程被占满 → 消息列表滚动卡顿。这里按消息节流：距上次渲染 ≥200ms 立即渲染，否则合并到
// 200ms 后渲染一次（trailing）。流式期间视觉上仍平滑，最终结果一致。
// 初始历史加载：全部消息首次渲染会一次性同步执行（60 条 ≈ 数百 ms 主线程阻塞，
// JCEF 软件渲染下更明显），改为按帧分批渲染（每帧 6 条），首屏立即出现、正文渐进填充。
const renderedHtml = reactive<Record<string, string>>({})
const lastRenderAt = new Map<string, number>()
const pendingTimers = new Map<string, ReturnType<typeof setTimeout>>()
const MD_THROTTLE_MS = 200
const INITIAL_CHUNK = 6
const initialQueue: ChatMessage[] = []
let initialRendering = false

function renderNow(msg: ChatMessage) {
  const id = msg.id
  lastRenderAt.set(id, Date.now())
  renderedHtml[id] = md.render(msg.content || '')
  // 卡片高度由 renderedHtml 决定：流式增长实际发生在本次 markdown 渲染之后。
  // 若正在跟随底部，等 Vue 把新 HTML 写入 DOM（nextTick）再钉一次，避免视图逐帧漂移
  if (followBottom) nextTick(() => scrollToBottom())
}

/** 分批渲染队列（首次渲染的初始历史）；每帧渲染 INITIAL_CHUNK 条。 */
function drainInitialQueue() {
  initialRendering = false
  if (initialQueue.length === 0) return
  const chunk = initialQueue.splice(0, INITIAL_CHUNK)
  chunk.forEach(renderNow)
  initialRendering = true
  requestAnimationFrame(drainInitialQueue)
}

function scheduleMarkdown(msg: ChatMessage) {
  if (!msg || msg.role !== 'assistant') return
  const id = msg.id
  const now = Date.now()
  const last = lastRenderAt.get(id) ?? 0
  if (last > 0) {
    // 已渲染过（含流式更新）：按节流合并
    if (now - last >= MD_THROTTLE_MS) {
      renderNow(msg)
    } else {
      const timer = pendingTimers.get(id)
      if (timer) clearTimeout(timer)
      pendingTimers.set(id, setTimeout(() => renderNow(msg), MD_THROTTLE_MS))
    }
    return
  }
  // 首次渲染：进分批队列，避免初始历史一次性全量同步渲染阻塞主线程
  if (!initialQueue.some((m) => m.id === id)) initialQueue.push(msg)
  if (!initialRendering) {
    initialRendering = true
    requestAnimationFrame(drainInitialQueue)
  }
}

watch(
  () => props.messages,
  (list) => list?.forEach(scheduleMarkdown),
  { deep: true, flush: 'post' },
)

// ===== 滚动控制 =====
// 打开会话时钉在底部（看最新消息）；流式增长时若用户贴近底部则跟随，用户上滚即取消跟随。
const listRef = ref<HTMLElement | null>(null)
const FOLLOW_THRESHOLD = 120
let followBottom = true

function nearBottom(): boolean {
  const el = listRef.value
  if (!el) return false
  return el.scrollHeight - el.scrollTop - el.clientHeight < FOLLOW_THRESHOLD
}

function scrollToBottom() {
  const el = listRef.value
  if (el) el.scrollTop = el.scrollHeight
}

function onScroll() {
  followBottom = nearBottom()
}

// 滚轮灵敏度增强：JCEF 下默认每格滚动量偏小（感受"不灵敏"），按 1.4 倍放大。
// 仅拦截纵向滚轮事件；行/页模式（deltaMode≠0）与无纵向滚动时交给默认处理，
// 避免影响代码块横向滚动等场景。
const WHEEL_BOOST = 1.4
onMounted(() => {
  const el = listRef.value
  if (!el) return
  el.addEventListener(
    'wheel',
    (e: WheelEvent) => {
      if (e.deltaMode !== 0) return
      const dy = e.deltaY
      if (dy === 0) return
      if (el.scrollHeight <= el.clientHeight) return
      e.preventDefault()
      el.scrollTop += dy * WHEEL_BOOST
    },
    { passive: false },
  )
})

// 历史加载（0→N）后滚动到底部；打开即看最新消息
watch(
  () => props.messages.length,
  (len) => {
    if (len > 0 && followBottom) {
      nextTick(() => scrollToBottom())
    }
  },
)

// 流式内容增长：贴近底部时保持钉在底部（O(1) 签名，避免整列表 join）
watch(
  () => {
    const msgs = props.messages
    const last = msgs[msgs.length - 1]
    return msgs.length + ':' + (last ? last.content.length : 0)
  },
  () => {
    if (followBottom) scrollToBottom()
  },
  { flush: 'post' },
)

const handleMarkdownClick = (event: MouseEvent) => {
  const target = event.target as HTMLElement
  const copyBtn = target.closest('.copy-code-btn')
  if (!copyBtn) return
  const code = copyBtn.getAttribute('data-code')
  const codeIndex = copyBtn.getAttribute('data-code-index')
  if (!code || !codeIndex) return
  const decoded = code.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
  void navigator.clipboard.writeText(decoded).catch(() => undefined)
  const btnSpan = copyBtn.querySelector('span')
  if (btnSpan) {
    const original = btnSpan.innerText
    btnSpan.innerText = '已复制'
    setTimeout(() => {
      btnSpan.innerText = original
    }, 2000)
  }
}

// ===== 反馈（点赞/点踩） =====
const feedbackStatus = (m: ChatMessage): 'like' | 'dislike' | null =>
  m.feedback === 'like' || m.feedback === 'dislike' ? m.feedback : null

const handleFeedback = (m: ChatMessage, type: 'like' | 'dislike') => {
  const cur = feedbackStatus(m)
  emit('feedback', { message: m, feedback: cur === type ? '' : type })
}

// ===== 复制完整回答 =====
const copiedId = ref('')
const copyFullContent = async (m: ChatMessage) => {
  try {
    await navigator.clipboard.writeText(m.content)
    copiedId.value = m.id
    setTimeout(() => {
      if (copiedId.value === m.id) copiedId.value = ''
    }, 2000)
  } catch {
    /* 忽略剪贴板失败 */
  }
}

// ===== 重新生成：回发该回答对应的上一条用户输入文本 =====
const handleRegenerate = (m: ChatMessage) => {
  const idx = props.messages.findIndex((x) => x.id === m.id)
  for (let i = idx - 1; i >= 0; i--) {
    const prev = props.messages[i]
    if (prev && prev.role === 'user') {
      emit('regenerate', prev.content)
      return
    }
  }
}

// ===== 复制用户发送的内容 =====
const userCopiedId = ref('')
const copyUserContent = async (m: ChatMessage) => {
  try {
    await navigator.clipboard.writeText(m.content)
    userCopiedId.value = m.id
    setTimeout(() => {
      if (userCopiedId.value === m.id) userCopiedId.value = ''
    }, 2000)
  } catch {
    /* 忽略剪贴板失败 */
  }
}

// ===== 编辑用户消息（点击后内容框变为可输入状态，发送后重新生成） =====
const editingId = ref('')
const editDraft = ref('')
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const startEdit = (m: ChatMessage) => {
  editingId.value = m.id
  editDraft.value = m.content
  nextTick(() => textareaRef.value?.focus())
}
const cancelEdit = () => {
  editingId.value = ''
  editDraft.value = ''
}
const submitEdit = (m: ChatMessage) => {
  const text = editDraft.value.trim()
  if (!text) return
  editingId.value = ''
  emit('regenerate', text) // 复用重新生成流程：回发修改后的文本
}

// ===== ask_user 交互（选项 / 计划确认） =====
// 每条消息的交互状态（按消息 id 索引）
const checkedOrders = ref<Record<string, number[]>>({})
const selectedOption = ref<Record<string, string>>({})
const customText = ref<Record<string, string>>({})
const submitted = ref<Record<string, boolean>>({})

const askDisabled = (m: ChatMessage) =>
  !!m.askUser?.choice || submitted.value[m.id] === true || askReadonlyFor(m)

const getChecked = (m: ChatMessage): number[] => checkedOrders.value[m.id] ?? []

const toggleOrder = (m: ChatMessage, order: number) => {
  if (askDisabled(m)) return
  const list = getChecked(m)
  const idx = list.indexOf(order)
  if (idx === -1) checkedOrders.value[m.id] = [...list, order]
  else checkedOrders.value[m.id] = list.filter((o) => o !== order)
}

const parsePlanChoice = (
  raw: string | undefined,
): { action: 'confirm' | 'replan'; keepOrders: number[] } => {
  if (!raw) return { action: 'confirm', keepOrders: [] }
  if (raw.includes('重新规划') || raw === 'replan') return { action: 'replan', keepOrders: [] }
  try {
    const parsed = JSON.parse(raw) as { action?: string; keep_orders?: number[] }
    if (parsed && typeof parsed === 'object') {
      return {
        action: parsed.action === 'replan' ? 'replan' : 'confirm',
        keepOrders: Array.isArray(parsed.keep_orders) ? parsed.keep_orders : [],
      }
    }
  } catch {
    /* 纯文本回显按确认处理 */
  }
  return { action: 'confirm', keepOrders: [] }
}

const askStatus = (m: ChatMessage): string => {
  if (askReadonlyFor(m)) return '任务已停止，不可再选择'
  if (m.askUser?.choice) {
    if (m.askUser.mode === 'plan') {
      const { action, keepOrders } = parsePlanChoice(m.askUser.choice)
      const label = action === 'replan' ? '已重新规划' : '已确认执行'
      return keepOrders.length > 0 ? `${label}，保留项：${keepOrders.join('、')}` : label
    }
    return `已选：${m.askUser.choice}`
  }
  if (submitted.value[m.id]) return '已提交，继续处理中…'
  return ''
}

const submitPlan = (m: ChatMessage, action: 'confirm' | 'replan') => {
  if (askDisabled(m)) return
  const info = m.askUser
  if (!info) return
  if (action === 'replan' && !(customText.value[m.id] ?? '').trim()) return
  submitted.value[m.id] = true
  emit('ask-user-submit', {
    message: m,
    payload: {
      taskId: info.taskId,
      eventId: info.eventId,
      action,
      keepOrders: action === 'confirm' ? getChecked(m) : [],
      custom: action === 'replan' ? (customText.value[m.id] ?? '').trim() : '',
      skip: false,
    },
  })
}

const submitOption = (m: ChatMessage, payload: { skip?: boolean }) => {
  if (askDisabled(m)) return
  const info = m.askUser
  if (!info) return
  const choice = selectedOption.value[m.id] ?? ''
  const custom = (customText.value[m.id] ?? '').trim()
  if (!payload.skip && !choice && !custom) return
  submitted.value[m.id] = true
  emit('ask-user-submit', {
    message: m,
    payload: {
      taskId: info.taskId,
      eventId: info.eventId,
      choice: choice || custom,
      custom: custom || undefined,
      skip: payload.skip ?? false,
    },
  })
}
</script>

<template>
  <div ref="listRef" class="message-list" @scroll="onScroll">
    <div v-if="messages.length === 0" class="message-list__empty">暂无消息，开始对话吧</div>

    <div
      v-for="m in messages"
      :key="m.id"
      class="message-list__item"
      :class="'message-list__item--' + m.role"
    >
      <!-- ===== 助手消息（无头像/名称，深色卡片） ===== -->
      <template v-if="m.role === 'assistant'">
        <div class="msg-main">
          <!-- 错误 -->
          <div v-if="m.error" class="msg-card msg-card--error">{{ m.error }}</div>
          <!-- 生成中 -->
          <div v-else-if="m.streaming && !m.content.trim()" class="msg-card msg-card--loading">
            <dot-flashing />
          </div>
          <!-- 已终态且无正文：显示终态提示（不再无限"生成中"抖点） -->
          <div
            v-else-if="isTerminalTask(m) && !m.content.trim()"
            class="msg-card msg-card--terminal"
          >
            {{ terminalHint(m) }}
          </div>
          <!-- Markdown 正文（节流渲染，避免流式期滚动卡顿） -->
          <div
            v-else
            class="msg-card markdown-body"
            v-html="renderedHtml[m.id] ?? ''"
            @click="handleMarkdownClick"
          />

          <!-- ask_user 交互卡片 -->
          <div v-if="m.askUser" class="ask-card">
            <div class="ask-question">{{ m.askUser.question }}</div>

            <!-- plan 模式：子任务勾选 + 原因 + 确认执行/重新规划 -->
            <template v-if="m.askUser.mode === 'plan'">
              <div class="ask-plan-list">
                <label
                  v-for="opt in m.askUser.subTaskOptions ?? []"
                  :key="opt.order"
                  class="ask-plan-item"
                  :class="{ 'is-disabled': askDisabled(m) }"
                >
                  <input
                    type="checkbox"
                    :name="'ask-plan-' + m.id"
                    :checked="getChecked(m).includes(opt.order)"
                    :disabled="askDisabled(m)"
                    class="ask-checkbox"
                    @change="toggleOrder(m, opt.order)"
                  />
                  <span class="ask-plan-item__text">
                    <span class="ask-plan-item__title">{{ opt.order }}. {{ opt.title }}</span>
                    <span v-if="opt.role_prompt" class="ask-plan-item__sub">角色/任务：{{ opt.role_prompt }}</span>
                    <span v-if="opt.expect_output" class="ask-plan-item__sub">预期输出：{{ opt.expect_output }}</span>
                  </span>
                </label>
              </div>
              <input
                v-model="customText[m.id]"
                type="text"
                :name="'ask-reason-' + m.id"
                class="ask-input"
                placeholder="输入原因或补充要求…"
                :disabled="askDisabled(m)"
              />
              <div class="ask-footer">
                <span class="ask-status">{{ askStatus(m) }}</span>
                <div class="ask-actions">
                  <button
                    type="button"
                    class="ask-btn ask-btn--ghost"
                    :disabled="askDisabled(m) || !(customText[m.id] ?? '').trim()"
                    @click="submitPlan(m, 'replan')"
                  >
                    重新规划
                  </button>
                  <button
                    type="button"
                    class="ask-btn ask-btn--primary"
                    :disabled="askDisabled(m)"
                    @click="submitPlan(m, 'confirm')"
                  >
                    确认执行
                  </button>
                </div>
              </div>
            </template>

            <!-- option 模式：选项 + 自定义 + 提交/跳过 -->
            <template v-else>
              <div class="ask-options">
                <button
                  v-for="(opt, idx) in m.askUser.options ?? []"
                  :key="idx"
                  type="button"
                  class="ask-option"
                  :class="{ 'is-selected': selectedOption[m.id] === opt }"
                  :disabled="askDisabled(m)"
                  @click="selectedOption[m.id] = opt"
                >
                  {{ opt }}
                </button>
              </div>
              <input
                v-if="m.askUser.allowCustom"
                v-model="customText[m.id]"
                type="text"
                :name="'ask-custom-' + m.id"
                class="ask-input"
                placeholder="输入自定义选项…"
                :disabled="askDisabled(m)"
              />
              <div class="ask-footer">
                <span class="ask-status">{{ askStatus(m) }}</span>
                <div class="ask-actions">
                  <button
                    type="button"
                    class="ask-btn ask-btn--ghost"
                    :disabled="askDisabled(m)"
                    @click="submitOption(m, { skip: true })"
                  >
                    跳过
                  </button>
                  <button
                    type="button"
                    class="ask-btn ask-btn--primary"
                    :disabled="askDisabled(m)"
                    @click="submitOption(m, {})"
                  >
                    提交
                  </button>
                </div>
              </div>
            </template>
          </div>

          <!-- 操作行：耗时/token | 点踩 点赞 复制 -->
          <div class="msg-actions">
            <span class="msg-actions__meta">
              <icon-check v-if="m.latency" :size="12" class="msg-meta-icon" />
              <template v-if="m.latency">{{ m.latency.toFixed(2) }}s</template>
              <template v-if="m.totalTokenCount"> · {{ m.totalTokenCount }} Tokens</template>
            </span>
            <span class="msg-actions__btns">
              <!-- 断点续跑：仅可恢复消息显示，与重新生成等图标一致 -->
              <icon-launch
                v-if="m.canResume"
                :size="20"
                class="msg-action-btn"
                title="继续执行"
                @click="emit('continue', m)"
              />
              <icon-refresh
                :size="20"
                class="msg-action-btn"
                title="重新生成"
                @click="handleRegenerate(m)"
              />
              <icon-thumb-down
                :size="20"
                class="msg-action-btn"
                title="点踩"
                :class="{ 'is-active is-dislike': feedbackStatus(m) === 'dislike' }"
                @click="handleFeedback(m, 'dislike')"
              />
              <icon-thumb-up
                :size="20"
                class="msg-action-btn"
                title="点赞"
                :class="{ 'is-active is-like': feedbackStatus(m) === 'like' }"
                @click="handleFeedback(m, 'like')"
              />
              <icon-copy
                :size="20"
                class="msg-action-btn"
                title="复制"
                @click="copyFullContent(m)"
              />
              <span v-if="copiedId === m.id" class="msg-copied"><icon-check :size="12" />已复制</span>
            </span>
          </div>
        </div>
      </template>

      <!-- ===== 用户消息（右对齐蓝色气泡 + 复制/编辑） ===== -->
      <template v-else>
        <div class="user-msg" :class="{ 'is-editing': editingId === m.id }">
          <!-- 编辑态：内容框变为可输入，含取消/发送 -->
          <div v-if="editingId === m.id" class="user-edit-box">
            <textarea
              ref="textareaRef"
              v-model="editDraft"
              class="user-edit-input"
              placeholder="修改内容..."
              rows="3"
              spellcheck="false"
              @keydown.enter.exact.prevent="submitEdit(m)"
              @keydown.esc="cancelEdit"
            />
            <div class="user-edit-footer">
              <span class="user-edit-tip">编辑消息</span>
              <div class="user-edit-actions">
                <button type="button" class="user-edit-btn user-edit-btn--ghost" @click="cancelEdit">取消</button>
                <button type="button" class="user-edit-btn user-edit-btn--primary" @click="submitEdit(m)">发送</button>
              </div>
            </div>
          </div>
          <!-- 展示态：气泡 + 复制/编辑 -->
          <template v-else>
            <div class="user-bubble">
              <div v-if="m.files && m.files.length > 0" class="user-bubble__files">
                <span v-for="f in m.files" :key="f.id" class="user-bubble__file" :title="f.label">
                  {{ f.label }}
                </span>
              </div>
              <div class="user-bubble__text">{{ m.content }}</div>
            </div>
            <div class="user-msg-actions">
              <icon-edit :size="20" class="msg-action-btn" title="编辑" @click="startEdit(m)" />
              <icon-check
                v-if="userCopiedId === m.id"
                :size="20"
                class="msg-action-btn"
                title="已复制"
              />
              <icon-copy
                v-else
                :size="20"
                class="msg-action-btn"
                title="复制"
                @click="copyUserContent(m)"
              />
            </div>
          </template>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.message-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 12px 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  /* 阻止滚动链传播（滚到底/顶时事件不冒泡到外层滚动容器） */
  overscroll-behavior: contain;
  /* 滚动条样式由全局 agent-chat.css 提供（细、无箭头）；此处不写标准属性，
     避免覆盖 webkit 自定义滚动条 */
}

.message-list__empty {
  margin-top: 24px;
  text-align: center;
  font-size: 12px;
  color: var(--text-muted);
}

.message-list__item {
  display: flex;
  gap: 10px;
  /* 布局/样式隔离：单条消息内部变化（流式高度增长）不引发整列表 relayout；
     不使用 content-visibility（会让浏览器用估算高度计算滚动指标，导致滚动条失真），
     contain 不参与尺寸估算，滚动条保持准确 */
  contain: layout style;
}

.message-list__item--user {
  justify-content: flex-end;
}

/* ===== 助手消息 ===== */
.msg-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 6px;
}

.msg-card {
  width: 100%;
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 12px;
  padding: 12px 14px;
  /* 深色卡片（比 IDE 背景更深），白色文字 */
  background: #111214;
  color: #ffffff;
  font-size: 13px;
  line-height: 1.6;
  word-break: break-word;
}

.msg-card--error {
  border-color: rgba(220, 38, 38, 0.4);
  background: #1a1012;
  color: #fca5a5;
}

.msg-card--loading {
  min-height: 36px;
  display: flex;
  align-items: center;
  /* 等待回复的三个点：左 padding 25px */
  padding-left: 25px;
}

/* 已终态（超时/停止/出错）且无正文：灰字提示，取代无限"生成中" */
.msg-card--terminal {
  min-height: 36px;
  display: flex;
  align-items: center;
  padding-left: 25px;
  color: #9aa3b2;
  font-size: 12.5px;
}

/* ===== ask_user 卡片（深色适配） ===== */
.ask-card {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 10px;
  border: 1px solid rgba(96, 165, 250, 0.35);
  border-radius: 12px;
  background: #141d2e;
  padding: 12px 14px;
  /* 与上方输出内容间隔 16px（容器 gap 6px + 本项 margin-top 10px） */
  margin-top: 10px;
}

.ask-question {
  font-size: 13px;
  font-weight: 500;
  color: #ffffff;
}

.ask-plan-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.ask-plan-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 8px;
  background: #1a2334;
  padding: 8px 12px;
  font-size: 13px;
  color: #e5e7eb;
  cursor: pointer;
  transition: border-color 0.15s ease;
}

.ask-plan-item:hover {
  border-color: #93c5fd;
}

.ask-plan-item.is-disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.ask-checkbox {
  margin-top: 3px;
  width: 15px;
  height: 15px;
  accent-color: #2563eb;
  flex-shrink: 0;
}

.ask-plan-item__text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ask-plan-item__title {
  font-weight: 500;
}

.ask-plan-item__sub {
  font-size: 12px;
  line-height: 1.5;
  color: #9aa3b2;
}

.ask-options {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.ask-option {
  border: 1px solid rgba(255, 255, 255, 0.16);
  background: #1a2334;
  color: #d1d5db;
  font-size: 13px;
  padding: 6px 12px;
  border-radius: 8px;
  transition:
    border-color 0.15s ease,
    background 0.15s ease,
    color 0.15s ease;
}

.ask-option:hover {
  border-color: #60a5fa;
  color: #93c5fd;
}

.ask-option.is-selected {
  border-color: #2563eb;
  background: #2563eb;
  color: #ffffff;
}

.ask-option:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.ask-input {
  width: 100%;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 8px;
  background: #1a2334;
  padding: 6px 10px;
  font-size: 13px;
  color: #ffffff;
  outline: none;
  box-sizing: border-box;
  transition: border-color 0.15s ease;
}

.ask-input::placeholder {
  color: #8a93a3;
}

.ask-input:focus {
  border-color: #2563eb;
}

.ask-input:disabled {
  background: #141b28;
  cursor: not-allowed;
}

.ask-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.ask-status {
  font-size: 12px;
  color: #9aa3b2;
}

.ask-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.ask-btn {
  border-radius: 8px;
  padding: 6px 14px;
  font-size: 13px;
  transition: opacity 0.15s ease;
}

.ask-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.ask-btn--ghost {
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: transparent;
  color: #cbd5e1;
}

.ask-btn--ghost:hover:not(:disabled) {
  border-color: rgba(255, 255, 255, 0.35);
  color: #ffffff;
}

.ask-btn--primary {
  border: none;
  background: #2563eb;
  color: #ffffff;
}

.ask-btn--primary:hover:not(:disabled) {
  background: #1d4ed8;
}

/* ===== 操作行 ===== */
.msg-actions {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 2px;
}

.msg-actions__meta {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: #9ca3af;
}

.msg-meta-icon {
  color: #9ca3af;
}

.msg-actions__btns {
  display: flex;
  align-items: center;
  gap: 2px;
}

.msg-action-btn {
  border-radius: 50%;
  padding: 3px;
  color: #9ca3af;
  transition:
    background 0.15s ease,
    color 0.15s ease;
}

.msg-action-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #e0e0e0;
}

.msg-action-btn.is-active.is-like {
  color: #dc2626;
  background: #fee2e2;
}

.msg-action-btn.is-active.is-dislike {
  color: #dc2626;
  background: #fee2e2;
}

.msg-copied {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 11px;
  color: #9aa3b2;
}

/* ===== 用户消息 ===== */
.user-msg {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  max-width: 78%;
  min-width: 0;
}

/* 编辑态：让输入框横向撑满消息区宽度（.user-msg 在 flex 行里，需显式 width:100% 才会拉伸） */
.user-msg.is-editing {
  width: 100%;
  max-width: 100%;
}

.user-bubble {
  max-width: 100%;
  background: #dbeafe;
  border: 1px solid #bfdbfe;
  color: #1f2937;
  font-size: 13px;
  line-height: 1.6;
  padding: 8px 12px;
  border-radius: 12px;
  word-break: break-word;
  white-space: pre-wrap;
}

.user-msg-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  margin-top: 2px;
}

/* 编辑态：内容框变为可输入，含取消/发送 */
.user-edit-box {
  width: 100%;
  background: #1d1e20;
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 12px;
  padding: 8px;
}

.user-edit-input {
  width: 100%;
  min-height: 60px;
  max-height: 180px;
  resize: vertical;
  background: transparent;
  border: none;
  outline: none;
  color: #e0e0e0;
  font-size: 13px;
  line-height: 1.6;
  font-family: inherit;
  white-space: pre-wrap;
  word-break: break-word;
}

.user-edit-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 6px;
}

.user-edit-tip {
  font-size: 11px;
  color: #8b8f99;
}

.user-edit-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.user-edit-btn {
  padding: 3px 12px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  border: 1px solid transparent;
}

.user-edit-btn--ghost {
  background: transparent;
  color: #cbd5e1;
  border-color: rgba(255, 255, 255, 0.2);
}

.user-edit-btn--ghost:hover {
  border-color: rgba(255, 255, 255, 0.35);
  color: #ffffff;
}

.user-edit-btn--primary {
  background: #2563eb;
  color: #ffffff;
}

.user-edit-btn--primary:hover {
  background: #1d4ed8;
}

.user-bubble__files {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 6px;
}

.user-bubble__file {
  display: inline-block;
  max-width: 100%;
  padding: 2px 8px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.65);
  border: 1px solid #bfdbfe;
  font-size: 11.5px;
  color: #334155;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Markdown 局部微调（深色卡片 + 白字；代码块保持深色高亮） */
.message-list :deep(.markdown-body) {
  font-size: 13px;
  background: transparent;
  color: #ffffff;
}

.message-list :deep(.markdown-body p),
.message-list :deep(.markdown-body li),
.message-list :deep(.markdown-body h1),
.message-list :deep(.markdown-body h2),
.message-list :deep(.markdown-body h3),
.message-list :deep(.markdown-body h4),
.message-list :deep(.markdown-body h5),
.message-list :deep(.markdown-body h6),
.message-list :deep(.markdown-body td),
.message-list :deep(.markdown-body th),
.message-list :deep(.markdown-body blockquote) {
  color: #ffffff;
}

.message-list :deep(.markdown-body blockquote) {
  border-left-color: rgba(255, 255, 255, 0.25);
}

.message-list :deep(.markdown-body a) {
  color: #60a5fa;
}

.message-list :deep(.markdown-body hr) {
  background-color: rgba(255, 255, 255, 0.15);
}

.message-list :deep(.markdown-body table tr) {
  background-color: transparent;
  border-top-color: rgba(255, 255, 255, 0.15);
}

.message-list :deep(.markdown-body table th),
.message-list :deep(.markdown-body table td) {
  border-color: rgba(255, 255, 255, 0.18);
}

.message-list :deep(.markdown-body code) {
  background-color: rgba(255, 255, 255, 0.12);
  color: #e5e7eb;
}

.message-list :deep(.markdown-body p) {
  margin-bottom: 10px;
}

.message-list :deep(.markdown-body pre) {
  padding: 0;
  margin: 0;
  background-color: #0c0d0f !important;
}

.message-list :deep(.markdown-body pre code) {
  white-space: pre-wrap;
  word-break: break-all;
  display: block;
  padding: 12px;
  overflow-x: auto;
  background-color: #0c0d0f !important;
}

.message-list :deep(.markdown-body table) {
  width: 100%;
  table-layout: fixed;
}

.message-list :deep(.markdown-body th),
.message-list :deep(.markdown-body td) {
  word-break: break-word;
  overflow-wrap: break-word;
}

.message-list :deep(.code-block-wrapper) {
  background-color: #0c0d0f !important;
}

.message-list :deep(.copy-code-btn) {
  background: transparent;
  border: none;
  cursor: pointer;
  font-size: 12px;
  color: #cbd5e1;
}

.message-list :deep(.copy-code-btn:hover) {
  background-color: #2a2d31;
}

.message-list :deep(.hljs) {
  background-color: #0c0d0f !important;
}
</style>
