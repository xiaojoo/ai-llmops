<script setup lang="ts">
import { ref } from 'vue'
import WeaviateVector from './components/WeaviateVectorManager.vue'

const activeTab = ref('weaviate')

const tabs = [{ key: 'weaviate', label: 'Weaviate 向量' }]
</script>

<template>
  <div class="flex-1 w-full min-h-0 h-full bg-white flex flex-col overflow-hidden">
    <div class="mx-6 mt-4 border border-gray-200 rounded-lg bg-white shrink-0 overflow-hidden">
      <div class="flex items-center justify-between h-14 px-4 border-b border-gray-100">
        <div>
          <span class="text-sm font-medium text-gray-700">向量数据库管理</span>
          <span class="text-xs text-gray-400 ml-3">
            管理 ChromaDB 与 Weaviate 向量数据，支持文档同步、分块查看与召回测试
          </span>
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
    <!-- 内容区：自然高度，整体滚动 -->
    <div class="flex-1 overflow-y-auto px-6 pt-4 pb-4">
      <weaviate-vector v-if="activeTab === 'weaviate'" />
    </div>
  </div>
</template>
