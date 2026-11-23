<script setup lang="ts">
import ConfigGroup from './ConfigGroup.vue'
import ConfigRow from './ConfigRow.vue'

defineProps<{ modelValue: Record<string, string> }>()
defineEmits(['update:modelValue'])
</script>

<template>
  <div>
    <config-group title="JWT 认证">
      <config-row label="JWT Secret Key" env-key="JWT_SECRET_KEY" :model-value="modelValue" sensitive @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>

    <config-group title="GitHub OAuth 登录">
      <config-row label="Client ID" env-key="GITHUB_CLIENT_ID" :model-value="modelValue" sensitive @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="Client Secret" env-key="GITHUB_CLIENT_SECRET" :model-value="modelValue" sensitive @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="Redirect URI" env-key="GITHUB_CLIENT_REDIRECT_URI" :model-value="modelValue" placeholder="http://localhost:5173/auth/authorize/github" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="OAuth 基础地址" env-key="GITHUB_OAUTH_BASE_URL" :model-value="modelValue" placeholder="https://github.com" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="API 基础地址" env-key="GITHUB_API_BASE_URL" :model-value="modelValue" placeholder="https://api.github.com" @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>

    <config-group title="内置 Agent" subtitle="系统内置助手 Agent 的应用 ID">
      <config-row label="Assistant Agent ID" env-key="ASSISTANT_AGENT_ID" :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>

    <config-group
      title="任务编排引擎"
      subtitle="全局默认值；应用配置里的「编排引擎」优先于这里。保存后需重启 API 生效（与其他环境变量型配置同口径）"
    >
      <config-row
        label="编排引擎"
        env-key="ORCHESTRATOR_ENGINE"
        :model-value="modelValue"
        type="select"
        :options="[
          { label: '默认编排（子任务拆分 + 依赖调度 + 失败重规划）', value: 'subtask' },
          { label: '预算护栏编排（同上，超预算即熔断剩余子任务）', value: 'guarded' },
        ]"
        hint="留空等同「默认编排」。选预算护栏时必须至少配一项下面的上限，否则不限流。"
        @update:model-value="$emit('update:modelValue', $event)"
      />
      <config-row label="预算：最大 tokens" env-key="ORCHESTRATOR_BUDGET_MAX_TOKENS" :model-value="modelValue" placeholder="0 = 不限" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="预算：最大花费" env-key="ORCHESTRATOR_BUDGET_MAX_PRICE" :model-value="modelValue" placeholder="0 = 不限" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="预算：最长耗时（秒）" env-key="ORCHESTRATOR_BUDGET_MAX_SECONDS" :model-value="modelValue" placeholder="0 = 不限" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="预算：最多子任务数" env-key="ORCHESTRATOR_BUDGET_MAX_SUBTASKS" :model-value="modelValue" placeholder="0 = 不限" @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>
  </div>
</template>
