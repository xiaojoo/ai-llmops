<script setup lang="ts">
/**
 * SessionList — 会话列表（可纵向滚动）
 * 支持搜索过滤（父级传入 query）与筛选
 */
import { computed } from 'vue'
import SessionItem from './SessionItem.vue'
import type { ChatSession, SessionFilter } from './types'

const props = withDefaults(
  defineProps<{
    sessions?: ChatSession[]
    activeId?: string
    query?: string
    filter?: SessionFilter
  }>(),
  {
    sessions: () => [],
  },
)

const emit = defineEmits<{
  select: [session: ChatSession]
}>()

const filtered = computed(() => {
  let list = props.sessions
  // 筛选
  if (props.filter === 'recent') {
    list = list.filter((s) => s.tags?.includes('recent'))
  } else if (props.filter === 'pinned') {
    list = list.filter((s) => s.pinned)
  }
  // 搜索
  const q = props.query?.trim().toLowerCase()
  if (q) {
    list = list.filter((s) => s.title.toLowerCase().includes(q))
  }
  return list
})
</script>

<template>
  <div class="session-list">
    <div v-if="filtered.length === 0" class="session-list__empty">没有会话</div>
    <SessionItem
      v-for="s in filtered"
      :key="s.id"
      :session="s"
      :active="s.id === props.activeId"
      @select="emit('select', $event)"
    />
  </div>
</template>

<style scoped>
.session-list {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 2px 0 8px;
  min-height: 0;
}

.session-list__empty {
  padding: 24px 16px;
  font-size: 12px;
  color: var(--text-muted);
  text-align: center;
}
</style>
