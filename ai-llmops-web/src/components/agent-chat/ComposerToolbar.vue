<script setup lang="ts">
/**
 * ComposerToolbar — 输入框底部工具栏
 * 左：[+] [Bot] Agent [Robot] Chat
 * 右：[Mic] [发送↑]
 */
import {
  IconPlus,
  IconRobot,
  IconSend,
  IconTool,
  IconLoading,
  IconClose,
} from '@arco-design/web-vue/es/icon'
import LucideMic from './LucideMic.vue'
import type { ComposerMode } from './types'

const props = defineProps<{
  mode: ComposerMode
  canSend: boolean
  sending?: boolean
  recording?: boolean
  /** 语音转文字开关（App 设置开启才显示麦克风按钮） */
  showAudioRecorder?: boolean
}>()

const emit = defineEmits<{
  uploadFile: []
  'update:mode': [mode: ComposerMode]
  toggleMic: []
  send: []
  'stop-send': []
}>()
</script>

<template>
  <div class="composer-toolbar">
    <!-- 左组 -->
    <div class="composer-toolbar__group">
      <button
        class="toolbar-btn"
        type="button"
        title="Agent 模式"
        :class="{ 'is-active': props.mode === 'agent' }"
        @click="emit('update:mode', 'agent')"
      >
        <IconTool class="ac-icon" :size="14" />
        <span class="toolbar-btn__text">Agent</span>
      </button>

      <button
        class="toolbar-btn"
        type="button"
        title="Chat 模式（纯聊天）"
        :class="{ 'is-active': props.mode === 'chat' }"
        @click="emit('update:mode', 'chat')"
      >
        <IconRobot class="ac-icon" :size="14" />
        <span class="toolbar-btn__text">Chat</span>
      </button>
    </div>

    <!-- 右组：语音 + 加号(上传文件) + 发送 -->
    <div class="composer-toolbar__group">
      <button class="toolbar-btn" type="button" title="上传文件" @click="emit('uploadFile')">
        <IconPlus class="ac-icon" :size="14" />
      </button>
      <button
        v-if="props.showAudioRecorder !== false"
        class="toolbar-btn"
        type="button"
        :title="props.recording ? '点击结束说话' : '语音输入'"
        :class="{ 'is-recording': props.recording }"
        @click="emit('toggleMic')"
      >
        <!-- 录音中显示"● 结束"（点击结束并转文字）；空闲显示麦克风图标 -->
        <LucideMic v-if="!props.recording" class="ac-icon" :size="14" />
        <span v-else class="toolbar-btn__stop">
          <span class="toolbar-btn__stop-dot"></span>
          <span>结束</span>
        </span>
      </button>
      <!-- 发送中：变成"停止"按钮（可主动停止正在回复的 Agent，含编排子任务） -->
      <button
        v-if="props.sending"
        class="toolbar-btn is-stop"
        type="button"
        title="停止回复"
        @click="emit('stop-send')"
      >
        <IconClose class="ac-icon" :size="14" />
      </button>
      <!-- 发送按钮：与加号/语音同款 toolbar-btn 样式 -->
      <button
        v-else
        class="toolbar-btn"
        type="button"
        title="发送"
        :disabled="!props.canSend"
        @click="emit('send')"
      >
        <IconLoading v-if="props.sending" class="ac-icon is-spinning" :size="14" />
        <IconSend v-else class="ac-icon" :size="14" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.composer-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px 8px;
  gap: 4px;
}

.composer-toolbar__group {
  display: flex;
  align-items: center;
  gap: 2px;
}

.toolbar-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 24px;
  padding: 0 6px;
  border-radius: 4px;
  color: var(--text-icon);
  font-size: 12px;
  transition:
    background 0.12s ease,
    color 0.12s ease;
}

.toolbar-btn:hover {
  background: var(--bg-hover);
  color: #d0d0d0;
}

.toolbar-btn.is-active {
  background: var(--bg-active);
  color: #d8d8d8;
}

/* 主动停止按钮：警告色，提示可中止正在回复的 Agent */
.toolbar-btn.is-stop {
  color: #e05656;
  background: rgba(224, 86, 86, 0.12);
}

.toolbar-btn.is-stop:hover {
  background: rgba(224, 86, 86, 0.2);
  color: #ff6b6b;
}

.toolbar-btn__text {
  font-size: 12px;
  color: #9a9a9a;
}

.toolbar-btn:hover .toolbar-btn__text {
  color: #d0d0d0;
}

.toolbar-btn.is-recording {
  color: #e05656;
  background: rgba(224, 86, 86, 0.12);
}

.toolbar-btn__stop {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 500;
}

.toolbar-btn__stop-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #e05656;
  animation: mic-pulse 1.2s ease-in-out infinite;
}

@keyframes mic-pulse {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.4;
    transform: scale(0.8);
  }
}

.toolbar-btn:disabled {
  opacity: 0.4;
  cursor: default;
  color: #d0d0d0;
}

/* 发送中 loading 旋转 */
.toolbar-btn .is-spinning {
  animation: ac-spin 0.9s linear infinite;
}

@keyframes ac-spin {
  to {
    transform: rotate(360deg);
  }
}

/* 窄视口（<250px）：隐藏左侧组（Agent/Chat），只保留右侧 加号/语音/发送。
   左侧隐藏后 space-between 会把右侧组推到最左——改为靠右对齐保持原位。 */
@media (max-width: 250px) {
  .composer-toolbar__group:first-child {
    display: none;
  }

  .composer-toolbar {
    justify-content: flex-end;
  }
}

/* 更窄视口（<150px）：两侧组全部隐藏，仅剩输入框（靠回车发送） */
@media (max-width: 150px) {
  .composer-toolbar {
    display: none;
  }
}
</style>
