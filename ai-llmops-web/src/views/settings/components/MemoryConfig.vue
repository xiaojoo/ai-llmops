<script setup lang="ts">
import { computed, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { showErrorToast } from '@/utils/http/error'
import { testMemoryConfig } from '@/services/system-config.ts'
import ConfigGroup from './ConfigGroup.vue'
import ConfigRow from './ConfigRow.vue'

const props = defineProps<{ modelValue: Record<string, string> }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: Record<string, string>): void }>()

const provider = computed({
  get: () => props.modelValue['MEMORY_PROVIDER'] ?? 'builtin',
  set: (v: string) => emit('update:modelValue', { ...props.modelValue, MEMORY_PROVIDER: v }),
})

const testing = ref(false)
const testConnection = async () => {
  testing.value = true
  try {
    // 连接配置随请求带上来（非空覆盖已保存配置）：未点保存也能先测。
    // 敏感项已保存时回显 '********'（掩码占位），不能当作真实 Key 提交，置空走已保存配置。
    const MASKED = '********'
    const value = (key: string) => props.modelValue[key] || ''
    const apiKey = value('TENCENT_MEMORY_API_KEY')
    const adminKey = value('TENCENT_MEMORY_ADMIN_KEY')
    const resp = await testMemoryConfig({
      team_id: value('TENCENT_MEMORY_TEAM_ID'),
      agent_id: value('TENCENT_MEMORY_AGENT_ID'),
      user_id: value('TENCENT_MEMORY_USER_ID'),
      endpoint: value('TENCENT_MEMORY_ENDPOINT'),
      api_key: apiKey === MASKED ? '' : apiKey,
      service_id: value('TENCENT_MEMORY_SERVICE_ID'),
      admin_key: adminKey === MASKED ? '' : adminKey,
    })
    if (resp.data?.ok) {
      Message.success(resp.data.message || '连接正常')
    } else {
      Message.error(resp.data?.message || '连接失败')
    }
  } catch (e) {
    showErrorToast((e as Error).message || '测试失败')
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <div>
    <config-group
      title="记忆系统"
      subtitle="应用配置里可单独覆盖；切换即时生效；存量记忆数据不迁移。"
    >
      <div class="flex gap-6 py-2">
        <label class="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
          <input
            type="radio"
            value="builtin"
            :checked="(provider || 'builtin') === 'builtin'"
            @change="provider = 'builtin'"
          />
          内置记忆系统（当前实现，行为不变）
        </label>
        <label class="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
          <input
            type="radio"
            value="tencent"
            :checked="provider === 'tencent'"
            @change="provider = 'tencent'"
          />
          腾讯记忆（TencentDB-Agent-Memory）
        </label>
      </div>
    </config-group>

    <config-group
      v-if="provider === 'tencent'"
      title="腾讯记忆连接配置"
      subtitle="腾讯记忆需可访问的 Memory Core 服务（自托管 docker 或腾讯云实例）且后端已安装 SDK；配置不完整时该模式等效关闭记忆。"
    >
      <config-row
        label="Memory Core 服务地址"
        env-key="TENCENT_MEMORY_ENDPOINT"
        placeholder="http://127.0.0.1:8420"
        :model-value="modelValue"
        @update:model-value="$emit('update:modelValue', $event)"
      />
      <config-row
        label="API Key"
        env-key="TENCENT_MEMORY_API_KEY"
        sensitive
        placeholder="sk-..."
        :model-value="modelValue"
        @update:model-value="$emit('update:modelValue', $event)"
      />
      <config-row
        label="Memory 空间 ID（service_id）"
        env-key="TENCENT_MEMORY_SERVICE_ID"
        placeholder="mem-..."
        :model-value="modelValue"
        @update:model-value="$emit('update:modelValue', $event)"
      />
      <config-row
        label="管理 Key"
        env-key="TENCENT_MEMORY_ADMIN_KEY"
        sensitive
        placeholder="sk-mem-...（记忆面板 API Key → 管理员 Key）"
        hint="填写后「测试连通」会额外校验 Team/Agent/User ID 是否真实存在（格式正确但实体不存在的 ID 会测试失败）"
        :model-value="modelValue"
        @update:model-value="$emit('update:modelValue', $event)"
      />
      <config-row
        label="Team ID"
        env-key="TENCENT_MEMORY_TEAM_ID"
        placeholder="team-..."
        hint="以 team- 开头，在记忆面板「组织与权限」中复制"
        :model-value="modelValue"
        @update:model-value="$emit('update:modelValue', $event)"
      />
      <config-row
        label="Agent ID"
        env-key="TENCENT_MEMORY_AGENT_ID"
        placeholder="agt-..."
        hint="以 agt- 开头，在记忆面板「Agents 管理」中复制"
        :model-value="modelValue"
        @update:model-value="$emit('update:modelValue', $event)"
      />
      <config-row
        label="User ID"
        env-key="TENCENT_MEMORY_USER_ID"
        placeholder="usr-..."
        hint="以 usr- 开头，在记忆面板「成员管理」中复制；记忆块会话名（chat_memory-...）不是用户 ID"
        :model-value="modelValue"
        @update:model-value="$emit('update:modelValue', $event)"
      />
      <div class="flex flex-col gap-1 py-2">
        <div class="flex items-center gap-3">
          <a-button size="mini" type="primary" :loading="testing" @click="testConnection">
            测试连通
          </a-button>
        </div>
        <span class="text-xs text-gray-400">
          测试连通使用上方当前填写值（不必先保存）；留空字段回退已保存配置。敏感 Key 已保存并回显 ******** 时沿用原值。
        </span>
        <span class="text-xs text-gray-400">作用域（team/agent/user）供腾讯记忆面板展示与隔离使用，应用配置可单独覆盖</span>
      </div>
    </config-group>
  </div>
</template>
