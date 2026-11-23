<script setup lang="ts">
import ConfigGroup from './ConfigGroup.vue'
import ConfigRow from './ConfigRow.vue'

defineProps<{ modelValue: Record<string, string> }>()
defineEmits(['update:modelValue'])
</script>

<template>
  <div>
    <config-group title="PostgreSQL 数据库" subtitle="SQLAlchemy 连接配置">
      <config-row label="连接 URI" env-key="SQLALCHEMY_DATABASE_URI" :model-value="modelValue" sensitive placeholder="postgresql://user:pass@host:5432/db" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="连接池大小" env-key="SQLALCHEMY_POOL_SIZE" :model-value="modelValue" placeholder="30" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="连接回收时间(秒)" env-key="SQLALCHEMY_POOL_RECYCLE" :model-value="modelValue" placeholder="3600" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="打印 SQL 日志" env-key="SQLALCHEMY_ECHO" :model-value="modelValue" type="select" :options="[{label:'开启',value:'True'},{label:'关闭',value:'False'}]" @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>
  </div>
</template>
