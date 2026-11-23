<script setup lang="ts">
/**
 * SessionItem — 单个会话列表项
 * 左侧小圆点 + 单行标题(ellipsis) + 相对时间
 */
import type { ChatSession } from './types'

const props = defineProps<{
  session: ChatSession
  active?: boolean
}>()

const emit = defineEmits<{
  select: [session: ChatSession]
}>()
</script>

<template>
  <div
    class="session-item"
    :class="{ 'is-active': props.active }"
    role="button"
    tabindex="0"
    @click="emit('select', props.session)"
    @keydown.enter="emit('select', props.session)"
  >
    <span class="session-item__dot" aria-hidden="true"></span>
    <div class="session-item__body">
      <div class="session-item__title" :title="props.session.title">{{ props.session.title }}</div>
      <div class="session-item__time">{{ props.session.time }}</div>
    </div>
  </div>
</template>

<style scoped>
.session-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 7px 10px 7px 16px;
  margin: 0 6px 3px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.12s ease;
}

.session-item:hover {
  background: var(--bg-hover);
}

.session-item.is-active {
  background: var(--bg-active);
}

/* 左侧小圆点 */
.session-item__dot {
  flex-shrink: 0;
  width: 4px;
  height: 4px;
  margin-top: 7px;
  border-radius: 50%;
  background: #555657;
}

.session-item.is-active .session-item__dot {
  background: #7a7b7c;
}

.session-item__body {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.session-item__title {
  font-size: 12.5px;
  line-height: 1.4;
  color: #d0d0d0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-item__time {
  font-size: 10.5px;
  line-height: 1.3;
  color: #777777;
}
</style>
