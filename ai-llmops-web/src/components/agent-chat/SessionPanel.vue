<script setup lang="ts">
/**
 * SessionPanel — 聊天面板主体（单列）
 * SessionHeader（标题+刷新）+ MessageList（消息列表，可滚动）+ ChatComposer（固定底部）
 * 交互：刷新 / 添加菜单 / 消息反馈 / ask_user 选择
 */
import { ref } from 'vue'
import SessionHeader from './SessionHeader.vue'
import MessageList from './MessageList.vue'
import ChatComposer from './ChatComposer.vue'
import type {
  AskUserSubmitPayload,
  ChatMessage,
  ChatSession,
  ComposerMode,
  ContextAttachment,
  FileMentionItem,
  WebAppItem,
  WorkspaceItem,
} from './types'

const props = withDefaults(
  defineProps<{
    // 必填（带默认值）：传给 MessageList（其 messages 为必填），避免 TS2322
    messages: ChatMessage[]
    title?: string
    /** 应用名（消息卡片头部） */
    appName?: string
    /** 应用图标 URL */
    appIcon?: string
    attachments?: ContextAttachment[]
    composerText?: string
    composerMode?: ComposerMode
    sending?: boolean
    recording?: boolean
    /** @ 提及项目文件列表（透传） */
    mentionFiles?: FileMentionItem[]
    mentionLoading?: boolean
    /** 多 App 切换：可用的 App 列表（透传） */
    apps?: WebAppItem[]
    /** 当前 App 的会话列表（透传） */
    sessions?: ChatSession[]
    /** 当前会话标题（空 = 新会话） */
    conversationTitle?: string
    /** 当前 App token（标记选中项） */
    currentAppToken?: string
    /** 当前会话 id（标记选中项） */
    currentConversationId?: string
    /** 是否显示 App/会话切换控件 */
    showSessionControls?: boolean
    /** 语音转文字开关（App 设置开启才显示麦克风） */
    showAudioRecorder?: boolean
    /** 正在切换 App/加载会话（头部按钮转圈动画） */
    switching?: boolean
    /** 可用工作区列表（IDE 当前打开的项目/文件夹） */
    workspaces?: WorkspaceItem[]
    /** 当前选中的工作区路径 */
    currentWorkspace?: string
  }>(),
  {
    messages: () => [],
    title: '',
    appName: '',
    appIcon: '',
    attachments: () => [],
    composerText: '',
    composerMode: 'agent',
    sending: false,
    recording: false,
    mentionFiles: () => [],
    mentionLoading: false,
    apps: () => [],
    sessions: () => [],
    conversationTitle: '',
    currentAppToken: '',
    currentConversationId: '',
    showSessionControls: true,
    showAudioRecorder: true,
    switching: false,
    workspaces: () => [],
    currentWorkspace: '',
  },
)

const emit = defineEmits<{
  'update:composerText': [value: string]
  'update:composerMode': [mode: ComposerMode]
  'update:recording': [value: boolean]
  submit: []
  'stop-send': []
  refresh: []
  settings: []
  refreshApps: []
  selectApp: [item: WebAppItem]
  selectConversation: [id: string]
  newConversation: []
  removeAttachment: [id: string]
  uploadFile: []
  mentionQuery: [query: string | null]
  mentionSelect: [path: string]
  feedback: [payload: { message: ChatMessage; feedback: '' | 'like' | 'dislike' }]
  'ask-user-submit': [payload: { message: ChatMessage; payload: AskUserSubmitPayload }]
  selectWorkspace: [path: string]
  regenerate: [query: string]
  continue: [message: ChatMessage]
}>()

// ===== 状态 =====
const refreshing = ref(false)
const recording = ref(props.recording)

// ===== 交互 =====

function onRefresh() {
  if (refreshing.value) return
  refreshing.value = true
  emit('refresh')
  // 旋转动画持续 900ms
  setTimeout(() => {
    refreshing.value = false
  }, 900)
}

function onRemoveAttachment(id: string) {
  emit('removeAttachment', id)
}
</script>

<template>
  <div class="session-panel">
    <!-- 顶部：标题 + 刷新 -->
    <SessionHeader
      :refreshing="refreshing"
      :title="title"
      :apps="apps"
      :app-name="appName"
      :app-icon="appIcon"
      :sessions="sessions"
      :conversation-title="conversationTitle"
      :current-app-token="currentAppToken"
      :current-conversation-id="currentConversationId"
      :show-session-controls="showSessionControls"
      :switching="switching"
      @refresh="onRefresh"
      @settings="emit('settings')"
      @refresh-apps="emit('refreshApps')"
      @select-app="emit('selectApp', $event)"
      @select-conversation="emit('selectConversation', $event)"
      @new-conversation="emit('newConversation')"
    />

    <!-- 消息列表（可滚动，占满剩余空间） -->
    <MessageList
      :messages="messages"
      :app-name="appName"
      :app-icon="appIcon"
      @feedback="emit('feedback', $event)"
      @ask-user-submit="emit('ask-user-submit', $event)"
      @regenerate="emit('regenerate', $event)"
      @continue="emit('continue', $event)"
    />

    <!-- 底部输入区（固定） -->
    <ChatComposer
      :model-value="composerText"
      :attachments="attachments"
      :mode="composerMode"
      :sending="sending"
      :recording="recording"
      :mention-files="mentionFiles"
      :mention-loading="mentionLoading"
      :show-audio-recorder="showAudioRecorder"
      :workspaces="workspaces"
      :current-workspace="currentWorkspace"
      @update:model-value="emit('update:composerText', $event)"
      @update:mode="emit('update:composerMode', $event)"
      @update:recording="recording = $event; emit('update:recording', $event)"
      @submit="emit('submit')"
      @stop-send="emit('stop-send')"
      @remove-attachment="onRemoveAttachment"
      @upload-file="emit('uploadFile')"
      @mention-query="emit('mentionQuery', $event)"
      @mention-select="emit('mentionSelect', $event)"
      @select-workspace="emit('selectWorkspace', $event)"
    />
  </div>
</template>

<style scoped>
.session-panel {
  position: relative;
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  background: var(--bg-primary);
  overflow: hidden;
}
</style>
