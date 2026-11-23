<script setup lang="ts">
defineProps<{ title: string; subtitle?: string }>()
</script>

<template>
  <div class="border border-gray-200 rounded-lg mb-4 bg-white overflow-hidden">
    <div class="px-4 py-3 bg-gray-50 border-b border-gray-200">
      <div class="text-sm font-semibold text-gray-700">{{ title }}</div>
      <div v-if="subtitle" class="text-xs text-gray-400 mt-0.5">{{ subtitle }}</div>
    </div>
    <div class="px-4 py-1">
      <slot />
    </div>
  </div>
</template>
