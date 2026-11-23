<script setup lang="ts">
/**
 * AgentChatPanel — 深色主题 AI Agent 聊天界面主容器
 * 单列布局：顶部标题栏 + 消息列表（可滚动）+ 底部输入框
 *
 * 用法：
 *   <AgentChatPanel :messages="messages" :title="appName" v-model:composer-text="text" @submit="onSend" />
 */
import SessionPanel from './SessionPanel.vue'
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
import './agent-chat.css'

withDefaults(
  defineProps<{
    // 必填（带默认值）：透传给 SessionPanel/MessageList（其 messages 为必填），避免 TS2322
    messages: ChatMessage[]
    /** 顶部标题（应用名等） */
    title?: string
    /** 应用名（消息卡片头部） */
    appName?: string
    /** 应用图标 URL */
    appIcon?: string
    attachments?: ContextAttachment[]
    composerText?: string
    composerMode?: ComposerMode
    sending?: boolean
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
</script>

<template>
  <div class="agent-chat agent-chat-panel">
    <SessionPanel
      :messages="messages"
      :title="title"
      :app-name="appName"
      :app-icon="appIcon"
      :attachments="attachments"
      :composer-text="composerText"
      :composer-mode="composerMode"
      :sending="sending"
      :mention-files="mentionFiles"
      :mention-loading="mentionLoading"
      :apps="apps"
      :sessions="sessions"
      :conversation-title="conversationTitle"
      :current-app-token="currentAppToken"
      :current-conversation-id="currentConversationId"
      :show-session-controls="showSessionControls"
      :show-audio-recorder="showAudioRecorder"
      :switching="switching"
      :workspaces="workspaces"
      :current-workspace="currentWorkspace"
      @update:composer-text="emit('update:composerText', $event)"
      @update:composer-mode="emit('update:composerMode', $event)"
      @update:recording="emit('update:recording', $event)"
      @submit="emit('submit')"
      @stop-send="emit('stop-send')"
      @refresh="emit('refresh')"
      @settings="emit('settings')"
      @refresh-apps="emit('refreshApps')"
      @select-app="emit('selectApp', $event)"
      @select-conversation="emit('selectConversation', $event)"
      @new-conversation="emit('newConversation')"
      @remove-attachment="emit('removeAttachment', $event)"
      @upload-file="emit('uploadFile')"
      @mention-query="emit('mentionQuery', $event)"
      @mention-select="emit('mentionSelect', $event)"
      @feedback="emit('feedback', $event)"
      @ask-user-submit="emit('ask-user-submit', $event)"
      @select-workspace="emit('selectWorkspace', $event)"
      @regenerate="emit('regenerate', $event)"
      @continue="emit('continue', $event)"
    />
  </div>
</template>

<style scoped>
.agent-chat-panel {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
}
</style>
