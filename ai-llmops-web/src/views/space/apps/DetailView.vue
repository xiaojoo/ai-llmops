<script setup lang="ts">
import { useRoute, onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useGetDraftAppConfig } from '@/hooks/use-app.ts'
import { apiPrefix } from '@/config'
import { Modal } from '@arco-design/web-vue'
import PreviewDebugHeader from './components/PreviewDebugHeader.vue'
import PresetPromptTextarea from './components/PresetPromptTextarea.vue'
import AgentAppAbility from './components/AgentAppAbility.vue'
import PreviewDebugChat from './components/PreviewDebugChat.vue'
import ModelConfig from './components/ModelConfig.vue'

const route = useRoute()

const props = defineProps({
  app: {
    type: Object,
    required: true,
    default: () => ({}),
  },
})
const { draftAppConfigForm, loadDraftAppConfig } = useGetDraftAppConfig(
  String(route.params?.app_id),
)
const reloadDraftConfig = () => loadDraftAppConfig(String(route.params?.app_id))

// ===== 左侧「应用结构」折叠/展开（视口变窄自动收起） =====
const sideCollapsed = ref(false)
const COLLAPSE_BREAKPOINT = 1150
let lastWide = true
const updateByViewport = () => {
  const wide = window.innerWidth >= COLLAPSE_BREAKPOINT
  if (wide !== lastWide) {
    sideCollapsed.value = !wide
    lastWide = wide
  }
}
onMounted(() => {
  // 刷新时按当前视口决定初始状态：小视口（<1150）默认收起「应用结构」
  const wide = window.innerWidth >= COLLAPSE_BREAKPOINT
  lastWide = wide
  sideCollapsed.value = !wide
  window.addEventListener('resize', updateByViewport)
})
onBeforeUnmount(() => {
  cancelAnimationFrame(rollRaf)
  window.removeEventListener('resize', updateByViewport)
})

// ===== 编排型 Agent：标题栏上方摘要行 + 页内 tab 视图状态 =====
// viewMode 提升到父组件：摘要行/tab 点击后通过 v-model 联动 PreviewDebugChat
type ViewMode = 'chat' | 'subagents'
const viewMode = ref<ViewMode>('chat')
// 子任务数量由 PreviewDebugChat 上报（update:sub-task-summary）
const subTaskCount = ref(0)
const handleSubTaskSummary = (count: number) => {
  subTaskCount.value = count
}

// ===== 调试预览运行态：任务运行中离开（切 tab / 切到其他应用 / 离开页面）需先确认 =====
const previewChatRef = ref<InstanceType<typeof PreviewDebugChat> | null>(null)
const debugChatRunning = ref(false)
const handleDebugChatRunning = (running: boolean) => {
  debugChatRunning.value = running
}

/** 弹框选「停止任务并离开」时调用子组件（PreviewDebugChat）暴露的停止逻辑（中断 SSE + 调后端 stop）。 */
const stopPreviewChatTask = async () => {
  const chat = previewChatRef.value as unknown as { handleStop?: () => Promise<void> } | null
  await chat?.handleStop?.()
}

/**
 * 任务运行中离开调试预览的确认：
 * - ok「停止任务并离开」：先让 PreviewDebugChat 停止任务，再放行离开；
 * - cancel「后台继续，直接离开」：不停止任务直接放行（任务在后台继续，返回本会话仍可见）；
 * 非运行状态直接放行，不弹框、不拦截（与原行为一致）。
 */
const confirmLeaveDebugRunning = (proceed: () => void) => {
  if (!debugChatRunning.value) {
    proceed()
    return
  }
  Modal.confirm({
    title: '正在执行任务',
    content:
      '当前调试对话仍有任务在运行，离开将中断当前输出。选择「停止任务并离开」会先停止任务；选择「后台继续，直接离开」不停止任务，任务将在后台继续执行，返回本会话后仍可查看结果。',
    okText: '停止任务并离开',
    cancelText: '后台继续，直接离开',
    onOk: async () => {
      try {
        await stopPreviewChatTask()
      } catch {
        // 忽略：客户端已停止，后端停止失败不阻塞离开
      }
      proceed()
    },
    onCancel: () => proceed(),
  })
}

// 拦截路由离开：切「发布配置/统计分析」等顶层 tab、切到其他应用/离开本页；
// 以及 :app_id 同级切换（组件复用，走 onBeforeRouteUpdate）
onBeforeRouteLeave((_to, _from, next) => {
  confirmLeaveDebugRunning(() => next())
})
onBeforeRouteUpdate((_to, _from, next) => {
  confirmLeaveDebugRunning(() => next())
})

// 中栏「应用能力总览」统计（一行 4 张，参考 数字放大版卡片样式：徽章 + 大数字 + 名称 + 描述）
type OverviewStat = {
  key: string
  name: string
  accent: 'blue' | 'cyan' | 'amber' | 'green'
  num: number
  unit: string
  svg: string
  desc: string
}

const statSvg = {
  plugin:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7"/><path d="M12 12l8-8"/><path d="M15 4h5v5"/></svg>',
  workflow:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="9" r="2.5"/><path d="M8.5 6H14a2 2 0 0 1 2 2v1"/><path d="M8.5 18H14a2 2 0 0 0 2-2v-5"/></svg>',
  skill:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l2.4 4.9 5.4.8-3.9 3.8.9 5.4L12 14.6 7.2 16.9l.9-5.4L4.2 7.7l5.4-.8z"/></svg>',
  dataset:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></svg>',
}

const abilityStats = computed<OverviewStat[]>(() => {
  const cfg = draftAppConfigForm.value ?? {}
  const n = (k: 'tools' | 'workflows' | 'skills' | 'datasets') => (cfg[k] || []).length
  return [
    {
      key: 'tools', name: '扩展插件', accent: 'blue', num: n('tools'), unit: '个',
      svg: statSvg.plugin,
      desc: '接入第三方插件，快速为应用增加搜索、翻译、天气等外部能力。',
    },
    {
      key: 'workflows', name: '工作流', accent: 'cyan', num: n('workflows'), unit: '个',
      svg: statSvg.workflow,
      desc: '编排多步骤流程，串联工具与模型，实现自动化任务处理。',
    },
    {
      key: 'skills', name: 'Skills', accent: 'amber', num: n('skills'), unit: '个',
      svg: statSvg.skill,
      desc: '注入专业技能与指令，让应用更懂你的业务场景。',
    },
    {
      key: 'datasets', name: '知识库', accent: 'green', num: n('datasets'), unit: '个',
      svg: statSvg.dataset,
      desc: '上传文档建立知识库，让应用基于你的专属资料作答。',
    },
  ]
})

// 数字滚动（0 → 目标值，900ms easeOutCubic，参考 html 的 count 动画）
const statDisplays = ref<number[]>(abilityStats.value.map(() => 0))
let rollRaf = 0
const animateCounters = (targets: number[]) => {
  cancelAnimationFrame(rollRaf)
  const from = statDisplays.value.map((v) => v)
  const duration = 900
  const start = performance.now()
  const tick = (now: number) => {
    const p = Math.min((now - start) / duration, 1)
    const eased = 1 - Math.pow(1 - p, 3)
    statDisplays.value = targets.map((t, i) => {
      const f = from[i] ?? 0
      return Math.round(f + (t - f) * eased)
    })
    if (p < 1) rollRaf = requestAnimationFrame(tick)
  }
  rollRaf = requestAnimationFrame(tick)
}
watch(
  () => abilityStats.value.map((s) => s.num),
  (targets) => animateCounters(targets),
  { immediate: true },
)

// 扩展插件总览：已添加插件展示列表（每张卡按索引循环取不同强调色，与上方能力总览色系区分）
const pluginAccents = ['#7c3aed', '#db2777', '#0d9488', '#ea580c', '#4f46e5', '#d946ef']
const addedTools = computed(() => {
  const tools = (draftAppConfigForm.value.tools ?? []) as {
    type?: string
    provider?: { id?: string; name?: string; label?: string; icon?: string }
    tool?: { name?: string; label?: string; description?: string }
  }[]
  return tools.map((t, i) => {
    const isApi = t.type === 'api_tool'
    const providerName = t.provider?.name ?? ''
    return {
      key: `${providerName}-${t.tool?.name ?? i}-${i}`,
      icon: isApi
        ? (t.provider?.icon ?? '')
        : providerName
          ? `${apiPrefix}/builtin_tools/${providerName}/icon`
          : '',
      rawName: t.tool?.label ?? t.tool?.name ?? '',
      name: `${t.provider?.label ?? providerName} / ${t.tool?.label ?? t.tool?.name ?? ''}`,
      desc: t.tool?.description ?? '',
      accent: pluginAccents[i % pluginAccents.length] ?? '#7c3aed',
    }
  })
})

// 每张插件卡片右上角设置图标：打开对应插件的工具设置弹窗
const agentAbilityRef = ref<InstanceType<typeof AgentAppAbility> | null>(null)
const openOverviewToolInfo = (rawName?: string) => {
  agentAbilityRef.value?.openToolInfoByName?.(rawName)
}
</script>

<template>
  <div class="flex-1 w-full min-h-0 relative">
    <!-- 整体三栏布局：左「应用结构」(可折叠) + 中「编排内容」+ 右「预览调试」 -->
    <div
      class="ab-3col w-full min-w-0"
      :style="{ '--ab-nav-w': sideCollapsed ? '0px' : '' }"
    >
      <!-- 左栏：应用结构导航（收起时悬浮按钮展开） -->
      <button
        v-if="sideCollapsed"
        type="button"
        class="ab-side-reopen"
        aria-label="展开应用结构"
        @click="sideCollapsed = false"
      >
        <icon-right :size="14" />
      </button>
      <aside class="h-full min-w-0 overflow-y-auto overflow-x-hidden">
        <agent-app-ability
          ref="agentAbilityRef"
          :draft_app_config="draftAppConfigForm"
          :app_id="String(route.params?.app_id)"
          @collapse-toggle="sideCollapsed = true"
        />
      </aside>

      <!-- 中栏：顶部白条标题(同预览调试) + 内容区 -->
      <div class="ab-mid-col flex flex-col h-full min-w-0 border-l border-[#e8ebf0]">
        <!-- 标题条：白底 + 下边框 -->
        <div class="ab-mid-head">
          <span class="ab-mid-title">应用编排</span>
          <!-- LLM模型配置 -->
          <div class="ml-auto">
            <model-config
              :dialog_round="draftAppConfigForm.dialog_round"
              v-model:model_config="draftAppConfigForm.model_config"
              :app_id="String(route.params?.app_id)"
            />
          </div>
        </div>
        <!-- 内容区（灰底，卡片撑满视口高度） -->
        <div class="ab-workspace flex-1 min-h-0 overflow-hidden min-w-0">
          <div class="ab-workspace-inner min-w-0">
            <!-- 系统提示词卡片（占大头） -->
            <section class="ab-card ab-card-prompt">
              <preset-prompt-textarea
                v-model:preset_prompt="draftAppConfigForm.preset_prompt"
                :draft_updated_at="(draftAppConfigForm.updated_at as number | undefined) ?? 0"
                :app_id="String(route.params?.app_id)"
                @saved="reloadDraftConfig"
              />
            </section>
          <!-- 应用能力总览卡片 -->
          <section class="ab-card ab-card-stats">
            <div class="ab-card-head">
              <div class="ab-card-title">应用能力总览</div>
              <span class="text-xs text-[#98a2b3]">在左侧「应用能力」中配置各项能力</span>
            </div>
            <div class="ab-overview">
              <div class="ab-ov-grid">
                <div
                  v-for="(stat, i) in abilityStats"
                  :key="stat.key"
                  class="ab-ov-card"
                  :class="`ab-acc-${stat.accent}`"
                >
                  <div class="ab-ov-icon" v-html="stat.svg"></div>
                  <div class="ab-ov-count">
                    <span class="ab-ov-num">{{ statDisplays[i] }}</span>
                    <span class="ab-ov-unit">{{ stat.unit }}</span>
                  </div>
                  <h3 class="ab-ov-name">{{ stat.name }}</h3>
                  <p class="ab-ov-desc">{{ stat.desc }}</p>
                </div>
              </div>
            </div>
          </section>
          <!-- 扩展插件总览卡片：已添加的插件列表（多余的在卡内滚动） -->
          <section class="ab-card ab-card-plugins">
            <div class="ab-card-head">
              <div class="ab-card-title">扩展插件总览</div>
              <span class="text-xs text-[#98a2b3]">已添加 {{ addedTools.length }} 个插件</span>
            </div>
            <div class="ab-plugin-overview">
              <div v-if="addedTools.length > 0" class="ab-plugin-grid">
                <div
                  v-for="tool in addedTools"
                  :key="tool.key"
                  class="ab-plugin-card ab-plugin-card-rel"
                  :style="{ '--ab-pacc': tool.accent }"
                >
                  <button
                    type="button"
                    class="ab-plugin-card-gear"
                    aria-label="插件设置"
                    @click="openOverviewToolInfo(tool.rawName)"
                  >
                    <icon-settings :size="13" />
                  </button>
                  <span class="ab-plugin-badge">
                    <img v-if="tool.icon" :src="tool.icon" class="ab-plugin-card-icon" alt="" />
                    <span v-else class="ab-plugin-card-icon ab-plugin-card-icon-fallback">▣</span>
                  </span>
                  <div class="ab-plugin-card-name">{{ tool.name }}</div>
                  <div class="ab-plugin-card-desc">{{ tool.desc }}</div>
                </div>
              </div>
              <div v-else class="text-xs text-[#98a2b3] px-4 py-4">
                还没有添加插件，可在左侧「扩展插件」中添加。
              </div>
            </div>
          </section>
          </div>
        </div>
      </div>

      <!-- 右栏：预览调试面板（缩窄时最后保留） -->
      <div
        class="ab-right-panel min-w-0 flex flex-col h-full min-h-0 overflow-hidden"
      >
        <preview-debug-header
          :app_id="String(route.params?.app_id)"
          :long_term_memory="draftAppConfigForm.long_term_memory"
          :sub-task-count="subTaskCount"
          v-model:view-mode="viewMode"
        />
        <preview-debug-chat
          ref="previewChatRef"
          v-model:view-mode="viewMode"
          @update:sub-task-summary="handleSubTaskSummary"
          @update:running-state="handleDebugChatRunning"
          :suggested_after_answer="draftAppConfigForm.suggested_after_answer"
          :opening_questions="draftAppConfigForm.opening_questions"
          :opening_statement="draftAppConfigForm.opening_statement"
          :text_to_speech="draftAppConfigForm.text_to_speech"
          :speech_to_text="draftAppConfigForm.speech_to_text"
          :app="props.app"
        />
      </div>
    </div>
  </div>
</template>

<style scoped></style>
