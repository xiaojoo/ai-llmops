<script setup lang="ts">
import { computed, reactive, ref, toRaw, watch } from 'vue'
import { useUpdateDraftAppConfig } from '@/hooks/use-app.ts'

import LongTermMemoryAbilityItem from './abilities/LongTermMemoryAbilityItem.vue'
import OpeningAbilityItem from './abilities/OpeningAbilityItem.vue'
import ReviewConfigAbilityItem from './abilities/ReviewConfigAbilityItem.vue'
import DatasetsAbilityItem from './abilities/DatasetsAbilityItem.vue'
import ToolsAbilityItem from './abilities/ToolsAbilityItem.vue'
import WorkflowAbilityItem from './abilities/WorkflowAbilityItem.vue'
import TextToSpeechAbilityItem from './abilities/TextToSpeechAbilityItem.vue'
import SkillAbilityItem from './abilities/SkillAbilityItem.vue'
import OrchestratorConfigAbilityItem from './abilities/OrchestratorConfigAbilityItem.vue'

// Props
const props = defineProps({
  app_id: { type: String, required: true, default: '' },
  draft_app_config: { type: Object, required: true, default: () => ({}) },
})

const emits = defineEmits(['update:draft_app_config', 'collapse-toggle'])

const localDraftAppConfig = reactive({ ...props.draft_app_config })

watch(
  () => props.draft_app_config,
  (newVal) => {
    Object.assign(localDraftAppConfig, toRaw(newVal) || {})
  },
  { deep: true, immediate: true },
)

watch(
  localDraftAppConfig,
  (newVal) => {
    emits('update:draft_app_config', toRaw(newVal))
  },
  { deep: true },
)

const tools = computed({
  get: () => localDraftAppConfig.tools || [],
  set: (value) => (localDraftAppConfig.tools = [...value]),
})

const workflows = computed({
  get: () => localDraftAppConfig.workflows || [],
  set: (value) => (localDraftAppConfig.workflows = [...value]),
})

const retrieval_config = computed({
  get: () => localDraftAppConfig.retrieval_config || {},
  set: (value) => (localDraftAppConfig.retrieval_config = { ...value }),
})

const datasets = computed({
  get: () => localDraftAppConfig.datasets || [],
  set: (value) => (localDraftAppConfig.datasets = [...value]),
})

const long_term_memory = computed({
  get: () => localDraftAppConfig.long_term_memory || {},
  set: (value) => (localDraftAppConfig.long_term_memory = { ...value }),
})

const opening_statement = computed({
  get: () => localDraftAppConfig.opening_statement || '',
  set: (value) => (localDraftAppConfig.opening_statement = value),
})

const opening_questions = computed({
  get: () => localDraftAppConfig.opening_questions || [],
  set: (value) => (localDraftAppConfig.opening_questions = [...value]),
})

const review_config = computed({
  get: () => localDraftAppConfig.review_config || {},
  set: (value) => (localDraftAppConfig.review_config = { ...value }),
})

const text_to_speech = computed({
  get: () => localDraftAppConfig.text_to_speech || {},
  set: (value) => (localDraftAppConfig.text_to_speech = { ...value }),
})

const skills = computed({
  get: () => localDraftAppConfig.skills || [],
  set: (value) => (localDraftAppConfig.skills = [...value]),
})

const orchestrator_config = computed({
  get: () => localDraftAppConfig.orchestrator_config || {},
  set: (value) => (localDraftAppConfig.orchestrator_config = { ...value }),
})

// ===== 左侧「应用结构」导航 =====
type NavItem = { key: string; glyph: string; label: string; badge?: 'count' | 'on'; switch?: boolean }

// AI 大脑组（系统提示词内联于中栏，不再出现在左侧导航）
const brainNav: NavItem[] = [
  { key: 'long_term_memory', glyph: '♧', label: '长期记忆', badge: 'on' },
  { key: 'opening', glyph: '⌕', label: '对话开场白' },
  { key: 'suggested_after_answer', glyph: '⌁', label: '用户问题建议', switch: true },
]

// 应用能力组（点击均弹出配置弹窗）
const abilityNav: NavItem[] = [
  { key: 'tools', glyph: '▣', label: '扩展插件', badge: 'count' },
  { key: 'workflows', glyph: '♧', label: '工作流', badge: 'count' },
  { key: 'skills', glyph: '♙', label: 'Skills', badge: 'count' },
  { key: 'datasets', glyph: '▤', label: '知识库', badge: 'count' },
  { key: 'review_config', glyph: '✓', label: '内容审查', badge: 'on' },
  { key: 'speech_to_text', glyph: '♪', label: '语音输入', switch: true },
  { key: 'text_to_speech', glyph: '♪', label: '语音输出', badge: 'on' },
  { key: 'orchestrator_config', glyph: '⇄', label: '任务编排', badge: 'on' },
]

// 导航角标（数量 / 开闭状态）
const navBadge = (item: NavItem): { text: string; on?: boolean } | null => {
  if (item.badge === 'count') {
    const n = (localDraftAppConfig[item.key] as unknown[] | undefined)?.length ?? 0
    return { text: String(n) }
  }
  if (item.badge === 'on') {
    const on = Boolean((localDraftAppConfig[item.key] as { enable?: boolean } | undefined)?.enable)
    return { text: on ? '开' : '关', on }
  }
  return null
}

// 弹窗元信息（宽度 + 顶部描述）
type AbilityKey =
  | 'opening'

const modalMeta: { [K in AbilityKey]: { label: string; width: number; desc: string } } = {
  opening: { label: '对话开场白', width: 640, desc: '设置对话开场白与开场推荐问题。' },
}

const modalVisible = reactive<{ [K in AbilityKey]: boolean }>({
  opening: false,
})

const openAbility = (key: string) => {
  const k = key as AbilityKey
  if (modalMeta[k]) modalVisible[k] = true
}

// 扩展插件/工作流/Skills：直接打开组件自带的「添加/选择」弹窗（不走自定义弹窗）
const toolsItemRef = ref<InstanceType<typeof ToolsAbilityItem> | null>(null)
const workflowItemRef = ref<InstanceType<typeof WorkflowAbilityItem> | null>(null)
const skillItemRef = ref<InstanceType<typeof SkillAbilityItem> | null>(null)
const datasetItemRef = ref<InstanceType<typeof DatasetsAbilityItem> | null>(null)
const reviewItemRef = ref<InstanceType<typeof ReviewConfigAbilityItem> | null>(null)
const ttsItemRef = ref<InstanceType<typeof TextToSpeechAbilityItem> | null>(null)
const orchestratorItemRef = ref<InstanceType<typeof OrchestratorConfigAbilityItem> | null>(null)
const openingItemRef = ref<InstanceType<typeof OpeningAbilityItem> | null>(null)
const memoryItemRef = ref<InstanceType<typeof LongTermMemoryAbilityItem> | null>(null)
const handleSaveOpening = async () => {
  const ok = (await openingItemRef.value?.save?.()) ?? false
  if (ok) modalVisible.opening = false
}
const onAbilityNavClick = (key: string) => {
  if (key === 'long_term_memory') {
    // 长期记忆：直接打开组件自带记忆设置弹窗
    memoryItemRef.value?.openAdd?.()
    return
  }
  if (key === 'tools') {
    toolsItemRef.value?.openAdd?.()
    return
  }
  if (key === 'workflows') {
    workflowItemRef.value?.openAdd?.()
    return
  }
  if (key === 'skills') {
    skillItemRef.value?.openAdd?.()
    return
  }
  if (key === 'datasets') {
    datasetItemRef.value?.openAdd?.()
    return
  }
  if (key === 'review_config') {
    reviewItemRef.value?.openAdd?.()
    return
  }
  if (key === 'speech_to_text') {
    // 语音输入：行内滑动开关，无需弹窗
    return
  }
  if (key === 'text_to_speech') {
    // 语音输出：直接打开组件自带设置弹窗
    ttsItemRef.value?.openAdd?.()
    return
  }
  if (key === 'orchestrator_config') {
    // 任务编排：直接打开组件自带配置弹窗
    orchestratorItemRef.value?.openAdd?.()
    return
  }
  openAbility(key)
}

// 行内开关能力（语音输入/用户问题建议）：直接持久化
const { handleUpdateDraftAppConfig } = useUpdateDraftAppConfig()
const switchModelValue = (item: NavItem) =>
  Boolean((localDraftAppConfig[item.key] as { enable?: boolean } | undefined)?.enable)
const onToggleSwitch = async (item: NavItem, value: string | number | boolean) => {
  const enable = Boolean(value)
  localDraftAppConfig[item.key] = {
    ...((localDraftAppConfig[item.key] ?? {}) as Record<string, unknown>),
    enable,
  }
  try {
    await handleUpdateDraftAppConfig(props.app_id, { [item.key]: { enable } } as never)
  } catch {
    // 失败回滚开关状态
    localDraftAppConfig[item.key] = {
      ...((localDraftAppConfig[item.key] ?? {}) as Record<string, unknown>),
      enable: !enable,
    }
  }
}

// 供 DetailView「扩展插件总览」右上角设置图标调用：按名称打开对应工具设置弹窗
const openToolInfoByName = (name?: string) => {
  const t = toolsItemRef.value
  if (!t) return
  const list = tools.value as {
    provider?: { label?: string; name?: string }
    tool?: { label?: string; name?: string }
  }[]
  let idx = 0
  if (name && list.length > 0) {
    idx = list.findIndex(
      (x) =>
        x.tool?.label === name ||
        (x.tool?.label ?? '').includes(name) ||
        (x.tool?.name ?? '') === name ||
        `${x.provider?.label ?? ''}${x.tool?.label ?? ''}`.includes(name),
    )
    if (idx < 0) idx = 0
  }
  ;(t as unknown as { openToolInfo?: (i: number) => void }).openToolInfo?.(idx)
}
defineExpose({ openToolInfoByName })
</script>

<template>
  <div class="ab-side-nav">
    <div class="ab-side-title">
      <span>应用结构</span>
      <a-button
        aria-label="收起应用结构"
        size="mini"
        type="text"
        class="text-[#98a2b3]! ml-auto"
        @click="emits('collapse-toggle')"
      >
        <template #icon>
          <icon-left :size="14" />
        </template>
      </a-button>
    </div>

    <!-- AI 大脑 -->
    <div class="ab-side-group">
      <div class="ab-side-group-title">AI 大脑</div>
      <div
        v-for="item in brainNav"
        :key="item.key"
        class="ab-nav-row"
        @click="onAbilityNavClick(item.key)"
      >
        <span class="ab-nav-glyph">{{ item.glyph }}</span>
        <span class="truncate">{{ item.label }}</span>
        <span
          v-if="navBadge(item)"
          class="ab-nav-badge"
          :class="navBadge(item)?.on === false ? 'off' : navBadge(item)?.on ? 'on' : ''"
          >{{ navBadge(item)?.text }}</span
        >
        <!-- 免弹窗能力：行内滑动开关（用户问题建议） -->
        <a-switch
          v-if="item.switch"
          size="small"
          type="round"
          class="ml-auto shrink-0"
          :model-value="switchModelValue(item)"
          @click.stop
          @update:model-value="(v: string | number | boolean) => onToggleSwitch(item, v)"
        />
      </div>
    </div>

    <!-- 应用能力 -->
    <div class="ab-side-group">
      <div class="ab-side-group-title">应用能力</div>
      <div
        v-for="item in abilityNav"
        :key="item.key"
        class="ab-nav-row"
        @click="onAbilityNavClick(item.key)"
      >
        <span class="ab-nav-glyph">{{ item.glyph }}</span>
        <span class="truncate">{{ item.label }}</span>
        <span
          v-if="navBadge(item)"
          class="ab-nav-badge"
          :class="navBadge(item)?.on === false ? 'off' : navBadge(item)?.on ? 'on' : ''"
          >{{ navBadge(item)?.text }}</span
        >
        <!-- 免弹窗能力：行内滑动开关（语音输入） -->
        <a-switch
          v-if="item.switch"
          size="small"
          type="round"
          class="ml-auto shrink-0"
          :model-value="switchModelValue(item)"
          @click.stop
          @update:model-value="(v: string | number | boolean) => onToggleSwitch(item, v)"
        />
      </div>
    </div>

    <!-- ===== 各能力配置弹窗（复用组件内容，组件零改动） ===== -->




    <a-modal
      v-model:visible="modalVisible.opening"
      width="max(500px, min(640px, calc(100vw - 32px)))"
      modal-class="rounded-xl"
      :closable="false"
    >
      <template #title>
        <div class="ab-ability-modal-head">
          <span class="ab-ability-modal-title">{{ modalMeta.opening.label }}</span>
          <span class="ab-ability-modal-sub">{{ modalMeta.opening.desc }}</span>
          <a-button
            type="text"
            class="ab-modal-close"
            aria-label="关闭"
            @click="modalVisible.opening = false"
          >
            <template #icon><icon-close /></template>
          </a-button>
        </div>
      </template>
      <!-- 平铺内容（无折叠），本地草稿，点「保存」才落库 -->
      <div v-if="modalVisible.opening">
        <opening-ability-item
          ref="openingItemRef"
          v-model:opening_statement="opening_statement"
          v-model:opening_questions="opening_questions"
          :app_id="app_id"
        />
      </div>
      <template #footer>
        <div class="flex w-full items-center justify-end">
          <a-space :size="12">
            <a-button class="rounded-lg" @click="modalVisible.opening = false">取消</a-button>
            <a-button
              type="primary"
              class="rounded-lg"
              @click="handleSaveOpening"
            >保存</a-button>
          </a-space>
        </div>
      </template>
    </a-modal>






    <!-- 扩展插件/工作流/Skills 入口：隐藏挂载组件，供左侧导航直接打开其添加/选择弹窗 -->
    <tools-ability-item ref="toolsItemRef" v-show="false" v-model:tools="tools" :app_id="app_id" />
    <workflow-ability-item ref="workflowItemRef" v-show="false" v-model:workflows="workflows" :app_id="app_id" />
    <skill-ability-item ref="skillItemRef" v-show="false" v-model:skills="skills" :app_id="app_id" />
    <datasets-ability-item
      ref="datasetItemRef"
      v-show="false"
      v-model:retrieval_config="retrieval_config"
      v-model:datasets="datasets"
      :app_id="app_id"
    />
    <review-config-ability-item ref="reviewItemRef" v-show="false" v-model:review_config="review_config" :app_id="app_id" />
    <text-to-speech-ability-item ref="ttsItemRef" v-show="false" v-model:text_to_speech="text_to_speech" :app_id="app_id" />
    <orchestrator-config-ability-item
      ref="orchestratorItemRef"
      v-show="false"
      v-model:orchestrator_config="orchestrator_config"
      :app_id="app_id"
    />
    <long-term-memory-ability-item
      ref="memoryItemRef"
      v-show="false"
      v-model:long_term_memory="long_term_memory"
      :app_id="app_id"
    />
  </div>
</template>

<style>
/* 统一所有能力项标题高度（弹窗内复用） */
.app-ability-item {
  .arco-collapse-item-header {
    background-color: transparent;
    border: none;
    height: 40px;
    min-height: 40px;
    box-sizing: border-box;
  }

  .arco-collapse-item-header-title {
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
}

.arco-collapse-item-content {
  padding-left: 16px;
}

/* 统一所有能力项内容区上下 padding */
.arco-collapse-item-content-box {
  padding-top: 0;
  padding-bottom: 0;
}

/* 统一能力项描述：固定单行高度 + 超长省略 */
.ability-desc {
  height: 28px;
  line-height: 28px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
