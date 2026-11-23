<script setup lang="ts">
import type { PropType } from 'vue'

type NodeMeta = {
  type: string
  label: string
  desc: string
  colorClass: string
  icon: string
}

const props = defineProps({
  visible: { type: Boolean, required: true, default: false },
  metaList: { type: Array as PropType<NodeMeta[]>, required: true, default: () => [] },
})

const emits = defineEmits(['update:visible', 'add-node', 'drag-start', 'switch-mode'])
</script>

<template>
  <div
    v-if="props.visible"
    class="absolute left-[15px] top-[100px] bottom-[300px] w-[320px] bg-white z-50 rounded-xl border shadow-lg overflow-hidden flex flex-col"
  >
    <!-- 固定头部行 -->
    <div class="flex items-center justify-between px-4 py-3 border-b shrink-0">
      <div class="text-base font-bold text-gray-700">节点列表</div>
      <div class="flex items-center gap-1">
        <a-button
          size="mini"
          type="text"
          class="!text-gray-700"
          @click="emits('switch-mode', 'dropdown')"
        >
          悬浮列表
        </a-button>
        <a-button aria-label="关闭" size="mini" type="text" class="!text-gray-700" @click="emits('update:visible', false)">
          <template #icon><icon-close /></template>
        </a-button>
      </div>
    </div>

    <!-- 组件列表 -->
    <div class="flex-1 overflow-scroll scrollbar-w-none p-3 flex flex-col gap-2">
      <div
        v-for="meta in props.metaList"
        :key="meta.type"
        class="flex flex-col px-3 py-2 gap-2 cursor-grab hover:bg-gray-50 active:cursor-grabbing rounded-xl"
        draggable="true"
        @dragstart="emits('drag-start', $event, meta.type)"
        @click="emits('add-node', meta.type)"
      >
        <div class="flex items-center gap-2">
          <a-avatar shape="square" :size="24" :class="`${meta.colorClass} rounded-lg`">
            <component :is="`icon-${meta.icon}`" />
          </a-avatar>
          <div class="text-gray-700 font-semibold">{{ meta.label }}</div>
        </div>
        <div class="text-gray-500 text-xs">{{ meta.desc }}</div>
      </div>
    </div>
  </div>
</template>
