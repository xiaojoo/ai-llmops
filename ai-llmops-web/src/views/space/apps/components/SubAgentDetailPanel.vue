<script setup lang="ts">
// 任务详情右侧面板：head（badge + 标题 + 关闭）+ tabs（Summary/Preview/Raw/Source）
// LangSmith 风格：展示模型名、LLM 输入 messages、完整输出、工具调用声明、token、耗时。
import { computed, type PropType } from 'vue'
import { QueueEvent } from '@/config'
import AgenticTraceSteps from './AgenticTraceSteps.vue'

type TraceStep = {
  round: number
  strategy: string
  query: string
  k: number
  hits: number
  sufficient: boolean
  score: number
  missing: string
}

type AgentThought = {
  id: string
  position: number
  event: string
  thought: string
  observation: string
  llm_output?: string
  tool_calls?: { name?: string; args?: Record<string, unknown>; id?: string; type?: string }[]
  message?: unknown[]
  tool: string
  tool_input: Record<string, unknown>
  trace?: TraceStep[]
  latency: number
  total_token_count?: number
  total_price?: number
  model_name?: string
  created_at: number
  sub_task_id?: string | null
  sub_task_title?: string
}

const props = defineProps({
  selected: {
    type: Object as PropType<AgentThought>,
    required: true,
  },
  // 所属区段标题，如「轮次 1 · 子任务 1」/「轮次 2」
  groupTitle: {
    type: String,
    default: '',
  },
  groupStatus: {
    type: String,
    default: '—',
  },
  tab: {
    type: String,
    default: 'Summary',
  },
  open: {
    type: Boolean,
    default: true,
  },
})

const emit = defineEmits<{
  (e: 'update:tab', tab: string): void
  (e: 'close'): void
}>()

const TABS = ['Summary', 'Preview', 'Raw', 'Source']

// ===== 类型徽章映射（model=紫 / tool=橙 / ctx=绿） =====
const typeClass = computed(() => {
  const event = props.selected.event
  if (event === QueueEvent.agentMessage || event === QueueEvent.agentThought) return 'model'
  if (event === QueueEvent.agentAction || event === QueueEvent.datasetRetrieval) return 'tool'
  return 'ctx'
})
const typeLabel = computed(() =>
  typeClass.value === 'model' ? 'MODEL' : typeClass.value === 'tool' ? 'TOOL' : 'CONTEXT',
)

const isErrorEvent = computed(() =>
  [QueueEvent.error, QueueEvent.timeout, QueueEvent.stop].includes(props.selected.event),
)

// 格式化工具输入/返回内容：优先美化 JSON
const formatDetail = (value: unknown): string => {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'string') {
    try {
      return JSON.stringify(JSON.parse(value), null, 2)
    } catch {
      return value
    }
  }
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

const toolCallNames = computed(() => {
  const calls = props.selected.tool_calls || []
  if (!calls.length) return ''
  return calls.map((c) => c.name || '?').join(', ')
})

const metaRows = computed(() => {
  const t = props.selected
  const rows = [
    { label: '事件', value: t.event },
    { label: '步骤', value: t.event === QueueEvent.agentThought ? 'LLM 调用' : t.event === QueueEvent.agentMessage ? 'LLM 输出' : '' },
  ]
  if (t.model_name) rows.push({ label: '模型', value: t.model_name })
  if (t.tool) rows.push({ label: '工具', value: t.tool })
  if (toolCallNames.value) rows.push({ label: '工具调用', value: toolCallNames.value })
  rows.push({ label: '位置', value: props.groupTitle || '—' })
  rows.push({ label: '状态', value: props.groupStatus })
  rows.push({ label: '耗时', value: `${(t.latency || 0).toFixed(2)}s` })
  if (t.total_token_count) rows.push({ label: 'Tokens', value: String(t.total_token_count) })
  if (t.total_price) rows.push({ label: '费用', value: String(t.total_price) })
  return rows
})

const previewText = computed(() => {
  const t = props.selected
  if (t.event === QueueEvent.agentThought || t.event === QueueEvent.agentMessage)
    return t.llm_output || t.thought || t.observation || '—'
  if (t.event === QueueEvent.agentAction || t.event === QueueEvent.datasetRetrieval)
    return formatDetail(t.observation)
  if (t.thought) return t.thought
  return t.observation || '—'
})

const rawPayload = computed(() =>
  JSON.stringify(
    {
      id: props.selected.id,
      event: props.selected.event,
      model_name: props.selected.model_name || '',
      tool: props.selected.tool || '',
      tool_input: props.selected.tool_input || {},
      tool_calls: props.selected.tool_calls || [],
      observation: props.selected.observation || '',
      llm_output: props.selected.llm_output || '',
      latency: props.selected.latency,
      total_token_count: props.selected.total_token_count ?? 0,
      total_price: props.selected.total_price ?? 0,
      created_at: props.selected.created_at,
      sub_task_id: props.selected.sub_task_id ?? null,
      sub_task_title: props.selected.sub_task_title ?? '',
      metadata: { position: props.selected.position },
    },
    null,
    2,
  ),
)

const traceSteps = computed(() => props.selected.trace || [])
const hasToolInput = computed(() => {
  const input = props.selected.tool_input
  return !!input && typeof input === 'object' && Object.keys(input).length > 0
})
const hasMessages = computed(() => Array.isArray(props.selected.message) && props.selected.message.length > 0)
</script>

<template>
  <aside class="stt-detail" :class="{ open }">
    <div class="stt-detail-head">
      <div class="stt-detail-title">
        <span class="stt-badge" :class="typeClass">{{ typeLabel }}</span>
        <span class="txt">{{ groupTitle ? `${groupTitle} · 事件` : '事件' }}</span>
      </div>
      <button class="stt-close" @click="emit('close')">×</button>
    </div>
    <div class="stt-detail-tabs">
      <button
        v-for="t in TABS"
        :key="t"
        class="stt-dtab"
        :class="{ active: tab === t }"
        @click="emit('update:tab', t)"
      >
        {{ t }}
      </button>
    </div>
    <div class="stt-detail-scroll">
      <!-- Summary -->
      <template v-if="tab === 'Summary'">
        <div v-if="isErrorEvent" class="stt-err">
          {{ selected.observation || selected.thought || '执行异常' }}
        </div>
        <div class="stt-meta">
          <template v-for="row in metaRows" :key="row.label">
            <span class="stt-label">{{ row.label }}</span>
            <span class="stt-value">{{ row.value }}</span>
          </template>
        </div>
        <agentic-trace-steps
          v-if="selected.event === QueueEvent.datasetRetrieval && traceSteps.length"
          :steps="traceSteps"
          :key-prefix="selected.sub_task_id || 'ungrouped'"
          :thought-id="selected.id || selected.position"
        />
        <div class="stt-preview-title">Preview ›</div>
        <div class="stt-markdown">{{ previewText }}</div>
      </template>

      <!-- Preview -->
      <template v-else-if="tab === 'Preview'">
        <div class="stt-preview-title">Preview</div>
        <div class="stt-markdown">{{ previewText }}</div>
      </template>

      <!-- Raw -->
      <template v-else-if="tab === 'Raw'">
        <div class="stt-preview-title">Raw payload</div>
        <pre class="stt-code">{{ rawPayload }}</pre>
      </template>

      <!-- Source -->
      <template v-else>
        <div class="stt-preview-title">Source</div>
        <div v-if="selected.model_name" class="stt-block">
          <div class="cap">模型</div>
          <pre>{{ selected.model_name }}</pre>
        </div>
        <div v-if="hasMessages" class="stt-block">
          <div class="cap">LLM 输入（messages）</div>
          <pre>{{ formatDetail(selected.message) }}</pre>
        </div>
        <div v-if="toolCallNames" class="stt-block">
          <div class="cap">工具调用声明</div>
          <pre>{{ formatDetail(selected.tool_calls) }}</pre>
        </div>
        <div v-if="hasToolInput" class="stt-block">
          <div class="cap">工具输入</div>
          <pre>{{ formatDetail(selected.tool_input) }}</pre>
        </div>
        <div class="stt-block">
          <div class="cap">工具返回</div>
          <pre>{{ formatDetail(selected.observation) || '—' }}</pre>
        </div>
        <div v-if="selected.llm_output || selected.thought" class="stt-block">
          <div class="cap">LLM 输出</div>
          <pre>{{ selected.llm_output || selected.thought }}</pre>
        </div>
        <div v-if="!hasToolInput && !selected.observation && !selected.llm_output && !selected.thought" class="stt-block">
          <div class="cap">内容</div>
          <pre>{{ selected.thought || 'No source attached.' }}</pre>
        </div>
      </template>
    </div>
  </aside>
</template>
