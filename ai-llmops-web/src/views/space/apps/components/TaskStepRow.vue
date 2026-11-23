<script setup lang="ts">
// Task Rows 叶子步骤行：状态徽章 + 类型徽章 + 步骤名 + 摘要 + 状态胶囊。
// 步骤名与任务详情共用 thought-display.ts（保证与 SubAgentTraceList 一致）。
import { computed, type PropType } from 'vue'
import { QueueEvent } from '@/config'
import TaskStatusBadge from './TaskStatusBadge.vue'
import { stepAmountOf, stepLabelOf, typeClassOf, typeLabelOf } from './thought-display'

type AgentThought = {
  id: string
  position: number
  event: string
  thought: string
  observation: string
  tool: string
  latency: number
  total_token_count?: number
  total_price?: number
  created_at: number
  sub_task_id?: string | null
  sub_task_title?: string
}

const props = defineProps({
  thought: {
    type: Object as PropType<AgentThought>,
    required: true,
  },
})

// 状态徽章：完成/智能体消息=绿勾 / 失败=红叉 / 进行中=绿色圆环 / 未开始=绿色圆环
const status = computed<'done' | 'failed' | 'running' | 'pending'>(() => {
  const e = props.thought.event
  if (e === QueueEvent.subTaskEnd) return 'done'
  if ([QueueEvent.error, QueueEvent.timeout, QueueEvent.stop].includes(e)) return 'failed'
  if (e === QueueEvent.subTaskStart) return 'running'
  if (e === QueueEvent.agentMessage) return 'done'
  return 'pending'
})

const pill = computed<{ text: string; tone: 'green' | 'red' } | null>(() => {
  if (status.value === 'done') return { text: '已完成', tone: 'green' }
  if (status.value === 'failed') return { text: '失败', tone: 'red' }
  return null
})
</script>

<template>
  <div class="flex h-11 w-full items-center gap-2.5 pl-2.5 pr-[30px] hover:bg-gray-50">
    <task-status-badge :status="status" :step="thought.position ?? ''" />
    <span class="stt-badge-mini" :class="typeClassOf(thought)">{{ typeLabelOf(thought) }}</span>
    <span class="min-w-0 flex-1 truncate text-[13px] font-medium text-gray-700">{{ stepLabelOf(thought) }}</span>
    <span class="shrink-0 max-w-[42%] truncate text-[12.5px] text-gray-500 tabular-nums">
      {{ stepAmountOf(thought) }}
    </span>
    <span
      v-if="pill"
      class="inline-flex h-[22px] shrink-0 items-center rounded-full px-2 text-[11.5px] font-medium"
      :class="pill.tone === 'green' ? 'bg-green-50 text-green-600' : 'bg-red-50 text-red-600'"
    >
      {{ pill.text }}
    </span>
  </div>
</template>

<style scoped>
/* 类型徽章（与任务详情 stt-badge 同款配色，缩小为行内尺寸） */
.stt-badge-mini {
  flex: none;
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 9.5px;
  line-height: 15px;
  font-weight: 600;
}
.stt-badge-mini.model {
  background: #f3eafa;
  color: #7c4d9f;
}
.stt-badge-mini.ctx {
  background: #eaf8ef;
  color: #16a05d;
}
.stt-badge-mini.tool {
  background: #fff2df;
  color: #e68a18;
}
</style>
