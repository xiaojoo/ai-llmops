<script setup lang="ts">
import { ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import FileManager from './components/FileManager.vue'
import ChromaVector from './components/VectorManager.vue'

const tabs = [
  { key: 'files', label: '文件管理' },
  { key: 'vectors', label: '向量数据' },
]

// tab 记忆：留在本页内一直有效（含刷新，刷新不跳回第一个）；
// 点击左侧菜单离开路由时清除 —— 下次进入默认第一个 tab（文件管理）。
const ACTIVE_TAB_STORAGE_KEY = 'llmops-chroma-active-tab'
const TAB_KEYS = tabs.map((t) => t.key)
const lastTab = localStorage.getItem(ACTIVE_TAB_STORAGE_KEY)
const activeTab = ref<string>(
  lastTab && TAB_KEYS.includes(lastTab) ? lastTab : 'files',
)
watch(activeTab, (v) => localStorage.setItem(ACTIVE_TAB_STORAGE_KEY, v))
onBeforeRouteLeave(() => {
  localStorage.removeItem(ACTIVE_TAB_STORAGE_KEY)
})
</script>

<template>
  <div class="flex-1 w-full min-h-0 h-full bg-white flex flex-col overflow-hidden">
    <div class="mx-6 mt-4 border border-gray-200 rounded-lg bg-white shrink-0 overflow-hidden">
      <div class="flex items-center justify-between h-14 px-4 border-b border-gray-100">
        <div>
          <span class="text-sm font-medium text-gray-700">ChromaDB</span>
          <span class="text-xs text-gray-400 ml-3"
            >ChromaDB是本地向量数据库，通过上传文件到服务器目录，进行检索，目前使用场景只有Agent
            RoBot</span
          >
        </div>
      </div>
      <div class="flex items-center gap-6 px-4 bg-white">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          class="py-2.5 text-sm transition-colors relative"
          :class="
            activeTab === tab.key
              ? 'text-blue-600 font-medium'
              : 'text-gray-500 hover:text-gray-700'
          "
          @click="activeTab = tab.key"
        >
          {{ tab.label }}
          <span
            v-if="activeTab === tab.key"
            class="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-600 rounded-t"
          />
        </button>
      </div>
    </div>
    <!-- 内容区 -->
    <div class="flex-1 min-h-0 overflow-y-auto px-6 pt-4">
      <file-manager v-if="activeTab === 'files'" />
      <chroma-vector v-if="activeTab === 'vectors'" />
    </div>
  </div>
</template>
