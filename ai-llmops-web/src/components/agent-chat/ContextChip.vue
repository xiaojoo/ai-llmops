<script setup lang="ts">
/**
 * ContextChip — 输入框内的上下文附件标签
 * [文件图标] 文本，hover 显示关闭按钮，支持删除
 */
import { IconFile, IconClose } from '@arco-design/web-vue/es/icon'
import type { ContextAttachment } from './types'

defineProps<{
  attachment: ContextAttachment
}>()

const emit = defineEmits<{
  remove: [id: string]
}>()
</script>

<template>
  <div class="context-chip">
    <IconFile class="context-chip__file" :size="12" />
    <span class="context-chip__label">{{ attachment.label }}</span>
    <button
      class="context-chip__close"
      type="button"
      title="移除"
      @click.stop="emit('remove', attachment.id)"
    >
      <IconClose :size="10" />
    </button>
  </div>
</template>

<style scoped>
.context-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 22px;
  max-width: 100%;
  padding: 0 6px 0 8px;
  border-radius: 4px;
  border: 1px solid var(--border-chip);
  background: #232425;
  font-size: 11px;
  color: #b8b8b8;
  user-select: none;
}

.context-chip__file {
  color: var(--text-icon);
  flex-shrink: 0;
}

.context-chip__label {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.context-chip__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  border-radius: 3px;
  color: var(--text-muted);
  opacity: 0;
  transition:
    opacity 0.12s ease,
    background 0.12s ease,
    color 0.12s ease;
  flex-shrink: 0;
}

.context-chip:hover .context-chip__close {
  opacity: 1;
}

.context-chip__close:hover {
  background: var(--bg-active);
  color: #d0d0d0;
}
</style>
