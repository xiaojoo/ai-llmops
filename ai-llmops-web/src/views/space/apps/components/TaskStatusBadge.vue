<script setup lang="ts">
// Task Rows 状态徽章：done=绿色勾 / failed=红色叉 / running=旋转进度环 / pending=静态圆环
// 视觉对齐参考实现 TaskRows 的 SpinnerRing + Badge。
defineProps<{
  status: 'done' | 'failed' | 'running' | 'pending'
  step?: string | number
}>()
</script>

<template>
  <span class="relative inline-flex size-6 shrink-0 items-center justify-center">
    <!-- 进度圆环（running / pending：完整的绿色圆环，不转动；转圈 = 未完成任务） -->
    <svg
      v-if="status === 'running' || status === 'pending'"
      width="24"
      height="24"
      class="absolute inset-0"
    >
      <circle cx="12" cy="12" r="11" fill="none" stroke="#10b981" stroke-width="2" />
    </svg>
    <span
      v-if="status === 'running' || status === 'pending'"
      class="relative text-[10.5px] font-semibold tabular-nums text-green-600"
    >
      {{ step }}
    </span>
    <!-- 勾 / 叉 徽章（done / failed） -->
    <span
      v-else
      class="flex size-[22px] items-center justify-center rounded-full text-white"
      :class="status === 'done' ? 'bg-green-500' : 'bg-red-500'"
    >
      <svg
        v-if="status === 'done'"
        width="13"
        height="13"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="3.5"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="M20 6L9 17l-5-5" />
      </svg>
      <svg
        v-else
        width="12"
        height="12"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="3.5"
        stroke-linecap="round"
      >
        <path d="M18 6L6 18M6 6l12 12" />
      </svg>
    </span>
  </span>
</template>
