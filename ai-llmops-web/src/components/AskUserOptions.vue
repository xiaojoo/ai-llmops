<script setup lang="ts">
import { computed, ref, watch } from 'vue'

type SubTaskOption = {
  order: number
  title: string
  role_prompt?: string
  expect_output?: string
  // 依赖的前置子任务 order；后端按它分批调度并把前置产出喂给后置。
  // 勾掉一个前置会连带让依赖它的子任务拿不到输入，所以要在界面上看得见。
  depends_on?: number[]
}

type SubmittedPayload = {
  taskId: string
  choice?: string
  action?: 'confirm' | 'replan'
  keepOrders?: number[]
  custom?: string
  skip: boolean
  eventId: string
}

const props = withDefaults(
  defineProps<{
    question: string
    options?: string[]
    allowCustom?: boolean
    taskId: string
    eventId: string
    choice: string
    mode?: 'option' | 'plan'
    subTaskOptions?: SubTaskOption[]
    requiresReason?: boolean
    // 外部强制只读：任务已终态(停止/超时/出错)时，不再提供勾选/提交，避免"看似可选实则卡住"
    readonly?: boolean
  }>(),
  {
    mode: 'option',
    requiresReason: false,
    readonly: false,
  },
)

const emit = defineEmits<{
  (e: 'submitted', payload: SubmittedPayload): void
}>()

// 当前高亮选项 / 自定义输入 / 已勾选子任务 order / 是否已提交 / 提交中
const selected = ref('')
const customText = ref('')
const submitted = ref(false)
const submitting = ref(false)

// 回显模式：choice 非空（历史消息或已由后端回写）时只读展示
const isHistory = computed(() => !!props.choice)

// 禁用 = 历史回显 / 已提交 / 提交中 / 外部强制只读（终态任务）
const disabled = computed(
  () => isHistory.value || submitted.value || submitting.value || props.readonly,
)

// plan 模式回显：choice 为后端 republish 的 JSON（{"action":"confirm","keep_orders":[...]}）或旧纯文本，
// 解析出 action 与保留项 order（历史刷新后据此还原勾选态与回显文案）
const parsePlanChoice = (raw: string): { action: 'confirm' | 'replan'; keepOrders: number[] } => {
  if (!raw) return { action: 'confirm', keepOrders: [] }
  if (raw.includes('重新规划') || raw === 'replan') return { action: 'replan', keepOrders: [] }
  try {
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed === 'object') {
      return {
        action: parsed.action === 'replan' ? 'replan' : 'confirm',
        keepOrders: Array.isArray(parsed.keep_orders) ? parsed.keep_orders : [],
      }
    }
  } catch {
    /* 非 JSON 纯文本（旧载荷）按确认处理 */
  }
  return { action: 'confirm', keepOrders: [] }
}

// 历史回显时按 choice 还原勾选态；交互态 choice 为空 → 全不选
const checkedOrders = ref<number[]>(parsePlanChoice(props.choice).keepOrders)

// choice 回填/变化时同步勾选项（修复间歇性"确认后灰色卡片不显示保留项"）：
// 确认后后端用同一 event_id republish 带 choice，eventId watch 不会触发；
// 若组件恰在确认瞬间重挂载且 choice 尚未回填，checkedOrders 会停留在空，
// 这里在 choice 到达/变化时补一次同步。
watch(
  () => props.choice,
  (val) => {
    if (val) checkedOrders.value = parsePlanChoice(val).keepOrders
  },
)

// 新的 ask_user 事件（eventId 变化，如 agent 连续追问下一问）到来时复位交互态——
// 组件按消息复用，上一问 submitted=true 残留会把新问题的选项/按钮全部禁用，
// 用户无法选择 → agent 一直等待。同 eventId 的带 choice 重发
// （后端回写回显）不触发复位，保持已提交回显。
watch(
  () => props.eventId,
  () => {
    submitted.value = false
    submitting.value = false
    selected.value = ''
    customText.value = ''
    checkedOrders.value = parsePlanChoice(props.choice).keepOrders
  },
)

// plan 模式：需要原因（重新规划）且未填原因时禁用"重新规划"按钮
const replanDisabled = computed(() => props.requiresReason && !customText.value.trim())

// plan 模式回显文案：按 choice 内容区分"重新规划 / 确认执行"
const planEchoLabel = computed(() => {
  const { action } = parsePlanChoice(props.choice)
  return action === 'replan' ? '重新规划' : '确认执行'
})

// plan 模式勾选/取消某个子任务
const toggleOrder = (order: number) => {
  if (disabled.value) return
  const idx = checkedOrders.value.indexOf(order)
  if (idx === -1) checkedOrders.value.push(order)
  else checkedOrders.value.splice(idx, 1)
}

// plan 模式提交：confirm 保留勾选项且不带 custom（填了原因的用户应走"重新规划"，
// 否则后端 `action=="replan" or custom` 会把确认静默转成重拆）；replan 全不保留（原因走 custom）
const handlePlanSubmit = (action: 'confirm' | 'replan') => {
  if (disabled.value) return
  if (action === 'replan' && replanDisabled.value) return
  submitted.value = true
  submitting.value = true
  if (action === 'confirm') {
    emit('submitted', {
      taskId: props.taskId,
      action: 'confirm',
      keepOrders: [...checkedOrders.value],
      custom: '',
      skip: false,
      eventId: props.eventId,
    })
  } else {
    emit('submitted', {
      taskId: props.taskId,
      action: 'replan',
      keepOrders: [],
      custom: customText.value.trim(),
      skip: false,
      eventId: props.eventId,
    })
  }
}

// 点击选项：仅选中，不自动提交（与计划确认保持一致——需再点"提交"才继续，避免误触直接恢复）
const handleOptionClick = (option: string) => {
  if (disabled.value) return
  selected.value = option
}

// 提交：优先取选中选项，否则取自定义输入
const handleSubmit = () => {
  if (disabled.value) return
  if (!selected.value && !customText.value.trim()) return
  submit()
}

const submit = () => {
  submitted.value = true
  submitting.value = true
  const choice = selected.value || customText.value.trim()
  const payload: {
    taskId: string
    choice: string
    custom?: string
    skip: boolean
    eventId: string
  } = {
    taskId: props.taskId,
    choice,
    skip: false,
    eventId: props.eventId,
  }
  // 汇总歧义等场景：选项 + 自定义原因一起提交（custom 非空才带，保持旧载荷不变）
  const custom = customText.value.trim()
  if (custom) payload.custom = custom
  emit('submitted', payload)
}

const handleSkip = () => {
  if (disabled.value) return
  submitted.value = true
  submitting.value = true
  emit('submitted', { taskId: props.taskId, choice: '', skip: true, eventId: props.eventId })
}

// 复位提交状态：父级 choice 接口调用失败时调用，恢复按钮可点击以便重试
function reset() {
  submitted.value = false
  submitting.value = false
}

defineExpose({ reset })
</script>

<template>
  <div
    class="w-[calc(100%-38px)] flex flex-col gap-2.5 rounded-2xl border border-blue-200 bg-blue-50/60 px-4 py-3"
  >
    <div class="text-sm font-medium text-gray-800">{{ question }}</div>

    <!-- ===== plan 模式：子任务勾选列表 + 原因输入 + 确认执行/重新规划 ===== -->
    <template v-if="mode === 'plan'">
      <div class="flex flex-col gap-1.5">
        <label
          v-for="opt in subTaskOptions ?? []"
          :key="opt.order"
          class="flex cursor-pointer items-start gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 transition-colors hover:border-blue-300"
          :class="{ 'cursor-not-allowed opacity-60': disabled }"
        >
          <input
            type="checkbox"
            :checked="checkedOrders.includes(opt.order)"
            :disabled="disabled"
            class="mt-0.5 h-4 w-4 accent-blue-600"
            @change="toggleOrder(opt.order)"
          />
          <span class="flex flex-col gap-0.5">
            <span class="font-medium">{{ opt.order }}. {{ opt.title }}</span>
            <span v-if="opt.depends_on?.length" class="text-xs leading-relaxed text-gray-500">
              依赖：{{ opt.depends_on.map((d) => `#${d}`).join('、') }}（前置完成后才执行，并带上其产出）
            </span>
            <span v-if="opt.role_prompt" class="text-xs leading-relaxed text-gray-500">
              角色/任务：{{ opt.role_prompt }}
            </span>
            <span v-if="opt.expect_output" class="text-xs leading-relaxed text-gray-500">
              预期输出：{{ opt.expect_output }}
            </span>
          </span>
        </label>
      </div>

      <div>
        <input
          v-model="customText"
          type="text"
          class="w-full rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700 outline-none transition-colors placeholder:text-gray-400 focus:border-blue-500 disabled:cursor-not-allowed disabled:bg-gray-100"
          placeholder="输入原因或补充要求…"
          :disabled="disabled"
        />
      </div>

      <!-- 状态文案（左）+ 按钮行（右）同一行展示 -->
      <div class="flex items-center justify-between gap-2">
        <div class="text-xs text-gray-500">
          <template v-if="props.readonly">任务已停止，不可再选择</template>
          <template v-else-if="isHistory">
            已{{ planEchoLabel }}<template v-if="checkedOrders.length">，保留项：{{ checkedOrders.join('、') }}</template>
          </template>
          <template v-else-if="submitted">已提交，继续处理中…</template>
        </div>
        <!-- 确认执行 / 重新规划（按钮行靠右对齐；确认执行在最右，与选项模式"提交"一致） -->
        <div class="flex items-center justify-end gap-2 shrink-0">
          <button
            type="button"
            class="rounded-lg border border-gray-300 bg-white px-4 py-1.5 text-sm text-gray-600 transition-colors hover:border-gray-400 hover:text-gray-800 disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="disabled || replanDisabled"
            @click="handlePlanSubmit('replan')"
          >
            重新规划
          </button>
          <button
            type="button"
            class="rounded-lg bg-blue-600 px-4 py-1.5 text-sm text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="disabled"
            @click="handlePlanSubmit('confirm')"
          >
            确认执行
          </button>
        </div>
      </div>
    </template>

    <!-- ===== option 模式：选项按钮 + 自定义输入 + 提交/跳过 ===== -->
    <template v-else>
      <div class="flex flex-wrap gap-2">
        <button
          v-for="(option, idx) in options ?? []"
          :key="idx"
          type="button"
          class="rounded-lg border px-3 py-1.5 text-sm transition-colors disabled:cursor-not-allowed"
          :class="[
            selected === option
              ? 'border-blue-600 bg-blue-600 text-white'
              : 'border-gray-300 bg-white text-gray-700 hover:border-blue-400 hover:text-blue-600',
            disabled ? 'opacity-60' : '',
          ]"
          :disabled="disabled"
          @click="handleOptionClick(option)"
        >
          {{ option }}
        </button>
      </div>

      <div v-if="allowCustom">
        <input
          v-model="customText"
          type="text"
          class="w-full rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700 outline-none transition-colors placeholder:text-gray-400 focus:border-blue-500 disabled:cursor-not-allowed disabled:bg-gray-100"
          placeholder="输入自定义选项…"
          :disabled="disabled"
        />
      </div>

      <!-- 状态文案（左）+ 按钮行（右）同一行展示 -->
      <div class="flex items-center justify-between gap-2">
        <div class="text-xs text-gray-500">
          <template v-if="props.readonly">任务已停止，不可再选择</template>
          <template v-else-if="isHistory">已选：{{ choice }}</template>
          <template v-else-if="submitted">已提交，继续处理中…</template>
        </div>
        <div class="flex items-center justify-end gap-2 shrink-0">
          <button
            type="button"
            class="rounded-lg border border-gray-300 bg-white px-4 py-1.5 text-sm text-gray-600 transition-colors hover:border-gray-400 hover:text-gray-800 disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="disabled"
            @click="handleSkip"
          >
            跳过
          </button>
          <button
            type="button"
            class="rounded-lg bg-blue-600 px-4 py-1.5 text-sm text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="disabled"
            @click="handleSubmit"
          >
            提交
          </button>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped></style>
