<script setup lang="ts">
/**
 * ChatComposer — 底部聊天输入区域（固定在底部）
 * 结构：圆角容器
 *   ├─ ContextChips（附件标签，可删除）
 *   ├─ MessageInput（透明多行输入）
 *   └─ ComposerToolbar（工具栏）
 * 容器下方：StatusBar（本地 / 默认审批）
 */
import { computed, nextTick, ref } from 'vue'
import ContextChip from './ContextChip.vue'
import MessageInput from './MessageInput.vue'
import ComposerToolbar from './ComposerToolbar.vue'
import type { ComposerMode, ContextAttachment, FileMentionItem, WorkspaceItem } from './types'

const props = withDefaults(
  defineProps<{
    modelValue?: string
    attachments?: ContextAttachment[]
    mode?: ComposerMode
    sending?: boolean
    recording?: boolean
    disabled?: boolean
    /** @ 提及项目文件列表（透传给 MessageInput） */
    mentionFiles?: FileMentionItem[]
    mentionLoading?: boolean
    /** 语音转文字开关（App 设置开启才显示麦克风） */
    showAudioRecorder?: boolean
    /** 可用工作区列表（IDE 当前打开的项目/文件夹） */
    workspaces?: WorkspaceItem[]
    /** 当前选中的工作区路径 */
    currentWorkspace?: string
  }>(),
  {
    modelValue: '',
    attachments: () => [],
    mode: 'agent',
    sending: false,
    recording: false,
    disabled: false,
    mentionFiles: () => [],
    mentionLoading: false,
    showAudioRecorder: true,
    workspaces: () => [],
    currentWorkspace: '',
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:mode': [mode: ComposerMode]
  'update:recording': [value: boolean]
  submit: []
  'stop-send': []
  removeAttachment: [id: string]
  uploadFile: []
  mentionQuery: [query: string | null]
  mentionSelect: [path: string]
  selectWorkspace: [path: string]
}>()

const inputRef = ref<InstanceType<typeof MessageInput> | null>(null)

const canSend = computed(() => props.modelValue.trim().length > 0 && !props.disabled)

// ===== 工作区 =====
const workspaceList = computed(() => props.workspaces ?? [])
const currentWorkspaceName = computed(() => {
  const hit = workspaceList.value.find((w) => w.path === props.currentWorkspace)
  if (hit) return hit.name
  return props.currentWorkspace ? props.currentWorkspace : '未识别'
})
const hasMultipleWorkspaces = computed(() => workspaceList.value.length > 1)

function onSelectWorkspace(path: string | number | Record<string, unknown> | undefined) {
  if (typeof path === 'string' && path) emit('selectWorkspace', path)
}

function onSubmit() {
  if (canSend.value && !props.sending) {
    emit('submit')
  }
}

function onRemove(id: string) {
  emit('removeAttachment', id)
  nextTick(() => inputRef.value?.focusInput())
}

function onToggleMic() {
  emit('update:recording', !props.recording)
}
</script>

<template>
  <div class="chat-composer">
    <div class="chat-composer__box">
      <!-- 工作区（小字；多个工作区时点击切换） -->
      <div class="chat-composer__workspace">
        <template v-if="hasMultipleWorkspaces">
          <a-dropdown trigger="click" @select="onSelectWorkspace">
            <span class="chat-composer__ws" title="点击切换工作区">
              <icon-folder />
              工作区：{{ currentWorkspaceName }}
              <icon-down />
            </span>
            <template #content>
              <a-doption v-for="w in workspaceList" :key="w.path" :value="w.path">
                {{ w.name }}
              </a-doption>
            </template>
          </a-dropdown>
        </template>
        <span v-else class="chat-composer__ws">
          <icon-folder />
          工作区：{{ currentWorkspaceName }}
        </span>
      </div>
      <div v-if="props.attachments.length > 0" class="chat-composer__chips">
        <ContextChip
          v-for="a in props.attachments"
          :key="a.id"
          :attachment="a"
          @remove="onRemove"
        />
      </div>
      <MessageInput
        ref="inputRef"
        :model-value="props.modelValue"
        :disabled="props.disabled"
        :mention-files="props.mentionFiles"
        :mention-loading="props.mentionLoading"
        @update:model-value="emit('update:modelValue', $event)"
        @submit="onSubmit"
        @mention-query="emit('mentionQuery', $event)"
        @mention-select="emit('mentionSelect', $event)"
      />
      <ComposerToolbar
        :mode="props.mode"
        :can-send="canSend"
        :sending="props.sending"
        :recording="props.recording"
        :show-audio-recorder="props.showAudioRecorder"
        @update:mode="emit('update:mode', $event)"
        @toggle-mic="onToggleMic"
        @send="onSubmit"
        @stop-send="emit('stop-send')"
        @upload-file="emit('uploadFile')"
      />
    </div>
  </div>
</template>

<style scoped>
.chat-composer {
  flex-shrink: 0;
  padding: 0 10px 6px;
  display: flex;
  flex-direction: column;
}

/* 圆角输入容器：空状态也保持完整高度；position:relative 供 @ 提及下拉绝对定位 */
.chat-composer__box {
  position: relative;
  display: flex;
  flex-direction: column;
  background: #1d1e20;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  min-height: 145px;
  max-height: 220px;
}

.chat-composer__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 6px 12px 0;
}

/* 工作区小字 */
.chat-composer__workspace {
  display: flex;
  align-items: center;
  padding: 8px 12px 0;
  color: #8b8f99;
  font-size: 11px;
  line-height: 1;
}

.chat-composer__ws {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #8b8f99;
  cursor: default;
}

.chat-composer__ws .arco-icon {
  color: #6b7280;
}
</style>
