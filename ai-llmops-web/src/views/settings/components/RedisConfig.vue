<script setup lang="ts">
import ConfigGroup from './ConfigGroup.vue'
import ConfigRow from './ConfigRow.vue'

defineProps<{ modelValue: Record<string, string> }>()
defineEmits(['update:modelValue'])
</script>

<template>
  <div>
    <config-group title="Redis 连接配置">
      <config-row label="Host" env-key="REDIS_HOST" :model-value="modelValue" placeholder="127.0.0.1" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="Port" env-key="REDIS_PORT" :model-value="modelValue" placeholder="6379" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="Username" env-key="REDIS_USERNAME" :model-value="modelValue" placeholder="留空表示无用户名" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="Password" env-key="REDIS_PASSWORD" :model-value="modelValue" sensitive placeholder="留空表示无密码" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="DB 编号" env-key="REDIS_DB" :model-value="modelValue" placeholder="0" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="启用 SSL" env-key="REDIS_USE_SSL" :model-value="modelValue" type="select" :options="[{label:'否',value:'False'},{label:'是',value:'True'}]" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="超时时间(秒)" env-key="REDIS_SOCKET_TIMEOUT" :model-value="modelValue" placeholder="5" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="连接超时(秒)" env-key="REDIS_CONNECT_TIMEOUT" :model-value="modelValue" placeholder="5" @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>

    <config-group title="Celery 任务队列配置">
      <config-row label="Broker DB" env-key="CELERY_BROKER_DB" :model-value="modelValue" placeholder="1" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="Result Backend DB" env-key="CELERY_RESULT_BACKEND_DB" :model-value="modelValue" placeholder="1" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="忽略任务结果" env-key="CELERY_TASK_IGNORE_RESULT" :model-value="modelValue" type="select" :options="[{label:'否',value:'False'},{label:'是',value:'True'}]" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="结果过期时间(秒)" env-key="CELERY_RESULT_EXPIRES" :model-value="modelValue" placeholder="3600" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="启动时重试连接" env-key="CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP" :model-value="modelValue" type="select" :options="[{label:'是',value:'True'},{label:'否',value:'False'}]" @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>
  </div>
</template>
