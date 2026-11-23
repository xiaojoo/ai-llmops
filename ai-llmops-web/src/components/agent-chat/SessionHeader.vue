<script setup lang="ts">
/**
 * SessionHeader — 顶部标题区域
 * 左侧：App 选择下拉（当前应用图标+名称）；右侧：会话选择下拉（新建会话 + 当前 App 会话列表）、设置、刷新。
 * 数据与动作由父级（embed）提供；组件只负责展示与事件上报。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { IconRefresh, IconSettings, IconDown, IconPlus, IconLoading } from '@arco-design/web-vue/es/icon'
import type { ChatSession, WebAppItem } from './types'

const emit = defineEmits<{
  refresh: []
  settings: []
  selectApp: [item: WebAppItem]
  selectConversation: [id: string]
  newConversation: []
  /** 打开 App 下拉时请求父级刷新应用列表（新建的 App 能及时出现） */
  refreshApps: []
}>()

const props = withDefaults(
  defineProps<{
    /** 标题文案（无 App 名时的回退展示） */
    title?: string
    /** 刷新旋转动画 */
    refreshing?: boolean
    /** 可切换的 App 列表 */
    apps?: WebAppItem[]
    /** 当前 App 名称 */
    appName?: string
    /** 当前 App 图标 */
    appIcon?: string
    /** 当前 App 的会话列表 */
    sessions?: ChatSession[]
    /** 当前会话标题（无会话 = 空 → 显示"新会话"） */
    conversationTitle?: string
    /** 当前 App token（标记选中项） */
    currentAppToken?: string
    /** 当前会话 id（标记选中项） */
    currentConversationId?: string
    /** 是否显示 App/会话切换控件（演示页可关） */
    showSessionControls?: boolean
    /** 正在切换 App/加载会话（按钮显示转圈动画） */
    switching?: boolean
  }>(),
  {
    title: '',
    refreshing: false,
    apps: () => [],
    appName: '',
    appIcon: '',
    sessions: () => [],
    conversationTitle: '',
    currentAppToken: '',
    currentConversationId: '',
    showSessionControls: true,
    switching: false,
  },
)

const appMenuOpen = ref(false)
const convMenuOpen = ref(false)
const appMenuRef = ref<HTMLElement | null>(null)
const convMenuRef = ref<HTMLElement | null>(null)

function toggleAppMenu() {
  if (!props.showSessionControls) return
  const opening = !appMenuOpen.value
  appMenuOpen.value = opening
  convMenuOpen.value = false
  // 打开时请求父级刷新应用列表（新建的 App 能及时出现）
  if (opening) emit('refreshApps')
}
function toggleConvMenu() {
  if (!props.showSessionControls) return
  convMenuOpen.value = !convMenuOpen.value
  appMenuOpen.value = false
}
function pickApp(item: WebAppItem) {
  appMenuOpen.value = false
  // 传完整项（token/name/icon）：父级可乐观更新界面，不等网络
  if (item.token !== props.currentAppToken) emit('selectApp', item)
}
function pickConv(id: string) {
  convMenuOpen.value = false
  if (id !== props.currentConversationId) emit('selectConversation', id)
}
function pickNew() {
  convMenuOpen.value = false
  emit('newConversation')
}

// 点击组件外部关闭下拉
function onDocClick(e: MouseEvent) {
  const target = e.target as Node
  if (appMenuRef.value && !appMenuRef.value.contains(target)) appMenuOpen.value = false
  if (convMenuRef.value && !convMenuRef.value.contains(target)) convMenuOpen.value = false
}
onMounted(() => document.addEventListener('mousedown', onDocClick))
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocClick))
</script>

<template>
  <div class="session-header">
    <!-- 左侧：App 选择 -->
    <div v-if="props.showSessionControls" ref="appMenuRef" class="session-header__app">
      <button class="session-header__app-btn" type="button" title="切换应用" @click="toggleAppMenu">
        <img v-if="props.appIcon" :src="props.appIcon" class="session-header__app-icon" alt="" />
        <span class="session-header__app-name">{{ props.appName || props.title || '选择应用' }}</span>
        <IconLoading v-if="props.switching" class="ac-icon session-header__caret is-spinning" :size="10" />
        <IconDown v-else class="ac-icon session-header__caret" :size="10" />
      </button>
      <div v-if="appMenuOpen" class="header-dropdown header-dropdown--app">
        <div v-if="props.apps.length === 0" class="header-dropdown__empty">暂无可用应用</div>
        <button
          v-for="a in props.apps"
          :key="a.token"
          type="button"
          class="header-dropdown__item"
          :class="{ 'is-active': a.token === props.currentAppToken }"
          @click="pickApp(a)"
        >
          <img v-if="a.icon" :src="a.icon" class="header-dropdown__icon" alt="" />
          <span class="header-dropdown__label">{{ a.name || '未命名应用' }}</span>
          <span v-if="a.token === props.currentAppToken" class="header-dropdown__check">✓</span>
        </button>
      </div>
    </div>
    <span v-else class="session-header__title">{{ props.title || '会话' }}</span>

    <!-- 右侧：会话选择 + 设置 + 刷新 -->
    <div class="session-header__actions">
      <div v-if="props.showSessionControls" ref="convMenuRef" class="session-header__conv">
        <button class="session-header__btn session-header__conv-btn" type="button" title="切换会话" @click="toggleConvMenu">
          <span class="session-header__conv-name">{{ props.conversationTitle || '新会话' }}</span>
          <IconLoading v-if="props.switching" class="ac-icon session-header__caret is-spinning" :size="10" />
          <IconDown v-else class="ac-icon session-header__caret" :size="10" />
        </button>
        <div v-if="convMenuOpen" class="header-dropdown header-dropdown--conv">
          <button type="button" class="header-dropdown__item header-dropdown__item--new" @click="pickNew">
            <IconPlus :size="12" class="ac-icon" />
            <span class="header-dropdown__label">新建会话</span>
          </button>
          <div v-if="props.sessions.length === 0" class="header-dropdown__empty">暂无会话，点"新建会话"开始</div>
          <button
            v-for="s in props.sessions"
            :key="s.id"
            type="button"
            class="header-dropdown__item"
            :class="{ 'is-active': s.id === props.currentConversationId }"
            @click="pickConv(s.id)"
          >
            <span class="header-dropdown__label">{{ s.title || '未命名会话' }}</span>
            <span v-if="s.id === props.currentConversationId" class="header-dropdown__check">✓</span>
          </button>
        </div>
      </div>
      <button class="session-header__btn" type="button" title="设置" @click="emit('settings')">
        <IconSettings class="ac-icon" :size="15" />
      </button>
      <button
        class="session-header__btn"
        type="button"
        title="刷新"
        :class="{ 'is-spinning': props.refreshing }"
        @click="emit('refresh')"
      >
        <IconRefresh class="ac-icon" :size="15" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.session-header {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 36px;
  padding: 0 10px;
  flex-shrink: 0;
  user-select: none;
  gap: 8px;
}

.session-header__title {
  font-size: 13.5px;
  font-weight: 500;
  color: #e0e0e0;
  letter-spacing: 0.2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-header__actions {
  display: flex;
  align-items: center;
  /* 会话选择 / 设置 / 刷新 间隙收紧 */
  gap: 2px;
  flex-shrink: 0;
  min-width: 0;
}

.session-header__btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 4px;
  color: var(--text-icon);
  transition:
    background 0.15s ease,
    color 0.15s ease;
  flex-shrink: 0;
}

.session-header__btn:hover {
  background: var(--bg-hover);
  color: #d0d0d0;
}

.session-header__btn.is-active {
  background: var(--bg-active);
  color: #d0d0d0;
}

.session-header__btn.is-spinning .ac-icon {
  animation: ac-spin 0.8s linear infinite;
}

/* 切换中 loading 图标：is-spinning 加在图标自身（App/会话按钮的下拉箭头位置） */
.session-header__caret.is-spinning {
  animation: ac-spin 0.8s linear infinite;
}

@keyframes ac-spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

/* ===== App 选择（左侧） ===== */
.session-header__app {
  position: relative;
  min-width: 0;
  flex: 1;
}

.session-header__app-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  height: 26px;
  padding: 0 8px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: transparent;
  color: #e0e0e0;
  cursor: pointer;
  transition: background 0.15s ease;
}

.session-header__app-btn:hover {
  background: var(--bg-hover);
}

.session-header__app-icon {
  width: 16px;
  height: 16px;
  border-radius: 4px;
  object-fit: cover;
  flex-shrink: 0;
}

.session-header__app-name {
  font-size: 12.5px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 120px;
}

.session-header__caret {
  color: var(--text-muted);
  flex-shrink: 0;
}

/* ===== 会话选择（右侧） ===== */
.session-header__conv {
  position: relative;
}

.session-header__conv-btn {
  gap: 4px;
  width: auto;
  padding: 0 6px;
  max-width: 120px;
}

.session-header__conv-name {
  font-size: 12px;
  color: #c0c0c0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ===== 通用下拉 ===== */
.header-dropdown {
  position: absolute;
  top: 32px;
  z-index: 60;
  min-width: 180px;
  max-width: 240px;
  max-height: 260px;
  overflow-y: auto;
  background: #1d1e20;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  padding: 4px;
  box-sizing: border-box;
  /* 选项之间留间距 */
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.header-dropdown--app {
  left: 0;
}

.header-dropdown--conv {
  right: 0;
}

.header-dropdown__empty {
  padding: 10px 12px;
  font-size: 11.5px;
  color: var(--text-muted);
}

.header-dropdown__item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  /* 上下 padding 加大：选项更易点选、视觉不拥挤 */
  padding: 8px 12px;
  border-radius: 5px;
  background: transparent;
  border: none;
  color: #c8c8c8;
  font-size: 12px;
  text-align: left;
  cursor: pointer;
  min-width: 0;
}

.header-dropdown__item:hover {
  background: #2a2d31;
}

.header-dropdown__item.is-active {
  background: #26334d;
  color: #e0e0e0;
}

.header-dropdown__item--new {
  color: #60a5fa;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 5px 5px 0 0;
  margin-bottom: 2px;
}

.header-dropdown__icon {
  width: 16px;
  height: 16px;
  border-radius: 4px;
  object-fit: cover;
  flex-shrink: 0;
}

.header-dropdown__label {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.header-dropdown__check {
  flex-shrink: 0;
  color: #60a5fa;
  font-size: 11px;
}

/* 窄视口（<320px）：隐藏 App 选择框，会话选择按钮收窄、名称以 … 截断；
   左侧隐藏后容器只有一个子元素，space-between 会把它推到最左——
   改为靠右对齐，让右侧按钮组保持原位。 */
@media (max-width: 320px) {
  .session-header__app {
    display: none;
  }

  .session-header {
    justify-content: flex-end;
  }

  .session-header__conv-btn {
    max-width: 84px;
  }
}
</style>
