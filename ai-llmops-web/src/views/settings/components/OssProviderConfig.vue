<script setup lang="ts">
import { computed } from 'vue'
import ConfigGroup from './ConfigGroup.vue'
import ConfigRow from './ConfigRow.vue'

const props = defineProps<{ modelValue: Record<string, string> }>()
defineEmits(['update:modelValue'])

// 存储提供者：cos（腾讯云 COS）| miniio（MiniIO）；缺省 miniio（与后端默认一致）
const provider = computed(() => props.modelValue['STORAGE_PROVIDER'] || 'miniio')
const isMiniio = computed(() => provider.value === 'miniio')
const isCos = computed(() => provider.value === 'cos')

const minioGroupSub = computed(() =>
  isMiniio.value
    ? '经 mall-third-party 网关的对象存储'
    : '当前未启用：存储提供者未选择 miniio',
)
const cosGroupSub = computed(() =>
  isCos.value
    ? '对象存储，用于文件上传和静态资源托管'
    : '对象存储，用于文件上传和静态资源托管；当前未启用：存储提供者未选择腾讯云 COS',
)
</script>

<template>
  <div>
    <config-group title="存储提供者" subtitle="cos（腾讯云 COS）或 miniio（经 mall-third-party 网关），二选一">
      <config-row label="存储提供者" env-key="STORAGE_PROVIDER" :model-value="modelValue" type="select" :options="[{label:'cos（腾讯云 COS）',value:'cos'},{label:'miniio（MiniIO）',value:'miniio'}]" @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>

    <config-group title="MiniIO 配置" :subtitle="minioGroupSub">
      <config-row label="MiniIO API 地址" env-key="MINIO_API_URL" :model-value="modelValue" placeholder="http://localhost:88/api" :disabled="!isMiniio" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="MiniIO 超时(秒)" env-key="MINIO_TIMEOUT" :model-value="modelValue" placeholder="60" :disabled="!isMiniio" @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>

    <config-group title="腾讯云 COS 配置" :subtitle="cosGroupSub">
      <config-row label="Secret ID" env-key="COS_SECRET_ID" :model-value="modelValue" sensitive :disabled="!isCos" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="Secret Key" env-key="COS_SECRET_KEY" :model-value="modelValue" sensitive :disabled="!isCos" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="Region" env-key="COS_REGION" :model-value="modelValue" placeholder="ap-guangzhou" :disabled="!isCos" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="Bucket" env-key="COS_BUCKET" :model-value="modelValue" placeholder="llmops-1253662435" :disabled="!isCos" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="Scheme" env-key="COS_SCHEME" :model-value="modelValue" type="select" :options="[{label:'https',value:'https'},{label:'http',value:'http'}]" :disabled="!isCos" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="自定义域名（可选）" env-key="COS_DOMAIN" :model-value="modelValue" placeholder="留空使用默认域名" :disabled="!isCos" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="音频转写基础地址（可选）" env-key="COS_BASE_URL" :model-value="modelValue" placeholder="留空默认 https://{bucket}.cos.{region}.myqcloud.com/" :disabled="!isCos" @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>
  </div>
</template>
