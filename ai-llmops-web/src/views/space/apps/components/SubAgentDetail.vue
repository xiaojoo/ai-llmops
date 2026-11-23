<script setup lang="ts">
// 任务详情视图（当前上下文全部轨迹）：toolbar（统计 + 搜索）+ 时间轴 + 左侧轨迹列表 + 右侧详情面板。
// 与旧版差异：不再只展示"最新一条含子任务的消息"，而是展示当前会话上下文里所有消息的完整轨迹
// （每条消息 = 一轮，各自含 LLM 调用/输出、工具调用、子任务等事件）。
// 支持外部聚焦：focusMessageId/focusThoughtId 命中后选中 + 高亮 + 展开右侧详情面板。
import { computed, nextTick, ref, watch, type PropType } from 'vue'
import { QueueEvent } from '@/config'
import SubAgentTraceList from './SubAgentTraceList.vue'
import SubAgentDetailPanel from './SubAgentDetailPanel.vue'
import './subagent-trace.css'

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

export type TraceThought = {
  id: string
  position: number
  event: string
  thought: string
  observation: string
  llm_output?: string
  tool_calls?: { name?: string; args?: Record<string, unknown>; id?: string; type?: string }[]
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

export type TraceMessage = {
  id: string
  query?: string
  answer?: string
  agent_thoughts: TraceThought[]
}

type PlanItem = {
  order?: number
  title?: string
  role_prompt?: string
  expect_output?: string
  required_tools?: string[]
}

type SubTaskGroup = {
  sub_task_id: string
  sub_task_title: string
  thoughts: TraceThought[]
}

export type TraceRound = {
  messageId: string
  index: number // 1-based 轮次
  query: string
  answer: string
  planItems: PlanItem[]
  groups: SubTaskGroup[]
  ungrouped: TraceThought[]
  events: TraceThought[] // groups 内事件 + ungrouped（时间轴用）
}

const props = defineProps({
  // 当前上下文全部消息（最新在前，与对话列表一致）
  messages: {
    type: Array as PropType<TraceMessage[]>,
    required: true,
    default: () => [],
  },
  // 外部聚焦（运行流程点击跳转）
  focusMessageId: { type: String as PropType<string | null>, default: null },
  focusThoughtId: { type: String as PropType<string | null>, default: null },
  focusNonce: { type: Number, default: 0 },
  // 子任务聚焦过滤：非空时任务详情只展示该子任务的轨迹（与全量视图同构渲染）
  filterSubTaskId: { type: String as PropType<string | null>, default: null },
})

const query = ref('')
const selectedId = ref<string | null>(null)
const detailTab = ref('Summary')
const detailOpen = ref(false)

// ===== 窄视口搜索：搜索框收起为图标，点击弹出浮层搜索框（浮在 stt-stat 上，失焦隐藏） =====
const searchOpen = ref(false)
const searchInputEl = ref<HTMLInputElement | null>(null)

const toggleSearch = () => {
  searchOpen.value = !searchOpen.value
  if (searchOpen.value) {
    nextTick(() => searchInputEl.value?.focus())
  }
}

// 焦点移出整个移动搜索区域时收起浮层
const onSearchFocusOut = (e: FocusEvent) => {
  const wrap = e.currentTarget as HTMLElement
  if (!wrap.contains(e.relatedTarget as Node | null)) {
    searchOpen.value = false
  }
}

// ===== 事件解析（LLM 步骤 / 工具 / 子任务 / 记忆 / ask_user 全部纳入轨迹） =====
const EVENT_WHITELIST = [
  QueueEvent.longTermMemoryRecall,
  QueueEvent.agentThought,
  QueueEvent.agentMessage,
  QueueEvent.agentAction,
  QueueEvent.datasetRetrieval,
  QueueEvent.subTaskStart,
  QueueEvent.subTaskEnd,
  QueueEvent.askUser,
  QueueEvent.error,
  QueueEvent.timeout,
  QueueEvent.stop,
]

const parsePlanItems = (thoughts: TraceThought[]): PlanItem[] => {
  const thought = thoughts.find((item) => item.event === QueueEvent.subTaskPlan)?.thought
  if (!thought) return []
  try {
    const parsed = JSON.parse(thought)
    return Array.isArray(parsed) ? (parsed as PlanItem[]) : []
  } catch {
    return []
  }
}

// 按 sub_task_id 分组（保持首次出现顺序）
const groupThoughts = (thoughts: TraceThought[]): SubTaskGroup[] => {
  const result: SubTaskGroup[] = []
  const indexMap = new Map<string, number>()
  for (const thought of thoughts) {
    if (!thought.sub_task_id) continue
    const idx = indexMap.get(thought.sub_task_id)
    const existing = idx !== undefined ? result[idx] : undefined
    if (existing) {
      existing.thoughts.push(thought)
    } else {
      indexMap.set(thought.sub_task_id, result.length)
      result.push({
        sub_task_id: thought.sub_task_id,
        sub_task_title: thought.sub_task_title || `子任务 ${result.length + 1}`,
        thoughts: [thought],
      })
    }
  }
  return result
}

// 未分组事件（无 sub_task_id 的所有轨迹事件，含 LLM 步骤——非编排场景也能看到完整轨迹）
const ungroupedEvents = (thoughts: TraceThought[]): TraceThought[] =>
  thoughts.filter(
    (item) =>
      !item.sub_task_id &&
      EVENT_WHITELIST.includes(item.event) &&
      item.event !== QueueEvent.subTaskPlan,
  )

// ===== 构建轮次（消息顺序：最新在前 → 展示时反转，最早的轮次在最上） =====
const rounds = computed<TraceRound[]>(() => {
  const sorted = [...props.messages].reverse()
  const filterId = props.filterSubTaskId
  const filtering = !!filterId && filterId.trim() !== ''
  return sorted.map((msg, i) => {
    const thoughts = msg.agent_thoughts || []
    if (filtering) {
      // 子任务聚焦：只展示该子任务分组内的轨迹事件（子 Agent 的 LLM/工具/步骤均带
      // sub_task_id 桥接）；不混入编排主任务的未分组步骤，保证"该子任务的对话"纯净。
      // planItems 保留——该子任务所在的计划方案仍作为轮次上下文展示。
      const group = groupThoughts(thoughts).find(
        (g) => String(g.sub_task_id) === filterId,
      )
      if (!group) return null
      return {
        messageId: msg.id,
        index: i + 1,
        query: msg.query || '',
        answer: msg.answer || '',
        planItems: parsePlanItems(thoughts),
        groups: [group],
        ungrouped: [],
        events: [...group.thoughts],
      }
    }
    const groups = groupThoughts(thoughts)
    const ungrouped = ungroupedEvents(thoughts)
    return {
      messageId: msg.id,
      index: i + 1,
      query: msg.query || '',
      answer: msg.answer || '',
      planItems: parsePlanItems(thoughts),
      groups,
      ungrouped,
      events: [...groups.flatMap((g) => g.thoughts), ...ungrouped],
    }
  }).filter((round): round is TraceRound => round !== null)
})

// 时间轴/统计的事件集合（全部轮次）
const allEvents = computed<TraceThought[]>(() =>
  rounds.value.flatMap((r) => r.events),
)

const stats = computed(() => {
  const subs = new Set(allEvents.value.map((t) => t.sub_task_id).filter(Boolean)).size
  const tools = allEvents.value.filter(
    (t) => t.event === QueueEvent.agentAction || t.event === QueueEvent.datasetRetrieval,
  ).length
  const dur = rounds.value.reduce((sum, r) => {
    const end = r.groups
      .flatMap((g) => g.thoughts)
      .find((t) => t.event === QueueEvent.subTaskEnd)
    return sum + (end?.latency || 0)
  }, 0)
  return { subs, events: allEvents.value.length, tools, dur, rounds: rounds.value.length }
})

// ===== 选中事件 & 详情面板 =====
const roundOf = (id: string): TraceRound | undefined =>
  rounds.value.find((r) => r.events.some((t) => t.id === id))

const selected = computed(
  () => allEvents.value.find((t) => t.id === selectedId.value) ?? null,
)

const groupOf = (id: string): SubTaskGroup | undefined =>
  rounds.value
    .flatMap((r) => r.groups)
    .find((g) => g.thoughts.some((t) => t.id === id))

const selectedGroupTitle = computed(() => {
  if (!selected.value) return ''
  const round = roundOf(selected.value.id)
  const prefix = round ? `轮次 ${round.index}` : '其他'
  const g = groupOf(selected.value.id)
  if (!g) return prefix
  const gi = round?.groups.findIndex((x) => x.sub_task_id === g.sub_task_id) ?? -1
  return `${prefix} · 子任务 ${gi + 1}`
})

const statusText = (group: SubTaskGroup): string => {
  if (group.thoughts.some((item) => item.event === QueueEvent.subTaskEnd)) return '已完成'
  if (group.thoughts.some((item) => item.event === QueueEvent.subTaskStart)) return '进行中'
  return '未开始'
}
const selectedStatus = computed(() => {
  if (!selected.value) return '—'
  const g = groupOf(selected.value.id)
  return g ? statusText(g) : '—'
})

const onSelect = (id: string) => {
  selectedId.value = id
  detailOpen.value = true
}

// 数据就绪后自动选中第一个事件（对齐 trace.html 默认打开详情；immediate 时 prev 为 undefined）
watch(
  () => allEvents.value.length,
  (len, prev) => {
    if ((prev === 0 || prev === undefined) && len > 0 && !selectedId.value) {
      const first = allEvents.value[0]
      if (first) {
        selectedId.value = first.id
        detailOpen.value = true
      }
    }
  },
  { immediate: true },
)

// 外部聚焦（运行流程点击跳转）：选中 + 展开面板 + 滚动定位高亮
// 同时监听 allEvents.length：组件由 chat 视图切换挂载时 focusState 已就绪，
// 但 allEvents 可能尚未构建完成，等数据就绪后（length 变化）再次执行聚焦。
watch(
  () => [props.focusThoughtId, props.focusNonce, allEvents.value.length] as const,
  ([thoughtId]) => {
    if (!thoughtId) return
    const target = allEvents.value.find((t) => t.id === thoughtId)
    if (!target) return
    selectedId.value = thoughtId
    detailOpen.value = true
    nextTick(() => {
      document.getElementById(`stt-row-${thoughtId}`)?.scrollIntoView({
        block: 'center',
        behavior: 'auto',
      })
    })
  },
  { immediate: true },
)

// ===== 时间轴 tick =====
const tickClass = (t: TraceThought): string => {
  if (t.event === QueueEvent.agentMessage || t.event === QueueEvent.agentThought) return 'model'
  if (t.event === QueueEvent.agentAction || t.event === QueueEvent.datasetRetrieval) return 'tool'
  return 'ctx'
}
const tickLabel = (t: TraceThought): string =>
  tickClass(t) === 'model' ? 'MODEL' : tickClass(t) === 'tool' ? 'TOOL' : 'CONTEXT'
const tickLeft = (i: number): string =>
  `${3 + (i / Math.max(allEvents.value.length - 1, 1)) * 94}%`
const turnLabelOf = (t: TraceThought): string => {
  const round = roundOf(t.id)
  const prefix = round ? `轮次 ${round.index}` : '其他'
  if (!t.sub_task_id) return prefix
  const g = groupOf(t.id)
  const gi = round?.groups.findIndex((x) => x.sub_task_id === g?.sub_task_id) ?? -1
  return `${prefix} · 子任务 ${gi + 1}`
}
</script>

<template>
  <div class="subagent-trace">
    <!-- toolbar：统计 + 搜索 -->
    <div class="stt-toolbar">
      <div class="stt-stats">
        <span class="stt-stat">◷ 耗时 <b>{{ stats.dur ? `${stats.dur.toFixed(1)}s` : '—' }}</b></span>
        <span class="stt-stat">▤ 轮次 <b>{{ stats.rounds }}</b></span>
        <span class="stt-stat">▤ 子任务 <b>{{ stats.subs }}</b></span>
        <span class="stt-stat">▤ 事件 <b>{{ stats.events }}</b></span>
        <span class="stt-stat">⌬ 工具 <b>{{ stats.tools }}</b></span>
      </div>
      <label class="stt-search stt-search-desktop"><span>⌕</span><input v-model="query" placeholder="搜索" autocomplete="off" /></label>
      <!-- 窄视口：搜索框收起为图标，点击弹出搜索框浮在统计栏上，失焦隐藏 -->
      <div class="stt-search-mobile" @focusout="onSearchFocusOut">
        <button
          type="button"
          class="stt-search-toggle"
          :class="{ open: searchOpen }"
          :aria-expanded="searchOpen"
          aria-label="搜索"
          @click="toggleSearch"
        >
          ⌕
        </button>
        <div v-show="searchOpen" class="stt-search-pop">
          <input
            ref="searchInputEl"
            v-model="query"
            placeholder="搜索"
            autocomplete="off"
          />
        </div>
      </div>
    </div>

    <!-- 时间轴：图例 + tick（全部轮次） -->
    <div class="stt-timeline">
      <div class="stt-legend">
        <span><i class="stt-i-model"></i>模型</span>
        <span><i class="stt-i-tool"></i>工具</span>
        <span><i class="stt-i-ctx"></i>上下文</span>
      </div>
      <div class="stt-track">
        <span
          v-for="(e, i) in allEvents"
          :key="e.id || i"
          class="stt-tick"
          :class="[tickClass(e), { active: selectedId === e.id }]"
          :style="{ left: tickLeft(i) }"
          :title="`${turnLabelOf(e)} · ${tickLabel(e)}`"
          @click="onSelect(e.id)"
        ></span>
      </div>
    </div>

    <!-- body：左右分栏——左侧轨迹列表，右侧详情面板常驻（不悬浮覆盖，不再弹遮罩） -->
    <div class="stt-body">
      <main class="stt-main">
        <sub-agent-trace-list
          :rounds="rounds"
          :query="query"
          :selected-id="selectedId"
          @select="onSelect"
        />
      </main>
      <!-- 右列：仅当"选中事件且面板打开"时显示。
           × 关闭（detailOpen=false）或未选中时整体隐藏，左列表占满剩余宽度；
           点击左侧事件重新打开。 -->
      <sub-agent-detail-panel
        v-if="selected && detailOpen"
        :selected="selected"
        :group-title="selectedGroupTitle"
        :group-status="selectedStatus"
        :tab="detailTab"
        :open="detailOpen"
        @update:tab="detailTab = $event"
        @close="detailOpen = false"
      />
    </div>
  </div>
</template>
