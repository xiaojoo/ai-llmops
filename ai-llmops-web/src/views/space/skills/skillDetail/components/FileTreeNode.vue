<script setup lang="ts">
import type { SkillFile } from '@/models/skill.ts'

// 目录树结构：目录为嵌套子树，文件叶子节点为 { __file: SkillFile }
interface FileTreeNode {
  [key: string]: FileTreeNode | { __file: SkillFile }
}

type FileTreeNodeValue = FileTreeNode | { __file: SkillFile }

const props = defineProps<{
  tree: FileTreeNode
  selectedPath?: string
  expandedKeys: string[]
  prefix?: string
}>()

const emit = defineEmits<{
  select: [file: SkillFile]
  toggle: [key: string]
}>()

const getFullPath = (name: string) => (props.prefix ? `${props.prefix}/${name}` : name)

const isExpanded = (name: string) => props.expandedKeys.includes(getFullPath(name))

const isDir = (node: FileTreeNodeValue | undefined) => !node?.__file

// 将节点值收窄为子树 / 文件叶子（运行时为恒等操作，仅用于类型收窄）
const nodeChildren = (node: FileTreeNodeValue | undefined): FileTreeNode => node as FileTreeNode
const nodeFile = (node: FileTreeNodeValue | undefined): SkillFile =>
  (node as { __file: SkillFile }).__file

const sortedKeys = (tree: FileTreeNode) => {
  const keys = Object.keys(tree)
  // 文件夹排前面
  return keys.sort((a, b) => {
    const aIsDir = isDir(tree[a])
    const bIsDir = isDir(tree[b])
    if (aIsDir && !bIsDir) return -1
    if (!aIsDir && bIsDir) return 1
    return a.localeCompare(b)
  })
}
</script>

<template>
  <div>
    <div v-for="name in sortedKeys(tree)" :key="name">
      <!-- 文件夹 -->
      <div v-if="isDir(tree[name])">
        <div
          class="flex items-center gap-1.5 px-2 py-1 rounded cursor-pointer hover:bg-gray-100 text-sm text-gray-700"
          @click="emit('toggle', getFullPath(name))"
        >
          <icon-right
            class="!text-gray-400 transition-transform text-xs"
            :class="isExpanded(name) ? 'rotate-90' : ''"
          />
          <icon-folder class="!text-blue-400 text-sm" />
          <span>{{ name }}</span>
        </div>
        <!-- 递归子节点 -->
        <div v-if="isExpanded(name)" class="ml-3 border-l border-gray-100 pl-1">
          <file-tree-node
            :tree="nodeChildren(tree[name])"
            :selected-path="selectedPath"
            :expanded-keys="expandedKeys"
            :prefix="getFullPath(name)"
            @select="emit('select', $event)"
            @toggle="emit('toggle', $event)"
          />
        </div>
      </div>

      <!-- 文件 -->
      <div
        v-else
        class="flex items-center gap-1.5 px-2 py-1 rounded cursor-pointer text-sm"
        :class="
          selectedPath === nodeFile(tree[name]).path
            ? 'bg-blue-50 text-blue-700 font-medium'
            : 'text-gray-700 hover:bg-gray-100'
        "
        @click="emit('select', nodeFile(tree[name]))"
      >
        <!-- 占位符，对齐文件夹的箭头宽度 -->
        <span class="w-3 shrink-0" />
        <icon-file class="!text-gray-400 text-sm shrink-0" />
        <span class="truncate">{{ name }}</span>
      </div>
    </div>
  </div>
</template>
