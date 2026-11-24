<script setup lang="ts">
// 运行流程（mockup 时间线形式）：每条 = 图标 + 步骤名（标题）+ 命令胶囊（工具名/模型名/时间/tokens）+ 内容详情（截断）。
// 步骤名与"任务详情"（SubAgentTraceList）共用 thought-display.ts，保证两侧一致；
// 点击步骤可跳转到任务详情（jumpable 时），由父组件联动 SubAgentDetail 高亮定位并展开右侧详情。
// 无进场动画（用户要求取消动画）。
import { computed, type PropType } from 'vue'
import { QueueEvent } from '@/config'
import type { GetDebugConversationMessagesWithPageResponse } from '@/models/app.ts'
import {
  mainExpandedMap,
  planExpandedMap,
  stepContentExpandedMap,
  subTaskExpandedMap,
} from './agent-thought-state'
import { stepAmountOf, stepDetailOf } from './thought-display'

type AgentThought =
  GetDebugConversationMessagesWithPageResponse['data']['list'][number]['agent_thoughts'][number]

const props = defineProps({
  message_id: { type: String, required: true },
  loading: { type: Boolean, required: false, default: false },
  agent_thoughts: {
    type: Array as PropType<
      GetDebugConversationMessagesWithPageResponse['data']['list'][number]['agent_thoughts']
    >,
    required: true,
    default: () => [],
  },
  // 允许点击步骤跳转到任务详情（web-apps/调试预览 传入 true）
  jumpable: { type: Boolean, default: false },
})

const emit = defineEmits<{
  (e: 'step-click', thought: AgentThought): void
}>()

// 主级面板显示隐藏状态
const visible = computed({
  get: () => mainExpandedMap[props.message_id] || false,
  set: (val) => {
    mainExpandedMap[props.message_id] = val
  },
})

// 过滤需要显示的思考步骤（sub_task_plan 已由上方"任务分解计划"卡片独立展示，这里不再重复渲染为步骤；
// 含 error/timeout/stop 以支持失败态徽章）
const filteredThoughts = computed(() => {
  return props.agent_thoughts.filter((item) =>
    [
      QueueEvent.longTermMemoryRecall,
      QueueEvent.agentThought,
      QueueEvent.agentMessage,
      QueueEvent.agentAction,
      QueueEvent.datasetRetrieval,
      QueueEvent.subTaskStart,
      QueueEvent.subTaskEnd,
      QueueEvent.error,
      QueueEvent.timeout,
      QueueEvent.stop,
    ].includes(item.event),
  )
})

// ===== 任务分解计划卡片（sub_task_plan） =====
const planExpanded = computed({
  get: () => planExpandedMap[props.message_id] || false,
  set: (val) => {
    planExpandedMap[props.message_id] = val
  },
})

type SubTaskPlanItem = {
  order?: number
  title?: string
  role_prompt?: string
  expect_output?: string
  required_tools?: string[]
}

const planThought = computed(() =>
  props.agent_thoughts.find((item) => item.event === QueueEvent.subTaskPlan),
)

const planItems = computed<SubTaskPlanItem[]>(() => {
  const thought = planThought.value?.thought
  if (!thought) return []
  try {
    const parsed = JSON.parse(thought)
    return Array.isArray(parsed) ? (parsed as SubTaskPlanItem[]) : []
  } catch {
    // thought 非 JSON 数组（如流式未完成），原样展示
    return []
  }
})

// ===== 按 sub_task_id 分组 =====
type SubTaskGroup = {
  sub_task_id: string
  sub_task_title: string
  thoughts: AgentThought[]
}

const subTaskGroups = computed<SubTaskGroup[]>(() => {
  const groups: SubTaskGroup[] = []
  const indexMap = new Map<string, number>()
  for (const thought of filteredThoughts.value) {
    if (!thought.sub_task_id) continue
    const idx = indexMap.get(thought.sub_task_id)
    const existing = idx !== undefined ? groups[idx] : undefined
    if (existing) {
      existing.thoughts.push(thought)
    } else {
      indexMap.set(thought.sub_task_id, groups.length)
      groups.push({
        sub_task_id: thought.sub_task_id,
        sub_task_title: thought.sub_task_title || `子任务 ${groups.length + 1}`,
        thoughts: [thought],
      })
    }
  }
  return groups
})

// 渲染列表：分组头（子任务任务行）+ 未分组步骤；分组内部步骤由分组行展开渲染
type RenderItem =
  | { kind: 'group-header'; group: SubTaskGroup }
  | { kind: 'step'; thought: AgentThought; index: number }

const renderItems = computed<RenderItem[]>(() => {
  const items: RenderItem[] = []
  const seen = new Set<string>()
  filteredThoughts.value.forEach((thought, index) => {
    if (thought.sub_task_id) {
      if (seen.has(thought.sub_task_id)) return
      seen.add(thought.sub_task_id)
      const group = subTaskGroups.value.find((g) => g.sub_task_id === thought.sub_task_id)
      if (!group) return
      items.push({ kind: 'group-header', group })
    } else {
      items.push({ kind: 'step', thought, index })
    }
  })
  return items
})

// ===== 分组行：展开状态 / 摘要 =====
const isGroupOpen = (sub_task_id: string): boolean =>
  subTaskExpandedMap[`${props.message_id}_${sub_task_id}`] || false

const toggleGroup = (sub_task_id: string) => {
  const key = `${props.message_id}_${sub_task_id}`
  subTaskExpandedMap[key] = !subTaskExpandedMap[key]
}

const groupAmountOf = (group: SubTaskGroup): string => {
  const end = group.thoughts.find((item) => item.event === QueueEvent.subTaskEnd)
  if (end?.latency) {
    let s = `${end.latency.toFixed(2)}s`
    if (end.total_token_count) s += ` · ${end.total_token_count} Tokens`
    return s
  }
  return `${group.thoughts.length} 个事件`
}

// ===== 未分组步骤：详情折叠进 at-line，点击行展开/收起 =====
const stepDetailKey = (thought: AgentThought, index: number): string =>
  `${props.message_id}_step_${thought.id || index}`

const isStepDetailOpen = (thought: AgentThought, index: number): boolean =>
  stepContentExpandedMap[stepDetailKey(thought, index)] || false

const toggleStepDetail = (thought: AgentThought, index: number) => {
  const key = stepDetailKey(thought, index)
  stepContentExpandedMap[key] = !stepContentExpandedMap[key]
}

// ===== 图标（mockup：sparkle/pencil/check/read/chevron，浅色适配） =====
const iconClassOf = (t: AgentThought): string => {
  if (t.event === QueueEvent.subTaskEnd) return 'at-check'
  if ([QueueEvent.error, QueueEvent.timeout, QueueEvent.stop].includes(t.event)) return 'at-close'
  if (t.event === QueueEvent.agentThought || t.event === QueueEvent.agentMessage)
    return 'at-sparkle'
  if (t.event === QueueEvent.agentAction) return 'at-pencil'
  if (t.event === QueueEvent.datasetRetrieval) return 'at-read'
  if (t.event === QueueEvent.longTermMemoryRecall) return 'at-read'
  return 'at-dot'
}

const onStepClick = (thought: AgentThought) => {
  if (props.jumpable) emit('step-click', thought)
}
</script>

<template>
  <div class="flex flex-col rounded-2xl border w-[calc(100%-40px)] overflow-hidden">
    <!-- 运行流程头部 -->
    <div
      :class="`flex items-center justify-between h-10 rounded-2xl bg-gray-100 px-4 text-gray-700 cursor-pointer w-auto ${visible ? 'rounded-bl-none rounded-br-none' : ''}`"
      @click="visible = visible!"
    >
      <div class="flex items-center gap-2">
        <icon-list />
        {{ visible ? '隐藏' : '显示' }}运行流程
      </div>
      <div class="flex items-center gap-2">
        <template v-if="props.loading">
          <icon-loading />
        </template>
        <template v-else>
          <icon-up v-if="visible" />
          <icon-down v-else />
        </template>
      </div>
    </div>

    <!-- 底部内容区（无动画，v-show 即时显隐） -->
    <div v-show="visible" class="flex flex-col bg-white">
      <!-- 时间线：任务分解计划 + 步骤列表（同一条竖线贯穿；展开区保留竖线） -->
      <div v-if="planThought || renderItems.length" class="at-timeline">
        <!-- 任务分解计划（与分组任务行同构：箭头默认向右/展开向下 + 标题 + 命令胶囊，可展开） -->
        <div v-if="planThought" class="at-item" :class="props.jumpable ? 'at-clickable' : ''">
          <div class="at-item-icon">
            <span class="at-icon at-chevron" :class="{ open: planExpanded }"></span>
          </div>
          <div class="at-content">
            <button
              type="button"
              class="at-line at-collapse-button"
              :aria-expanded="planExpanded"
              @click="planExpanded = !planExpanded"
            >
              <span class="at-title">任务分解计划</span>
              <span class="at-pill">共 {{ planItems.length }} 个子任务</span>
            </button>

            <!-- 展开：嵌套时间线 —— 计划子任务（与分组步骤同构：图标列 + 内容列） -->
            <div v-show="planExpanded" class="at-nested">
              <div
                v-for="(item, idx) in planItems"
                :key="`${props.message_id}_plan_${item.order ?? idx}`"
                class="at-item"
              >
                <div class="at-item-icon">
                  <span class="at-icon at-sparkle"></span>
                </div>
                <div class="at-content">
                  <div class="at-line">
                    <span class="at-title">{{ item.title || '未命名子任务' }}</span>
                  </div>
                </div>
              </div>
              <div v-if="planItems.length === 0" class="at-empty">
                {{ planThought?.thought || '-' }}
              </div>
            </div>
          </div>
        </div>

        <!-- 步骤（mockup：图标 + 步骤名 + 命令胶囊 + 内容详情） -->
        <template
          v-for="item in renderItems"
          :key="`${props.message_id}_${item.kind === 'group-header' ? 'group_' + item.group.sub_task_id : 'step_' + (item.thought.id || item.index)}`"
        >
          <!-- 分组任务行（子任务）：箭头默认向右/展开向下 + 标题 + 命令胶囊，可展开 -->
          <div
            v-if="item.kind === 'group-header'"
            class="at-item"
            :class="props.jumpable ? 'at-clickable' : ''"
          >
            <div class="at-item-icon">
              <span
                class="at-icon at-chevron"
                :class="{ open: isGroupOpen(item.group.sub_task_id) }"
              ></span>
            </div>
            <div class="at-content">
              <button
                type="button"
                class="at-line at-collapse-button"
                :aria-expanded="isGroupOpen(item.group.sub_task_id)"
                @click="toggleGroup(item.group.sub_task_id)"
              >
                <span class="at-title">{{ item.group.sub_task_title }}</span>
                <span class="at-pill">{{ groupAmountOf(item.group) }}</span>
              </button>

              <!-- 分组展开：嵌套时间线 —— 步骤图标 + 步骤名 + 命令胶囊 + 内容详情（点击详情跳转） -->
              <div v-show="isGroupOpen(item.group.sub_task_id)" class="at-nested">
                <div
                  v-for="(step, si) in item.group.thoughts"
                  :key="`${props.message_id}_substep_${step.id || si}`"
                  class="at-item"
                >
                  <div class="at-item-icon">
                    <span class="at-icon" :class="iconClassOf(step)"></span>
                  </div>
                  <div class="at-content">
                    <div class="at-line">
                      <span class="at-title">{{ step.event }}</span>
                      <span class="at-pill">{{ stepAmountOf(step) }}</span>
                    </div>
                    <div
                      v-if="stepDetailOf(step)"
                      class="at-subline"
                      :class="props.jumpable ? 'at-clickable' : ''"
                      @click="onStepClick(step)"
                    >
                      {{ stepDetailOf(step) }}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 未分组步骤行（与分组任务行同构：图标 + 步骤名 + 命令胶囊；详情折叠进行内，点击行展开/收起，点击详情跳转任务详情） -->
          <div v-else class="at-item" :class="props.jumpable ? 'at-clickable' : ''">
            <div class="at-item-icon">
              <span
                class="at-icon at-chevron"
                :class="{ open: isStepDetailOpen(item.thought, item.index) }"
              ></span>
            </div>
            <div class="at-content">
              <button
                type="button"
                class="at-line at-collapse-button"
                :aria-expanded="isStepDetailOpen(item.thought, item.index)"
                @click="toggleStepDetail(item.thought, item.index)"
              >
                <span class="at-title">{{ item.thought.event }}</span>
                <span class="at-pill">{{ stepAmountOf(item.thought) }}</span>
              </button>
              <div
                v-if="stepDetailOf(item.thought)"
                v-show="isStepDetailOpen(item.thought, item.index)"
                class="at-subline at-subline-icon"
                :class="props.jumpable ? 'at-clickable' : ''"
                @click="onStepClick(item.thought)"
              >
                <span class="at-icon" :class="iconClassOf(item.thought)"></span>
                <span class="at-subline-text">{{ stepDetailOf(item.thought) }}</span>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ===== 步骤时间线（mockup 结构，浅色适配） ===== */
.at-timeline {
  position: relative;
  margin-top: 2px;
  padding-bottom: 4px;
}

.at-item {
  position: relative;
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  min-height: 39px;
}

.at-item-icon {
  position: relative;
  z-index: 1;
  align-self: start;
  display: flex;
  align-items: center;
  justify-content: center;
  height: 24px;
  margin-top: 4px;
  background: #fff;
}

.at-content {
  min-width: 0;
  padding: 4px 10px 6px 0;
}

.at-line {
  min-height: 24px;
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

/* 标题 = 步骤名称：单行不换行，超宽省略 */
.at-title {
  flex: 1 1 auto;
  min-width: 0;
  color: #374151;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 命令胶囊：工具名 / 模型名 / 时间 · tokens，超宽省略 */
.at-pill {
  flex: none;
  max-width: 45%;
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 9px;
  border-radius: 9999px;
  background: #f3f4f6;
  color: #6b7280;
  font-size: 11.5px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 内容详情：部分信息，单行不换行，超宽省略 */
.at-subline {
  margin-top: 2px;
  color: #9ca3af;
  font-size: 12px;
  line-height: 18px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 未分组步骤行详情：与分组步骤同构（24px 图标列 + 内容列），在内容列内展示 */
.at-subline.at-subline-icon {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  align-items: center;
  width: 100%;
  margin-top: 2px;
}
.at-subline.at-subline-icon .at-icon {
  justify-self: center;
  width: 13px;
  height: 18px;
}
.at-subline.at-subline-icon .at-subline-text {
  min-width: 0;
  padding-right: 10px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 分组展开：嵌套步骤在竖线右侧缩进 */
.at-nested {
  position: relative;
}
/* 展开区竖线：贯穿嵌套各步骤图标中心（left 12px ≈ 嵌套 24px 图标列中心，相对 at-nested） */
.at-nested::before {
  content: '';
  position: absolute;
  left: 12px;
  top: 4px;
  bottom: 4px;
  width: 1px;
  background: #e5e7eb;
}
/* 只有单个计划子任务时：图标替代竖线，不显示 | */
.at-nested.at-nested-noline::before {
  display: none;
}
.at-nested .at-item {
  min-height: 30px;
}
.at-nested .at-item-icon {
  height: 22px;
}
.at-nested .at-content {
  padding-top: 2px;
  padding-bottom: 3px;
}
.at-nested .at-line {
  min-height: 22px;
}

/* 展开区空态（计划子任务为空时展示原文，与内容列对齐） */
.at-empty {
  padding: 6px 10px 8px 24px;
  font-size: 12px;
  line-height: 18px;
  color: #9ca3af;
  word-break: break-all;
}

/* 可点击跳转（作用于详情 at-subline） */
.at-clickable {
  cursor: pointer;
}
.at-clickable:hover {
  color: #2563eb;
}

/* 分组展开按钮 */
.at-collapse-button {
  width: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  text-align: left;
  font: inherit;
  color: inherit;
  cursor: pointer;
}

/* ===== 图标（mockup CSS 图标，浅色适配） ===== */
.at-icon {
  position: relative;
  width: 13px;
  height: 20px;
  flex: none;
  color: #9ca3af;
}

/* sparkle ✦：模型 / LLM 步骤 */
.at-sparkle::before {
  content: '✦';
  position: absolute;
  left: 1px;
  top: 2px;
  color: #9ca3af;
  font-size: 14px;
  line-height: 14px;
}

/* pencil ✎：工具调用 */
.at-pencil {
  transform: rotate(-45deg);
}
.at-pencil::before {
  content: '';
  position: absolute;
  width: 8px;
  height: 3px;
  left: 2px;
  top: 9px;
  border: 1px solid #9ca3af;
  border-radius: 1px;
}
.at-pencil::after {
  content: '';
  position: absolute;
  left: 0;
  top: 9px;
  width: 0;
  height: 0;
  border-top: 2px solid transparent;
  border-bottom: 2px solid transparent;
  border-right: 3px solid #9ca3af;
}

/* check ✓：子任务完成 */
.at-check::before {
  content: '';
  position: absolute;
  width: 5px;
  height: 9px;
  left: 4px;
  top: 4px;
  border-right: 1.5px solid #9ca3af;
  border-bottom: 1.5px solid #9ca3af;
  transform: rotate(45deg);
}

/* read ▢：知识库检索 / 长期记忆 */
.at-read::before {
  content: '';
  position: absolute;
  left: 1px;
  top: 3px;
  width: 11px;
  height: 13px;
  border: 1px solid #9ca3af;
  border-radius: 2px;
}
.at-read::after {
  content: '';
  position: absolute;
  width: 5px;
  height: 1px;
  background: #9ca3af;
  left: 4px;
  top: 8px;
  box-shadow: 0 3px 0 #9ca3af;
}

/* chevron ▸/▾：一级菜单箭头 —— 默认向右（折叠），展开时向下 */
.at-chevron {
  transition: transform 0.16s ease;
  transform: rotate(-90deg);
}
.at-chevron::before {
  content: '';
  position: absolute;
  left: 3px;
  top: 7px;
  width: 6px;
  height: 6px;
  border-right: 1.5px solid #9ca3af;
  border-bottom: 1.5px solid #9ca3af;
  transform: rotate(45deg);
}
.at-chevron.open {
  transform: rotate(0deg);
}

/* close ✕：失败 / 超时 / 停止 */
.at-close::before,
.at-close::after {
  content: '';
  position: absolute;
  left: 6px;
  top: 4px;
  width: 1.5px;
  height: 12px;
  background: #9ca3af;
}
.at-close::before {
  transform: rotate(45deg);
}
.at-close::after {
  transform: rotate(-45deg);
}

/* dot ●：兜底 */
.at-dot::before {
  content: '';
  position: absolute;
  left: 4px;
  top: 7px;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #9ca3af;
}
</style>
