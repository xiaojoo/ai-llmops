<script setup lang="ts">
/**
 * MessageInput — 透明多行输入框
 * Enter 发送 / Shift+Enter 换行；focus 无蓝色 outline，仅微弱的边框高亮
 *
 * @ 提及项目文件：词边界输入 @ 打开项目文件下拉（数据来自 Java 桥 listProjectFiles），
 * ↑/↓ 选择、Enter/点击选中（把 @过滤词 替换为文件相对路径）、Esc/失焦关闭。
 * 仅负责触发与文本替换；文件列表由父级经 mentionFiles prop 提供，过滤词经 mentionQuery 事件上报。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { FileMentionItem } from './types'

const props = withDefaults(
  defineProps<{
    modelValue: string
    placeholder?: string
    disabled?: boolean
    /** @ 提及：Java 桥返回的项目文件列表（父级按 mentionQuery 拉取） */
    mentionFiles?: FileMentionItem[]
    /** @ 提及：父级正在拉取文件列表 */
    mentionLoading?: boolean
  }>(),
  {
    placeholder: '描述要构建的内容',
    disabled: false,
    mentionFiles: () => [],
    mentionLoading: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  submit: []
  /** @ 提及触发词变化：null = 关闭下拉；非 null = 当前过滤词 */
  mentionQuery: [query: string | null]
  /** @ 提及选中某个文件：把路径上报父级，父级在发送时随 file_ids 上传该文件 */
  mentionSelect: [path: string]
}>()

const textareaRef = ref<HTMLTextAreaElement | null>(null)

// 窄视口（<250px，与工具栏左侧隐藏同一阈值）placeholder 缩略为 "…"，避免占满输入框
const isNarrow = ref(false)
let mql: MediaQueryList | null = null
const effectivePlaceholder = computed(() => (isNarrow.value ? '…' : props.placeholder))
const onMqlChange = (e: MediaQueryListEvent) => {
  isNarrow.value = e.matches
}
onMounted(() => {
  mql = window.matchMedia('(max-width: 250px)')
  isNarrow.value = mql.matches
  mql.addEventListener('change', onMqlChange)
})
onBeforeUnmount(() => {
  mql?.removeEventListener('change', onMqlChange)
  mql = null
})

/** 自适应高度：内容变化时撑满 */
watch(
  () => props.modelValue,
  () => {
    autoGrow()
  },
)

function autoGrow() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${el.scrollHeight}px`
}

// ===== @ 提及项目文件 =====

/** 当前生效的 @ 提及：{ start: '@' 所在位置, caret: 触发时光标, query: 过滤词 } */
const mention = ref<{ start: number; caret: number; query: string } | null>(null)
const highlightIndex = ref(0)

/**
 * 从光标位置向前找词边界 @：'@' 前是开头或空白才视为触发；
 * '@' 与光标之间不允许有空白（有空白说明过滤词已结束）。
 * 返回 null 表示当前没有生效的提及。
 */
function computeMention(text: string, caret: number): { start: number; caret: number; query: string } | null {
  if (caret <= 0) return null
  let i = caret - 1
  while (i >= 0) {
    // charAt 越界返回 ""，避免 noUncheckedIndexedAccess 下 text[i] 为 string|undefined
    const ch = text.charAt(i)
    if (ch === '@') {
      const prev = text.charAt(i - 1)
      if (prev === '' || /\s/.test(prev)) {
        return { start: i, caret, query: text.slice(i + 1, caret) }
      }
      return null // '@' 在单词中间，不是提及触发
    }
    if (/\s/.test(ch)) return null // 未到 '@' 先遇空白 → 无生效提及
    i--
  }
  return null
}

function closeMention() {
  if (mention.value !== null) {
    mention.value = null
    emit('mentionQuery', null)
  }
  highlightIndex.value = 0
}

function selectFile(file: FileMentionItem) {
  const m = mention.value
  if (!m || props.disabled) return
  const before = props.modelValue.slice(0, m.start)
  const after = props.modelValue.slice(m.caret)
  const text = before + file.path + after
  const caret = before.length + file.path.length
  emit('update:modelValue', text)
  mention.value = null
  emit('mentionQuery', null)
  emit('mentionSelect', file.path)
  highlightIndex.value = 0
  nextTick(() => {
    const el = textareaRef.value
    if (el) {
      el.focus()
      el.setSelectionRange(caret, caret)
    }
    autoGrow()
  })
}

function moveHighlight(delta: number) {
  const len = props.mentionFiles.length
  if (len === 0) return
  highlightIndex.value = (highlightIndex.value + delta + len) % len
}

function onInput(e: Event) {
  const el = e.target as HTMLTextAreaElement
  const text = el.value
  emit('update:modelValue', text)
  autoGrow()
  if (props.disabled) return
  const m = computeMention(text, el.selectionStart)
  if (m) {
    const queryChanged = mention.value === null || mention.value.query !== m.query
    mention.value = m
    if (queryChanged) {
      highlightIndex.value = 0
      emit('mentionQuery', m.query)
    }
  } else {
    closeMention()
  }
}

function onKeydown(e: KeyboardEvent) {
  if (mention.value !== null && !props.disabled) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      moveHighlight(1)
      return
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      moveHighlight(-1)
      return
    }
    if (e.key === 'Enter' && !e.isComposing) {
      e.preventDefault()
      const target = props.mentionFiles[highlightIndex.value]
      if (target) selectFile(target)
      return
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      closeMention()
      return
    }
    // 其余按键（含 IME 组词中的 Enter）走默认行为，不关闭下拉
    return
  }
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    emit('submit')
  }
}

function onBlur() {
  // 点击下拉项用 mousedown.prevent 阻止失焦；其他原因失焦（点工具栏等）关闭下拉
  closeMention()
}

function focusInput() {
  textareaRef.value?.focus()
}

defineExpose({ focusInput })
</script>

<template>
  <textarea
    ref="textareaRef"
    name="agent-chat-input"
    class="message-input"
    :value="props.modelValue"
    :placeholder="effectivePlaceholder"
    :disabled="props.disabled"
    rows="1"
    spellcheck="false"
    @input="onInput"
    @keydown="onKeydown"
    @blur="onBlur"
  ></textarea>
  <div v-if="mention !== null && !props.disabled" class="mention-dropdown">
    <div v-if="props.mentionLoading" class="mention-empty">加载项目文件…</div>
    <div v-else-if="props.mentionFiles.length === 0" class="mention-empty">无匹配文件</div>
    <template v-else>
      <div
        v-for="(f, i) in props.mentionFiles"
        :key="f.path"
        class="mention-item"
        :class="{ 'is-active': i === highlightIndex }"
        @mousedown.prevent="selectFile(f)"
        @mouseenter="highlightIndex = i"
      >
        <span class="mention-item__name">{{ f.name }}</span>
        <span class="mention-item__dir">{{ f.path }}</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.message-input {
  flex: 1;
  width: 100%;
  min-height: 40px;
  max-height: 120px;
  resize: none;
  background: transparent;
  border: none;
  outline: none;
  color: var(--text-primary);
  font-family: inherit;
  font-size: 13px;
  line-height: 1.5;
  padding: 8px 12px;
  overflow-y: auto;
}

.message-input::placeholder {
  color: var(--text-muted);
  opacity: 1;
}

.message-input:focus {
  outline: none;
  box-shadow: none;
}

/* ===== @ 提及下拉 ===== */
.mention-dropdown {
  position: absolute;
  left: 10px;
  right: 10px;
  bottom: calc(100% + 6px);
  z-index: 30;
  max-height: 240px;
  overflow-y: auto;
  background: #1d1e20;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 8px;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.45);
  padding: 4px;
  box-sizing: border-box;
}

.mention-empty {
  padding: 10px 12px;
  font-size: 12px;
  color: var(--text-muted);
}

.mention-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 5px;
  cursor: pointer;
  min-width: 0;
}

.mention-item.is-active {
  background: #2a2d31;
}

.mention-item__name {
  flex-shrink: 0;
  font-size: 12px;
  color: #e0e0e0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 45%;
}

.mention-item__dir {
  flex: 1;
  min-width: 0;
  font-size: 11px;
  color: #8a93a3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
