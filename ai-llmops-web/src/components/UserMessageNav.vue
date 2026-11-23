<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

/**
 * 右侧用户消息导航条：每条用户消息一个圆点。
 * 高亮位置由「滚动进度」直接决定——滚动条滚到多少比例，就亮第几个圆点（顶部→第1个，底部→最后1个）。
 * 圆点数量 = 用户消息数（hover 显示对应消息摘要，点击跳转到对应进度位置）。
 */
const props = defineProps<{
  /** 用户消息列表（顺序与滚动方向一致：顶部→底部，第 1 条对应最顶部） */
  items: { id: string; query: string }[]
  /** 滚动容器元素（如虚拟滚动器的 $el），组件自行监听滚动 / 窗口尺寸变化 */
  scrollEl: HTMLElement | null
}>()

/** 导航条出现所需的最少用户消息数（≥2 条才显示）。 */
const NAV_MIN_MESSAGES = 2

/** 截断到最多 maxChars 字符，以省略号结尾。 */
function truncateNavText(text: string, maxChars: number): string {
  if (text.length <= maxChars) return text
  const cut = text.slice(0, Math.max(0, maxChars - 1)).trimEnd()
  return cut + '…'
}

// 标记盒子高度：默认固定最大高度；用户消息过多时压缩盒子并封顶面板，
// 避免面板超高。通过 CSS 变量交给每个盒子使用。
const NAV_BOX_MAX_HEIGHT = 20
const NAV_BOX_MIN_HEIGHT = 5
const NAV_MAX_PANEL_RATIO = 0.55
const NAV_MAX_PANEL_HEIGHT = 520

const navHostRef = ref<HTMLElement | null>(null)
const hoveredNavId = ref('')
const navBubbleTop = ref<number | null>(null)
const navOverflow = ref(false)
const navProgress = ref(0)

const hoveredNavIndex = computed(() =>
  props.items.findIndex((i) => i.id === hoveredNavId.value),
)
const hoveredNavQuery = computed(() => {
  const item = props.items.find((i) => i.id === hoveredNavId.value)
  return item ? truncateNavText(item.query, 200) : ''
})
const showNavBubble = (event: MouseEvent, itemId: string) => {
  hoveredNavId.value = itemId
  const host = navHostRef.value
  if (!host) return
  const target = event.currentTarget as HTMLElement
  const targetRect = target.getBoundingClientRect()
  const hostRect = host.getBoundingClientRect()
  navBubbleTop.value = targetRect.top - hostRect.top + targetRect.height / 2
}
const hideNavBubble = () => {
  hoveredNavId.value = ''
  navBubbleTop.value = null
}

const navRailVisible = computed(() => {
  return props.items.length >= NAV_MIN_MESSAGES && navOverflow.value
})

const navBoxHeight = computed(() => {
  const total = props.items.length
  if (total === 0) return NAV_BOX_MAX_HEIGHT
  const el = props.scrollEl
  const viewHeight = el?.clientHeight ?? window.innerHeight
  const maxPanel = Math.min(NAV_MAX_PANEL_HEIGHT, Math.max(0, viewHeight) * NAV_MAX_PANEL_RATIO)
  return Math.min(
    NAV_BOX_MAX_HEIGHT,
    Math.max(NAV_BOX_MIN_HEIGHT, (maxPanel - 24) / total),
  )
})

const navRailStyle = computed(() => {
  return {
    '--nav-box-h': `${navBoxHeight.value}px`,
  }
})

/** 当前高亮圆点下标：滚动进度 × (圆点数 - 1)，取整（0..count-1）。 */
const activeNavLineIndex = computed(() => {
  const total = props.items.length
  if (total === 0) return -1
  return Math.min(total - 1, Math.max(0, Math.round(navProgress.value * (total - 1))))
})

/** 点击圆点：按进度跳转（第 1 个 → 顶部，最后 1 个 → 底部）。 */
const scrollToNavLine = (lineIndex: number) => {
  const el = props.scrollEl
  if (!el) return
  const maxScroll = el.scrollHeight - el.clientHeight
  if (maxScroll <= 0) return
  const total = props.items.length
  const target = maxScroll * (lineIndex / Math.max(1, total - 1))
  el.scrollTo({ top: target, behavior: 'smooth' })
}

const updateActiveNav = () => {
  const el = props.scrollEl
  if (!el) return
  // 内容超过一屏才显示导航条
  navOverflow.value = el.scrollHeight > el.clientHeight + 1
  // 滚动进度：0（顶部）~ 1（底部），与圆点位置一一对应
  const maxScroll = el.scrollHeight - el.clientHeight
  navProgress.value = maxScroll > 0 ? Math.min(1, Math.max(0, el.scrollTop / maxScroll)) : 0
}

// 滚动容器变化时挂/卸监听；容器就绪后立即计算一次
watch(
  () => props.scrollEl,
  (el, oldEl) => {
    oldEl?.removeEventListener('scroll', updateActiveNav)
    el?.addEventListener('scroll', updateActiveNav, { passive: true })
    if (el) {
      nextTick(updateActiveNav)
    } else {
      navOverflow.value = false
      navProgress.value = 0
    }
  },
  { immediate: true },
)

// 消息数量/内容变化（加载更多、流式输出、虚拟滚动重排）后重算溢出与进度
watch(
  () => props.items,
  () => {
    nextTick(updateActiveNav)
  },
)

// 窗口尺寸变化时重算导航条（标记盒子高度 / 面板高度），与滚动/流式保持同步
const handleWindowResize = () => updateActiveNav()
window.addEventListener('resize', handleWindowResize)
onBeforeUnmount(() => {
  window.removeEventListener('resize', handleWindowResize)
  props.scrollEl?.removeEventListener('scroll', updateActiveNav)
})

/** 供父组件在虚拟滚动器重排（@reflown）等时机手动刷新 */
const refresh = () => updateActiveNav()
defineExpose({ refresh })
</script>

<template>
  <!-- fixed 而非 absolute：页面布局有 min-w-[1200px] 全局约束，窄窗口下 absolute 会被顶到
       屏幕右侧之外（布局右缘），fixed 锚定视口右缘保证任何窗口宽度都可见 -->
  <div
    v-if="navRailVisible"
    ref="navHostRef"
    class="fixed right-4 top-1/2 -translate-y-1/2 z-10"
    @mouseleave="hideNavBubble"
  >
    <div class="nio-nav" :style="navRailStyle">
      <button
        v-for="(item, idx) in items"
        :key="item.id"
        type="button"
        class="nio-nav-marker"
        :class="{ 'nio-nav-marker-active': idx === activeNavLineIndex }"
        :aria-label="`跳转到第 ${idx + 1} 条提问`"
        @mouseenter="showNavBubble($event, item.id)"
        @click="scrollToNavLine(idx)"
      ></button>
      <span class="nio-nav-count">{{ items.length }}</span>
      <div
        v-if="hoveredNavId && navBubbleTop !== null"
        class="pointer-events-none absolute z-20 -translate-y-1/2 nio-nav-tip"
        :style="{ top: `${navBubbleTop}px` }"
      >
        <span class="nio-nav-tip-title">{{
          hoveredNavIndex >= 0 ? `第 ${hoveredNavIndex + 1} 条提问` : ''
        }}</span>
        <span class="nio-nav-tip-body">{{ hoveredNavQuery }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.nio-nav {
  /* 圆点盒子高度：由 navRailStyle 内联注入覆盖，此处声明默认值便于 CSS 校验器识别 */
  --nav-box-h: 20px;
  position: relative;
  box-sizing: border-box;
  width: 24px;
  border-radius: 999px;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 0;
  padding: 10px 0 8px;
  background: transparent;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  border: 1px solid transparent;
  box-shadow: none;
  opacity: 0.55;
  transition:
    opacity 180ms ease,
    background 180ms ease,
    border-color 180ms ease,
    box-shadow 180ms ease;
}
.nio-nav:hover {
  opacity: 1;
  background: rgba(28, 28, 30, 0.08);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border-color: rgba(127, 127, 127, 0.25);
  box-shadow: 0 1px 6px rgba(0, 0, 0, 0.06);
}
.nio-nav-marker {
  box-sizing: border-box;
  width: 100%;
  height: var(--nav-box-h, 20px);
  flex: none;
  border: 0;
  padding: 0;
  margin: 0;
  cursor: pointer;
  pointer-events: auto;
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
}
.nio-nav-marker::before {
  content: '';
  box-sizing: border-box;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: rgba(136, 136, 136, 0.42);
  opacity: 0.85;
  transition:
    opacity 120ms ease,
    transform 120ms ease,
    background 120ms ease;
}
.nio-nav-marker:hover::before {
  opacity: 1;
  transform: scale(1.45);
  background: #888;
}
.nio-nav-marker-active::before {
  background: #3b82f6;
  opacity: 1;
  transform: scale(1.3);
}
.nio-nav-marker-active:hover::before {
  transform: scale(1.35);
  background: #3b82f6;
  opacity: 1;
}
.nio-nav-count {
  margin-top: 2px;
  text-align: center;
  font-size: 9px;
  line-height: 1;
  font-weight: 600;
  color: #999;
  pointer-events: none;
  user-select: none;
}
.nio-nav-tip {
  right: calc(100% + 10px);
  width: 280px;
  max-width: calc(100vw - 80px);
  max-height: 220px;
  overflow: hidden;
  box-sizing: border-box;
  border-radius: 10px;
  padding: 9px 11px;
  font-size: 12px;
  line-height: 1.5;
  color: #eee;
  background: rgba(28, 28, 30, 0.92);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18);
  transition: opacity 120ms ease;
}
.nio-nav-tip-title {
  display: block;
  font-weight: 600;
  margin-bottom: 4px;
  color: #4d6bfe;
}
.nio-nav-tip-body {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 8;
  overflow: hidden;
  word-break: break-word;
  max-height: 160px;
}
</style>
