<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useUpdateDraftAppConfig } from '@/hooks/use-app.ts'
import cloneDeep from 'lodash/cloneDeep'
import { isEqual } from 'lodash'
import type { OrchestratorConfig } from '@/models/app.ts'

const props = defineProps({
  app_id: { type: String, default: '', required: true },
  orchestrator_config: {
    type: Object,
    default: () => ({
      enable: false,
      max_sub_tasks: 5,
      max_parallel: 3,
      sub_task_timeout: 300,
      resume_mode: 'auto',
    }),
    required: true,
  },
})

const emits = defineEmits(['update:orchestrator_config'])

const { loading, handleUpdateDraftAppConfig } = useUpdateDraftAppConfig()
const isInit = ref(false)
const orchestratorConfigModalVisible = ref(false)

const orchestratorConfigForm = ref<OrchestratorConfig>({
  enable: props.orchestrator_config?.enable ?? false,
  max_sub_tasks: props.orchestrator_config?.max_sub_tasks ?? 5,
  max_parallel: props.orchestrator_config?.max_parallel ?? 3,
  sub_task_timeout: props.orchestrator_config?.sub_task_timeout ?? 300,
  resume_mode: props.orchestrator_config?.resume_mode ?? 'auto',
})

const originOrchestratorConfigForm = ref({ ...cloneDeep(orchestratorConfigForm.value) })

const isFormModified = () => {
  return !isEqual(originOrchestratorConfigForm.value, orchestratorConfigForm.value)
}

// 关闭编排配置弹框（还原表单数据）
const handleCancelOrchestratorConfigModal = () => {
  orchestratorConfigModalVisible.value = false
  orchestratorConfigForm.value = cloneDeep(originOrchestratorConfigForm.value)
}

// 提交编排配置（开启/关闭即时保存 + 弹框保存共用）
const handleSubmitOrchestratorConfig = async () => {
  await handleUpdateDraftAppConfig(props.app_id, {
    orchestrator_config: {
      enable: orchestratorConfigForm.value.enable,
      max_sub_tasks: orchestratorConfigForm.value.max_sub_tasks,
      max_parallel: orchestratorConfigForm.value.max_parallel,
      sub_task_timeout: orchestratorConfigForm.value.sub_task_timeout,
      resume_mode: orchestratorConfigForm.value.resume_mode,
    },
  })
  emits('update:orchestrator_config', { ...orchestratorConfigForm.value })
  originOrchestratorConfigForm.value = cloneDeep(orchestratorConfigForm.value)
  await nextTick()
  handleCancelOrchestratorConfigModal()
}

// 监听orchestrator_config变化并同步到表单
watch(
  () => props.orchestrator_config,
  (newValue: Partial<OrchestratorConfig> | undefined) => {
    if (!isInit.value || !isFormModified()) {
      if (newValue && Object.keys(newValue).length > 0) {
        orchestratorConfigForm.value = {
          enable: newValue.enable ?? false,
          max_sub_tasks: newValue.max_sub_tasks ?? 5,
          max_parallel: newValue.max_parallel ?? 3,
          sub_task_timeout: newValue.sub_task_timeout ?? 300,
          resume_mode: newValue.resume_mode ?? 'auto',
        }
        originOrchestratorConfigForm.value = cloneDeep(orchestratorConfigForm.value)
        isInit.value = true
      }
    }
  },
  { immediate: true, deep: true },
)

const handleEnableSelect = async (value: unknown) => {
  const enable = Boolean(value)
  if (enable === orchestratorConfigForm.value.enable) return
  orchestratorConfigForm.value.enable = enable
  await handleSubmitOrchestratorConfig()
}

// 供外部（左侧「任务编排」导航）直接打开编排配置弹窗
defineExpose({ openAdd: () => { orchestratorConfigModalVisible.value = true } })
</script>

<template>
  <div class="">
    <a-collapse-item key="orchestrator_config" class="app-ability-item">
      <template #header>
        <div class="text-gray-700 font-bold">任务编排（Orchestrator）</div>
      </template>
      <template #extra>
        <a-dropdown @select="handleEnableSelect">
          <a-button size="mini" class="rounded-lg flex items-center gap-1 px-1" @click.stop>
            {{ orchestratorConfigForm.enable ? '开启' : '关闭' }}
            <icon-down />
          </a-button>
          <template #content>
            <a-doption :value="1" class="text-xs py-1.5 text-gray-700">开启</a-doption>
            <a-doption :value="0" class="text-xs py-1.5 text-red-700">关闭</a-doption>
          </template>
        </a-dropdown>
      </template>
      <!-- 介绍 + 设置入口（描述不隐藏，设置按钮覆盖其上并垂直居中，悬停浮现） -->
      <div class="group relative">
        <div class="ability-desc text-xs text-gray-500 leading-[28px]">
          将用户请求自动分解为多个子任务并行执行，并在中断后支持断点续跑。
        </div>
        <div
          v-if="orchestratorConfigForm.enable"
          class="absolute inset-0 flex items-center rounded-lg transition-all opacity-0 group-hover:opacity-100"
        >
          <a-button size="small" long class="rounded-lg" @click="orchestratorConfigModalVisible = true">
            <template #icon>
              <icon-settings />
            </template>
            编排设置
          </a-button>
        </div>
      </div>
    </a-collapse-item>
    <!-- 编排配置弹框（auto-focus=false：避免 Arco 自动聚焦 a-input-number/a-select 内部 aria-hidden 隐藏输入框触发浏览器 a11y 告警） -->
    <a-modal
      :visible="orchestratorConfigModalVisible"
      hide-title
      :footer="false"
      modal-class="rounded-xl"
      width="max(400px, min(520px, calc(100vw - 32px)))"
      :auto-focus="false"
      @cancel="handleCancelOrchestratorConfigModal"
    >
      <!-- 顶部标题 -->
      <div class="flex items-center justify-between">
        <div class="text-lg font-bold text-gray-700">任务编排（Orchestrator）</div>
        <a-button aria-label="关闭"
          type="text"
          class="!text-gray-700"
          size="small"
          @click="handleCancelOrchestratorConfigModal"
        >
          <template #icon>
            <icon-close />
          </template>
        </a-button>
      </div>
      <!-- 中间表单 -->
      <div class="py-4">
        <div class="flex flex-col gap-5">
          <!-- 总开关：开启任务编排 -->
          <div class="flex items-center justify-between p-3 bg-gray-50 border border-gray-200 rounded-lg">
            <div>
              <div class="text-gray-700">开启任务编排</div>
              <div class="text-gray-500 text-xs mt-1">关闭后下方参数不可编辑</div>
            </div>
            <a-switch
              v-model:model-value="orchestratorConfigForm.enable"
              size="small"
              type="round"
            />
          </div>
          <div class="flex flex-col gap-2">
            <div class="text-gray-500 text-xs">
              启用后，应用需为编排型（应用类型选择 Orchestrator）；用户请求将自动分解为多个子任务并行执行，中断后支持断点续跑。
            </div>
          </div>
          <div class="flex flex-col gap-2">
            <div class="flex items-center gap-1 text-gray-700">
              最大子任务数（max_sub_tasks）
              <div class="text-red-700">*</div>
            </div>
            <div class="text-gray-500 text-xs">
              单次请求最多拆分几个子任务并行处理，建议不超过 5 个。
            </div>
          </div>
          <input
            v-model.number="orchestratorConfigForm.max_sub_tasks"
            type="number"
            min="1"
            max="20"
            :disabled="!orchestratorConfigForm.enable"
            aria-label="最大子任务数"
            class="w-full h-8 px-3 rounded-md border border-gray-200 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-50 disabled:text-gray-400"
          />

          <div class="flex flex-col gap-2">
            <div class="flex items-center gap-1 text-gray-700">
              最大并行数（max_parallel）
              <div class="text-red-700">*</div>
            </div>
            <div class="text-gray-500 text-xs">
              同时执行的子任务数量上限，取决于模型并发与成本预算。
            </div>
          </div>
          <input
            v-model.number="orchestratorConfigForm.max_parallel"
            type="number"
            min="1"
            max="10"
            :disabled="!orchestratorConfigForm.enable"
            aria-label="最大并行数"
            class="w-full h-8 px-3 rounded-md border border-gray-200 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-50 disabled:text-gray-400"
          />

          <div class="flex flex-col gap-2">
            <div class="flex items-center gap-1 text-gray-700">
              单子任务超时（秒，sub_task_timeout）
              <div class="text-red-700">*</div>
            </div>
            <div class="text-gray-500 text-xs">
              子任务超过该时长未完成将被标记为超时，其余子任务不受影响。
            </div>
          </div>
          <input
            v-model.number="orchestratorConfigForm.sub_task_timeout"
            type="number"
            min="10"
            max="3600"
            :disabled="!orchestratorConfigForm.enable"
            aria-label="单子任务超时"
            class="w-full h-8 px-3 rounded-md border border-gray-200 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-50 disabled:text-gray-400"
          />

          <div class="flex flex-col gap-2">
            <div class="flex items-center gap-1 text-gray-700">
              断点恢复模式（resume_mode）
              <div class="text-red-700">*</div>
            </div>
            <div class="text-gray-500 text-xs">
              auto：同一会话重发相同任务自动续跑；manual：仅通过"继续执行"按钮显式触发。
            </div>
          </div>
          <select
            v-model="orchestratorConfigForm.resume_mode"
            :disabled="!orchestratorConfigForm.enable"
            aria-label="断点恢复模式"
            class="w-full h-8 px-2 rounded-md border border-gray-200 text-sm bg-white focus:border-blue-500 focus:outline-none disabled:bg-gray-50 disabled:text-gray-400"
          >
            <option value="auto">auto（自动续跑）</option>
            <option value="manual">manual（仅手动触发）</option>
          </select>
        </div>
      </div>
      <!-- 底部按钮 -->
      <div class="flex items-center justify-between">
        <div class=""></div>
        <a-space :size="16">
          <a-button class="rounded-lg" @click="handleCancelOrchestratorConfigModal">取消</a-button>
          <a-button
            :loading="loading"
            type="primary"
            class="rounded-lg"
            @click="handleSubmitOrchestratorConfig"
          >
            保存
          </a-button>
        </a-space>
      </div>
    </a-modal>
  </div>
</template>

<style scoped></style>
