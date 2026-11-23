<script setup lang="ts">
import ConfigGroup from './ConfigGroup.vue'
import ConfigRow from './ConfigRow.vue'

defineProps<{ modelValue: Record<string, string> }>()
defineEmits(['update:modelValue'])
</script>

<template>
  <div>
    <config-group title="飞书应用配置" subtitle="飞书企业自建应用，用于机器人消息收发">
      <config-row label="App ID" env-key="FEISHU_APP_ID" :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="App Secret" env-key="FEISHU_APP_SECRET" :model-value="modelValue" sensitive @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="开放平台 API 地址" env-key="FEISHU_OPEN_API_BASE" :model-value="modelValue" placeholder="https://open.feishu.cn/open-apis" @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>

    <config-group title="LLMOps 对接配置" subtitle="飞书机器人调用本系统 API 所需的认证信息">
      <config-row label="Web App ID" env-key="LLMOPS_APP_ID" :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="系统 API 地址" env-key="LLMOPS_BASE_URL" :model-value="modelValue" placeholder="http://localhost:5000" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="Access Token" env-key="LLMOPS_ACCESS_TOKEN" :model-value="modelValue" sensitive placeholder="JWT Token，有效期内使用" @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>
  </div>
</template>
