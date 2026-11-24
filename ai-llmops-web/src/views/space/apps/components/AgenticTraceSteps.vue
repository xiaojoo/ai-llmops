<script setup lang="ts">
// Agentic 重检轨迹步骤块：展示知识库检索开启 agentic 时的多轮 query 重写记录。
// 由 SubAgentDetailPanel 在 Summary tab 中复用。
import { reactive, type PropType } from 'vue'

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

const props = defineProps({
  steps: {
    type: Array as PropType<TraceStep[]>,
    required: true,
  },
  // 展开状态隔离前缀：子任务 sub_task_id 或 'ungrouped'
  keyPrefix: {
    type: String,
    default: 'trace',
  },
  thoughtId: {
    type: [String, Number] as PropType<string | number>,
    default: '',
  },
})

// 某轮长文本（查询/补充查询）是否展开，默认折叠（line-clamp-2）
const expandedMap = reactive<Record<string, boolean>>({})
const expandKey = (round: number) => `${props.keyPrefix}_${props.thoughtId}_r${round}`
const isExpanded = (round: number) => expandedMap[expandKey(round)] || false
const toggle = (round: number) => {
  expandedMap[expandKey(round)] = !expandedMap[expandKey(round)]
}
const isLong = (text: string) => text.length > 100
</script>

<template>
  <div class="bg-blue-50 border border-blue-200 rounded-lg px-3 py-2 mb-2">
    <div class="flex items-center gap-2 mb-1">
      <icon-search class="!text-blue-600" />
      <span class="text-xs font-bold text-blue-700">Agentic 重检轨迹</span>
      <span class="text-xs text-blue-400">共 {{ steps.length }} 轮</span>
    </div>
    <div class="flex flex-col gap-1">
      <div
        v-for="step in steps"
        :key="step.round"
        class="flex items-start gap-2 text-xs"
      >
        <span
          class="shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-white"
          :class="step.sufficient ? 'bg-green-500' : 'bg-amber-500'"
        >{{ step.round }}</span>
        <div class="min-w-0 flex-1">
          <div class="text-gray-700">
            {{ step.strategy }} 策略 · 召回 {{ step.k }} 候选 / 命中 {{ step.hits }}
            <span v-if="!step.sufficient" class="text-amber-600 font-medium">· 不充分（{{ step.score }} 分）</span>
            <span v-else class="text-green-600 font-medium">· 充分（{{ step.score }} 分）</span>
          </div>
          <!-- 本轮实际使用的查询：超长折叠，点击展开 -->
          <div v-if="step.query" class="flex items-start gap-1">
            <div
              class="text-gray-500 break-all cursor-pointer"
              :class="!isExpanded(step.round) && isLong(step.query) ? 'line-clamp-2' : ''"
              @click="isLong(step.query) && toggle(step.round)"
            >
              查询：{{ step.query }}
            </div>
            <span
              v-if="isLong(step.query)"
              class="shrink-0 text-blue-500 cursor-pointer hover:text-blue-600"
              @click="toggle(step.round)"
            >{{ isExpanded(step.round) ? '收起' : '展开' }}</span>
          </div>
          <!-- 补充查询：超长折叠，点击展开 -->
          <div v-if="!step.sufficient && step.missing" class="flex items-start gap-1">
            <div
              class="text-gray-500 break-all cursor-pointer"
              :class="!isExpanded(step.round) && isLong(step.missing) ? 'line-clamp-2' : ''"
              @click="isLong(step.missing) && toggle(step.round)"
            >
              → 补充查询：{{ step.missing }}
            </div>
            <span
              v-if="isLong(step.missing)"
              class="shrink-0 text-blue-500 cursor-pointer hover:text-blue-600"
              @click="toggle(step.round)"
            >{{ isExpanded(step.round) ? '收起' : '展开' }}</span>
          </div>
          <div v-else-if="step.round === 1 && step.sufficient" class="text-gray-400">
            首轮即充分，无需重检
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
