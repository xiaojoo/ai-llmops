<script setup lang="ts">
import ConfigGroup from './ConfigGroup.vue'
import ConfigRow from './ConfigRow.vue'

defineProps<{ modelValue: Record<string, string> }>()
defineEmits(['update:modelValue'])
</script>

<template>
  <div>
    <config-group title="Weaviate 向量数据库">
      <config-row label="Host" env-key="WEAVIATE_HOST" :model-value="modelValue" placeholder="127.0.0.1" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="HTTP Port" env-key="WEAVIATE_PORT" :model-value="modelValue" placeholder="8080" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="gRPC Host" env-key="WEAVIATE_GRPC_HOST" :model-value="modelValue" placeholder="127.0.0.1" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="gRPC Port" env-key="WEAVIATE_GRPC_PORT" :model-value="modelValue" placeholder="50051" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="API Key" env-key="WEAVIATE_API_KEY" :model-value="modelValue" sensitive @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>
  </div>
</template>
