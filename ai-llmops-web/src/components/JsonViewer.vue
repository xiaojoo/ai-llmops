<script setup lang="ts">
import { computed, ref } from 'vue'

const props = defineProps<{
  code: string
  language: string
  /** 内容区最大高度(px)，默认 800 */
  maxHeight?: number
}>()

const isCollapsed = ref(false)
const isCopied = ref(false)

// 纯手写：轻量级正则语法高亮
const highlightedCode = computed(() => {
  const rawCode = (props.code || '').trim()

  let html = rawCode.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

  if (props.language === 'json') {
    html = html.replace(
      /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
      (match) => {
        let cls = 'text-green-400'
        if (/^"/.test(match)) {
          if (/:$/.test(match)) {
            cls = 'text-blue-400 font-medium'
          }
        } else if (/true|false/.test(match)) {
          cls = 'text-pink-400 font-bold'
        } else if (/null/.test(match)) {
          cls = 'text-gray-500 italic'
        } else {
          cls = 'text-orange-400'
        }
        return `<span class="${cls}">${match}</span>`
      },
    )
  } else if (props.language === 'shell') {
    html = html.replace(/(#.*$)/gm, '<span class="text-gray-500 italic">$1</span>')
    html = html.replace(/('.*?'|".*?")/g, '<span class="text-green-400">$1</span>')
    html = html.replace(
      /\b(curl|echo|export|POST|GET|PUT|DELETE)\b/g,
      '<span class="text-blue-400 font-bold">$1</span>',
    )
    html = html.replace(
      /(\s)(-[a-zA-Z0-9]+|--[a-zA-Z0-9\-]+)/g,
      '$1<span class="text-purple-400">$2</span>',
    )
  }

  return html
})

const copyToClipboard = async () => {
  const textToCopy = (props.code || '').trim()
  if (!textToCopy) return

  try {
    await navigator.clipboard.writeText(textToCopy)
    isCopied.value = true
    setTimeout(() => {
      isCopied.value = false
    }, 2000)
  } catch (err) {
    console.error('复制失败!', err)
  }
}

const toggleCollapse = () => {
  isCollapsed.value = !isCollapsed.value
}
</script>

<template>
  <div
    class="rounded-lg overflow-hidden border border-gray-700 bg-[#1e1e1e] shadow-sm my-4 text-left"
  >
    <div
      class="flex items-center justify-between px-4 py-2 bg-[#2d2d2d] text-xs text-gray-300 select-none"
    >
      <span class="uppercase font-semibold tracking-wider">{{ language }}</span>

      <div class="flex items-center gap-4">
        <button
          @click="copyToClipboard"
          class="flex items-center gap-1 hover:text-white transition-colors focus:outline-none cursor-pointer"
        >
          <svg
            v-if="!isCopied"
            class="w-3.5 h-3.5"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
            ></path>
          </svg>
          <svg
            v-else
            class="w-3.5 h-3.5 text-green-400"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M5 13l4 4L19 7"
            ></path>
          </svg>
          <span :class="{ 'text-green-400': isCopied }">{{ isCopied ? '已复制' : '复制' }}</span>
        </button>

        <button
          @click="toggleCollapse"
          class="flex items-center gap-1 hover:text-white transition-colors focus:outline-none cursor-pointer"
        >
          <svg
            :class="{ 'rotate-180': isCollapsed }"
            class="w-3.5 h-3.5 transition-transform duration-200"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M19 9l-7 7-7-7"
            ></path>
          </svg>
          <span>{{ isCollapsed ? '展开' : '折叠' }}</span>
        </button>
      </div>
    </div>

    <div
      v-show="!isCollapsed"
      class="custom-scrollbar p-4 overflow-auto text-sm bg-[#1e1e1e] text-gray-200"
      :style="{ maxHeight: `${props.maxHeight ?? 800}px` }"
    >
      <pre class="m-0 font-mono leading-relaxed"><code v-html="highlightedCode"></code></pre>
    </div>
  </div>
</template>

<style scoped>
/* 增加整体滚动条的宽度和高度，给“透明边距”留出空间 */
.custom-scrollbar::-webkit-scrollbar {
  height: 12px;
  width: 12px;
}

/* 核心技巧：使用 padding-box 和与背景相同的边框，把实际的滑块“挤”细，并形成悬浮感 */
.custom-scrollbar::-webkit-scrollbar-thumb {
  background-color: #4b5563;
  border-radius: 10px;
  border: 4px solid #1e1e1e; /* 与代码块背景色 #1e1e1e 保持完全一致 */
  background-clip: padding-box; /* 让背景色不蔓延到 border，产生 4px 的悬浮间距 */
}

.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background-color: #6b7280;
}

.custom-scrollbar::-webkit-scrollbar-track {
  background-color: transparent;
}

/* 右下角的交汇处也完全透明，避免出现难看的正方形色块 */
.custom-scrollbar::-webkit-scrollbar-corner {
  background-color: transparent;
}
</style>
