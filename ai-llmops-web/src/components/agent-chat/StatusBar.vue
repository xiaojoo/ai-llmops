<script setup lang="ts">
/**
 * StatusBar — 输入框下方的窄状态栏（单行不换行，悬停提示）
 * [电脑] 本地   [盾牌] 默认审批
 */
import { IconDesktop, IconSafe } from '@arco-design/web-vue/es/icon'
</script>

<template>
  <div class="status-bar">
    <span class="status-bar__item" title="本地">
      <IconDesktop :size="11" />
      本地
    </span>
    <span class="status-bar__item" title="默认审批">
      <IconSafe :size="11" />
      默认审批
    </span>
  </div>
</template>

<style scoped>
.status-bar {
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: 16px;
  padding: 6px 12px 0;
  font-size: 10.5px;
  color: #777777;
  user-select: none;
  flex-shrink: 0;
}

.status-bar__item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: #777777;
  white-space: nowrap;
  flex-shrink: 0;
}

.status-bar__item :deep(.arco-icon) {
  color: #6e6e6e;
}
</style>
