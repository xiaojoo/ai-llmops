<script setup lang="ts">
/**
 * PromptHint — 输入框第一行提示
 * 「提示:」略亮 + 描述文字灰色
 */
defineProps<{
  /** 提示前缀 */
  label?: string
  /** 提示正文 */
  text?: string
}>()
</script>

<template>
  <div class="prompt-hint">
    <span class="prompt-hint__label">{{ label ?? '提示:' }}</span>
    <span class="prompt-hint__text">{{ text ?? '使用 /create-agent 为工作流搭建自定义智能体。' }}</span>
  </div>
</template>

<style scoped>
.prompt-hint {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 10px 12px 0;
  font-size: 11.5px;
  line-height: 1.4;
  user-select: none;
}

.prompt-hint__label {
  color: #9a9a9a;
  /* 窄视口下不换行，避免标签被挤断 */
  white-space: nowrap;
  flex-shrink: 0;
}

.prompt-hint__text {
  color: #6e6e6e;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
