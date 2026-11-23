<script setup lang="ts">
import { computed, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { showErrorToast } from '@/utils/http/error'
import type { PropType } from 'vue'
import { useUpdateDraftAppConfig } from '@/hooks/use-app.ts'
import { testMemoryConfig } from '@/services/system-config.ts'

type LongTermMemory = {
  enable: boolean
  provider?: string
  team_id?: string
  agent_id?: string
  user_id?: string
}

const props = defineProps({
  app_id: { type: String, required: true },
  long_term_memory: {
    type: Object as PropType<LongTermMemory>,
    required: true,
    default: () => ({ enable: false, provider: 'default' }),
  },
})

const emits = defineEmits(['update:long_term_memory'])

const { loading, handleUpdateDraftAppConfig } = useUpdateDraftAppConfig()

const MEMORY_PROVIDERS = [
  { value: 'default', label: '跟随系统默认' },
  { value: 'builtin', label: '内置记忆系统' },
  { value: 'tencent', label: '腾讯记忆' },
]

const onSelectLongTermMemory = async (value: unknown) => {
  const enable = Boolean(value)
  if (enable === props.long_term_memory?.enable) return
  const next = { ...props.long_term_memory, enable }
  emits('update:long_term_memory', next)
  await handleUpdateDraftAppConfig(props.app_id, { long_term_memory: next })
}

// ===== 记忆设置弹窗 =====
const modalVisible = ref(false)
const draft = ref<LongTermMemory>({ enable: false, provider: 'default' })
// 测试状态：idle=灰色 / testing=点击后灰色禁用 / success=API 成功变绿
type TestStatus = 'idle' | 'testing' | 'success'
const testStatus = ref<TestStatus>('idle')

const openModal = () => {
  draft.value = {
    enable: props.long_term_memory?.enable ?? false,
    provider: props.long_term_memory?.provider ?? 'default',
    team_id: props.long_term_memory?.team_id ?? '',
    agent_id: props.long_term_memory?.agent_id ?? '',
    user_id: props.long_term_memory?.user_id ?? '',
  }
  testStatus.value = 'idle'
  modalVisible.value = true
}

const closeModal = () => {
  modalVisible.value = false
}

const onProviderChange = (value: unknown) => {
  draft.value.provider = String(value)
}

// 内置记忆系统（builtin 或跟随系统默认 default）无需配置作用域：禁用 Team/Agent/User ID 与测试连通
const isBuiltinProvider = computed(
  () => draft.value.provider === 'builtin' || draft.value.provider === 'default',
)

const testConnection = async () => {
  testStatus.value = 'testing'
  try {
    const resp = await testMemoryConfig({
      app_id: props.app_id,
      team_id: draft.value.team_id,
      agent_id: draft.value.agent_id,
      user_id: draft.value.user_id,
    })
    if (resp.data?.ok) {
      testStatus.value = 'success'
      Message.success(resp.data.message || '连接正常')
    } else {
      testStatus.value = 'idle'
      Message.error(resp.data?.message || '连接失败')
    }
  } catch (e) {
    testStatus.value = 'idle'
    showErrorToast((e as Error).message || '测试失败')
  }
}

const save = async () => {
  const next: LongTermMemory = {
    enable: draft.value.enable,
    provider: draft.value.provider,
  }
  for (const key of ['team_id', 'agent_id', 'user_id'] as const) {
    if (draft.value[key]) next[key] = draft.value[key]
  }
  try {
    emits('update:long_term_memory', next)
    await handleUpdateDraftAppConfig(props.app_id, { long_term_memory: next })
    Message.success('保存成功')
    closeModal()
  } catch (e) {
    showErrorToast(String(e))
  }
}

// 供外部（左侧「长期记忆」导航）直接打开记忆设置弹窗
defineExpose({ openAdd: openModal })
</script>

<template>
  <div>
    <a-collapse-item key="long_term_memory" class="app-ability-item long-term-memory-ability-item">
      <template #header>
        <div class="text-gray-700 font-bold">长期记忆</div>
      </template>
      <template #extra>
        <a-dropdown @select="onSelectLongTermMemory">
          <a-button size="mini" class="rounded-lg flex items-center gap-1 px-1" @click.stop>
            {{ props.long_term_memory.enable ? '开启' : '关闭' }}
            <icon-down />
          </a-button>
          <template #content>
            <a-doption :value="1" class="text-xs py-1.5 text-gray-700">开启</a-doption>
            <a-doption :value="0" class="text-xs py-1.5 text-gray-700">关闭</a-doption>
          </template>
        </a-dropdown>
      </template>
      <div class="group relative">
        <div class="ability-desc text-xs text-gray-500 leading-[28px]">
          总结聊天对话内容，并用于更好的响应用户的信息。
          <span v-if="props.long_term_memory.enable" class="ml-2 text-gray-400">
            {{ MEMORY_PROVIDERS.find(p => p.value === (props.long_term_memory.provider ?? 'default'))?.label }}
          </span>
        </div>
        <div
          v-if="props.long_term_memory.enable"
          class="absolute inset-0 flex items-center rounded-lg transition-all opacity-0 group-hover:opacity-100"
        >
          <a-button size="small" long class="rounded-lg" @click="openModal">
            <template #icon>
              <icon-settings />
            </template>
            设置
          </a-button>
        </div>
      </div>
    </a-collapse-item>

    <!-- 记忆设置弹窗 -->
    <a-modal
      :visible="modalVisible"
      hide-title
      :footer="false"
      modal-class="rounded-xl"
      width="max(400px, min(520px, calc(100vw - 32px)))"
      @cancel="closeModal"
    >
      <!-- 顶部标题 -->
      <div class="flex items-center justify-between">
        <div class="text-lg font-bold text-gray-700">记忆设置</div>
        <a-button aria-label="关闭" type="text" class="text-gray-700" size="small" @click="closeModal">
          <template #icon>
            <icon-close />
          </template>
        </a-button>
      </div>
      <!-- 中间表单 -->
      <div class="py-4">
        <div class="flex flex-col gap-5">
          <!-- 总开关：开启长期记忆 -->
          <div class="flex items-center justify-between p-3 bg-gray-50 border border-gray-200 rounded-lg">
            <div>
              <div class="text-gray-700">开启长期记忆</div>
              <div class="text-gray-500 text-xs mt-1">关闭后记忆系统与作用域配置不可编辑</div>
            </div>
            <a-switch
              v-model:model-value="draft.enable"
              size="small"
              type="round"
            />
          </div>
          <!-- 记忆系统 -->
          <div class="flex flex-col gap-2">
            <div class="text-gray-700">记忆系统</div>
            <a-select
              :model-value="draft.provider"
              :disabled="!draft.enable"
              class="w-full"
              @change="onProviderChange"
            >
              <a-option v-for="p in MEMORY_PROVIDERS" :key="p.value" :value="p.value">
                {{ p.label }}
              </a-option>
            </a-select>
          </div>
          <!-- Team ID -->
          <div class="flex flex-col gap-2">
            <div class="text-gray-700">Team ID</div>
            <input
              v-model="draft.team_id"
              :disabled="!draft.enable || isBuiltinProvider"
              class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 disabled:bg-gray-100 disabled:cursor-not-allowed disabled:text-gray-400"
              placeholder="team-xxx（留空跟随系统）"
            />
            <div class="text-gray-400 text-xs">在记忆面板「组织与权限」中获取</div>
          </div>
          <!-- Agent ID -->
          <div class="flex flex-col gap-2">
            <div class="text-gray-700">Agent ID</div>
            <input
              v-model="draft.agent_id"
              :disabled="!draft.enable || isBuiltinProvider"
              class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 disabled:bg-gray-100 disabled:cursor-not-allowed disabled:text-gray-400"
              placeholder="agt-xxx（留空跟随系统）"
            />
            <div class="text-gray-400 text-xs">在记忆面板「Agents 管理」中获取</div>
          </div>
          <!-- User ID -->
          <div class="flex flex-col gap-2">
            <div class="text-gray-700">User ID</div>
            <input
              v-model="draft.user_id"
              :disabled="!draft.enable || isBuiltinProvider"
              class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 disabled:bg-gray-100 disabled:cursor-not-allowed disabled:text-gray-400"
              placeholder="usr-xxx（留空跟随系统）"
            />
            <div class="text-gray-400 text-xs">在记忆面板「成员管理」中获取（记忆块会话名不是用户 ID）</div>
          </div>
          <p class="text-xs text-gray-400">
            作用域仅对「腾讯记忆」生效：填写后本应用的记忆写入/召回使用该 team/agent/user，留空则跟随系统设置。
          </p>
        </div>
      </div>
      <!-- 底部按钮：测试连通 + 取消/保存 一行 -->
      <div class="flex items-center justify-between">
        <a-button
          :status="testStatus === 'success' ? 'success' : 'normal'"
          :disabled="!draft.enable || testStatus === 'testing' || isBuiltinProvider"
          @click="testConnection"
        >
          测试连通
        </a-button>
        <a-space :size="16">
          <a-button class="rounded-lg" @click="closeModal">取消</a-button>
          <a-button
            :loading="loading"
            type="primary"
            class="rounded-lg"
            @click="save"
          >
            保存
          </a-button>
        </a-space>
      </div>
    </a-modal>
  </div>
</template>

<style>
.long-term-memory-ability-item {
  .arco-collapse-item-content-box {
    padding: 0;
  }
}
</style>
