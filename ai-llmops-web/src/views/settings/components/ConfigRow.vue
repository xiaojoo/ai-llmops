<script setup lang="ts">
import { computed, ref } from 'vue'

const props = defineProps<{
  label: string
  envKey: string
  modelValue: Record<string, string>
  sensitive?: boolean
  placeholder?: string
  type?: 'input' | 'select'
  options?: { label: string; value: string }[]
  hint?: string
  disabled?: boolean
}>()

const emit = defineEmits(['update:modelValue'])

const visible = ref(false)

const value = computed({
  get: () => props.modelValue[props.envKey] ?? '',
  set: (v) => emit('update:modelValue', { ...props.modelValue, [props.envKey]: v }),
})

const masked = computed(() => {
  const v = value.value
  if (!v) return '未配置'
  if (v.length <= 8) return '****'
  return v.slice(0, 4) + '****' + v.slice(-4)
})
</script>

<template>
  <div
    class="flex gap-3 py-2 border-b border-gray-100 last:border-0"
    :class="[hint ? 'items-start' : 'items-center', { 'opacity-60': disabled }]"
  >
    <div class="w-48 shrink-0">
      <div class="text-xs font-medium text-gray-600">{{ label }}</div>
      <div class="text-xs text-gray-400 font-mono mt-0.5 truncate">
        {{ envKey }}
      </div>
    </div>
    <div class="flex-1 min-w-0">
      <div class="flex items-center gap-2">
        <!-- select 类型 -->
        <a-select
          v-if="type === 'select'"
          v-model="value"
          size="small"
          class="flex-1"
          :disabled="disabled"
        >
          <a-option v-for="opt in options" :key="opt.value" :value="opt.value">{{
            opt.label
          }}</a-option>
        </a-select>

        <!-- 敏感字段：遮掩模式 -->
        <template v-else-if="sensitive">
          <a-input
            v-if="visible"
            v-model="value"
            :placeholder="placeholder || `输入 ${envKey}`"
            size="small"
            class="flex-1"
            allow-clear
            :disabled="disabled"
          >
            <template #suffix>
              <icon-eye-invisible
                v-if="!disabled"
                class="cursor-pointer !text-gray-400 hover:!text-gray-600"
                @click="visible = false"
              />
            </template>
          </a-input>
          <div
            v-else
            class="flex-1 flex items-center justify-between px-3 bg-gray-50 border border-gray-200 rounded text-xs text-gray-500 font-mono cursor-pointer"
            style="height: 28px; line-height: 28px"
            @click="disabled || (visible = true)"
          >
            <span>{{ masked }}</span>
            <icon-eye
              v-if="!disabled"
              class="!text-gray-400 hover:!text-gray-600 shrink-0 ml-2"
            />
          </div>
        </template>

        <!-- 普通字段 -->
        <a-input
          v-else
          v-model="value"
          :placeholder="placeholder || `输入 ${envKey}`"
          size="small"
          class="flex-1"
          allow-clear
          :disabled="disabled"
        />
      </div>
      <div v-if="hint" class="text-xs text-gray-400 mt-1">{{ hint }}</div>
    </div>
  </div>
</template>
