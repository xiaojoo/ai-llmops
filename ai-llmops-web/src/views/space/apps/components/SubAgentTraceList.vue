<script setup lang="ts">
// 任务详情左侧轨迹列表：按轮次（消息）分组，每轮 = 任务分解计划区段 + 子任务（Turn）区段 + 未分组事件区段。
// 事件行：dot + 类型徽章（MODEL/TOOL/CONTEXT）+ 步骤名 + 内容摘要（与运行流程共用 thought-display 命名）。
// 支持搜索过滤；选中行高亮；行带 id（stt-row-<thoughtId>）供外部聚焦滚动定位。
import { computed, ref, type PropType } from 'vue'
import { QueueEvent } from '@/config'
import type { TraceRound, TraceThought } from './SubAgentDetail.vue'
import {
  escapeHtml,
  isErrorEvent,
  rowContentOf,
  typeClassOf,
  typeLabelOf,
} from './thought-display'

const props = defineProps({
  rounds: {
    type: Array as PropType<TraceRound[]>,
    default: () => [],
  },
  query: {
    type: String,
    default: '',
  },
  selectedId: {
    type: String as PropType<string | null>,
    default: null,
  },
})

const emit = defineEmits<{
  (e: 'select', id: string): void
}>()

// 任务分解计划展开状态（按轮次）
const planExpanded = ref<Record<string, boolean>>({})
const togglePlan = (messageId: string) => {
  planExpanded.value = { ...planExpanded.value, [messageId]: !planExpanded.value[messageId] }
}
const isPlanExpanded = (messageId: string): boolean => planExpanded.value[messageId] ?? true

// ===== 文本工具（escape + 搜索高亮） =====
const highlight = (text: string, q: string): string => {
  const safe = escapeHtml(String(text))
  const queryTrim = q.trim()
  if (!queryTrim) return safe
  const escaped = queryTrim.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return safe.replace(new RegExp(escaped, 'gi'), (m) => `<mark class="stt-hl">${m}</mark>`)
}

// ===== 子任务组状态 =====
const statusText = (group: TraceRound['groups'][number]): string => {
  if (group.thoughts.some((item) => item.event === QueueEvent.subTaskEnd)) return '已完成'
  if (group.thoughts.some((item) => item.event === QueueEvent.subTaskStart)) return '进行中'
  return '未开始'
}
const statusClass = (status: string): string =>
  status === '已完成' ? 'done' : status === '进行中' ? 'running' : 'pending'
const latencyOf = (group: TraceRound['groups'][number]): number =>
  group.thoughts.find((item) => item.event === QueueEvent.subTaskEnd)?.latency ?? 0

// ===== 搜索过滤 =====
const matchesQuery = (t: TraceThought): boolean => {
  const q = props.query.trim().toLowerCase()
  if (!q) return true
  const hay = [t.thought, t.observation, t.llm_output, t.tool, t.event, t.sub_task_title, t.model_name]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
  return hay.includes(q)
}
const visibleThoughts = (group: TraceRound['groups'][number]): TraceThought[] =>
  group.thoughts.filter(matchesQuery)
const visibleRounds = computed(() =>
  props.rounds
    .map((r) => ({
      ...r,
      groups: r.groups.filter((g) => visibleThoughts(g).length > 0),
      ungrouped: r.ungrouped.filter(matchesQuery),
    }))
    .filter((r) => r.groups.length > 0 || r.ungrouped.length > 0 || r.planItems.length > 0),
)

const totalVisible = computed(() =>
  visibleRounds.value.reduce(
    (sum, r) =>
      sum + r.groups.reduce((s, g) => s + visibleThoughts(g).length, 0) + r.ungrouped.length,
    0,
  ),
)
const emptyText = computed(() => {
  if (props.rounds.length === 0) return '当前会话暂无轨迹数据'
  if (totalVisible.value === 0) return '没有找到匹配的消息。'
  return ''
})

const hasPlan = (r: TraceRound): boolean => r.planItems.length > 0
</script>

<template>
  <div class="stt-trace-scroll">
    <!-- 轮次区段 -->
    <section
      v-for="round in visibleRounds"
      :key="round.messageId"
      class="stt-turn"
    >
      <div class="stt-turn-number">轮次 {{ round.index }}</div>
      <div class="stt-turn-content">
        <!-- 轮次头：用户提问 + 状态 -->
        <div class="stt-turn-head">
          <span class="title">{{ round.query || '(空提问)' }}</span>
          <span class="meta">{{ round.events.length }} 个事件</span>
          <span v-if="round.answer" class="meta">已回复</span>
        </div>

        <!-- 任务分解计划 -->
        <template v-if="hasPlan(round)">
          <div class="stt-turn-head" @click="togglePlan(round.messageId)">
            <span class="stt-caret">{{ isPlanExpanded(round.messageId) ? '▾' : '▸' }}</span>
            <span class="title">任务分解计划</span>
            <span class="meta">共 {{ round.planItems.length }} 项</span>
          </div>
          <div v-show="isPlanExpanded(round.messageId)" class="stt-plan">
            <div
              v-for="(item, idx) in round.planItems"
              :key="`plan_${round.messageId}_${item.order ?? idx}`"
              class="stt-plan-item"
            >
              <span class="no">{{ item.order ?? idx + 1 }}.</span>
              <span>{{ item.title || '未命名子任务' }}</span>
            </div>
          </div>
        </template>

        <!-- 子任务（Turn）区段 -->
        <template v-for="(group, gi) in round.groups" :key="group.sub_task_id">
          <div class="stt-turn-head">
            <span class="title">{{ group.sub_task_title }}</span>
            <span class="status" :class="statusClass(statusText(group))">{{ statusText(group) }}</span>
            <span class="meta">{{ visibleThoughts(group).length }} 个事件</span>
            <span class="meta">耗时 {{ latencyOf(group).toFixed(2) }}s</span>
          </div>
          <div
            v-for="t in visibleThoughts(group)"
            :id="`stt-row-${t.id}`"
            :key="t.id"
            class="stt-message"
            :class="{ selected: selectedId === t.id }"
            @click="emit('select', t.id)"
          >
            <span class="stt-dot"></span>
            <span class="stt-badge" :class="typeClassOf(t)">{{ typeLabelOf(t) }}</span>
            <span
              class="stt-content"
              :class="{ err: isErrorEvent(t), 'stt-clamp': t.event === QueueEvent.agentMessage }"
              v-html="highlight(rowContentOf(t), props.query)"
            ></span>
          </div>
        </template>

        <!-- 未分组事件区段（含 LLM 调用/输出/记忆/ask_user 等全部轨迹） -->
        <template v-if="round.ungrouped.length">
          <div class="stt-turn-head">
            <span class="title">其他事件</span>
            <span class="meta">共 {{ round.ungrouped.length }} 个</span>
          </div>
          <div
            v-for="t in round.ungrouped"
            :id="`stt-row-${t.id}`"
            :key="t.id"
            class="stt-message"
            :class="{ selected: selectedId === t.id }"
            @click="emit('select', t.id)"
          >
            <span class="stt-dot"></span>
            <span class="stt-badge" :class="typeClassOf(t)">{{ typeLabelOf(t) }}</span>
            <span
              class="stt-content"
              :class="{ err: isErrorEvent(t), 'stt-clamp': t.event === QueueEvent.agentMessage }"
              v-html="highlight(rowContentOf(t), props.query)"
            ></span>
          </div>
        </template>
      </div>
    </section>

    <div v-if="emptyText" class="stt-empty">{{ emptyText }}</div>
  </div>
</template>
