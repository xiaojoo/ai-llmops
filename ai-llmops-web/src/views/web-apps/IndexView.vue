<script setup lang="ts">
import 'vue-virtual-scroller/dist/vue-virtual-scroller.css'
import { useRoute, useRouter } from 'vue-router'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import {
  useGetAppConversations,
  useGetWebApp,
  useStopWebAppChat,
  useWebAppChat,
} from '@/hooks/use-web-app.ts'
import {
  useDeleteConversation,
  useGetConversationMessagesWithPage,
  useUpdateConversationIsPinned,
} from '@/hooks/use-conversation.ts'
import type { GetConversationMessagesWithPageResponse } from '@/models/conversation.ts'
import type { ChatFileItem } from '@/models/chat-file.ts'
import UpdateNameModal from './components/UpdateNameModal.vue'
import ShortTermMemoryView from './components/ShortTermMemoryView.vue'
import { useAccountStore } from '@/stores/account.ts'
import { useGenerateSuggestedQuestions } from '@/hooks/use-ai.ts'
import { getAppsWithPage } from '@/services/app.ts'
import { Message } from '@arco-design/web-vue'
import cloneDeep from 'lodash/cloneDeep'
import { QueueEvent } from '@/config'
import AiMessage from '@/views/space/apps/components/AiMessage.vue'
import SubAgentDetail from '@/views/space/apps/components/SubAgentDetail.vue'
import { focusState, setFocusThought } from '@/views/space/apps/components/agent-thought-state'
import { followupsAllowed } from '@/utils/chat-followups'
import { planLiveMerge } from '@/utils/chat-live-merge'
import { defaultFabPosition, resolveFabPosition } from '@/utils/app-fab-position'
import AskUserOptions from '@/components/AskUserOptions.vue'
import { DynamicScroller, DynamicScrollerItem } from 'vue-virtual-scroller'
import HumanMessage from '@/components/HumanMessage.vue'
import { useAudioPlayer } from '@/hooks/use-audio.ts'
import { updateMessageFeedback } from '@/services/conversation.ts'
import { submitWebAppChoice, updateWebAppConversationSettings } from '@/services/web-app.ts'
import type { WebAppSseFrame } from '@/services/web-app.ts'
import UserMessageNav from '@/components/UserMessageNav.vue'
import ChatInputBar from '@/components/ChatInputBar.vue'

// ===== 局部类型：WebApp 配置 / 会话 / SSE 流式事件数据 / 推理步骤（类型收窄后视图侧补充） =====
type WebAppAppConfig = {
  opening_statement: string
  opening_questions: string[]
  suggested_after_answer: { enable: boolean }
  features?: string[]
  speech_to_text?: { enable: boolean }
  text_to_speech?: { enable: boolean; auto_play?: boolean }
  dialog_round?: number
}

type WebAppConversation = {
  id: string
  name: string
  summary: string
  created_at: number
}

type ChatEventData = {
  id?: string
  message_id?: string
  task_id?: string
  // 本次 run 的 id：断流后按它调 resume 端点重挂（后端顶层 task_id 与 run_id 同源）
  run_id?: string
  conversation_id?: string
  event?: string
  thought?: string
  observation?: string
  llm_output?: string
  tool_calls?: { name?: string; args?: Record<string, unknown>; id?: string; type?: string }[]
  model_name?: string
  message?: unknown[]
  tool?: string
  tool_input?: Record<string, unknown>
  question?: string
  options?: string[]
  allow_custom?: boolean
  choice?: string
  sub_task_options?: { order: number; title: string; role_prompt?: string; expect_output?: string; depends_on?: number[] }[]
  trace?: {
    round: number
    strategy: string
    query: string
    k: number
    hits: number
    sufficient: boolean
    score: number
    missing: string
  }[]
  latency?: number
  total_token_count?: number
  total_price?: number
  sub_task_id?: string | null
  sub_task_title?: string
}

type AgentThought = {
  id: string
  position: number
  event: string
  thought: string
  observation: string
  llm_output?: string
  tool_calls?: { name?: string; args?: Record<string, unknown>; id?: string; type?: string }[]
  model_name?: string
  message?: unknown[]
  tool: string
  tool_input: Record<string, unknown>
  trace?: {
    round: number
    strategy: string
    query: string
    k: number
    hits: number
    sufficient: boolean
    score: number
    missing: string
  }[]
  latency: number
  total_token_count?: number
  total_price?: number
  created_at: number
  sub_task_id?: string | null
  sub_task_title?: string
  question?: string
  options?: string[]
  allow_custom?: boolean
  choice?: string
  task_id?: string
  sub_task_options?: { order: number; title: string; role_prompt?: string; expect_output?: string; depends_on?: number[] }[]
}

type MessageItem = GetConversationMessagesWithPageResponse['data']['list'][number]

type ScrollerInstance = {
  $el: HTMLElement
  scrollToItem: (index: number) => void
  scrollToBottom: () => void
}

const route = useRoute()
const router = useRouter()
const updateConversationNameModalVisible = ref(false)
const updateConversationNameId = ref('')
const newConversation = ref<WebAppConversation | null>(null)
const selectedConversation = ref('')
const query = ref('')
const image_urls = ref<string[]>([])
const file_urls = ref<ChatFileItem[]>([])
const message_id = ref('')
const task_id = ref('')
// 断流重连：本次 run 的 id 与最后收到的 SSE 帧序号（后端帧内 `id:`）。
// 刷新后 run_id 由消息列表接口回读（run_status=running 的那条），不依赖本地存储。
const run_id = ref('')
const last_event_id = ref(0)
// 当前在挂流的帧游标与失败标记：同一时刻只允许一条流（单 AbortController），故提到组件级，
// 让"首次提问"与"断流重连"两条流共用同一个 applyStreamFrame 事件处理器。
// 每次开流前由 startStream 复位，勿在别处复用这两个名字。
let position = 0
let chatFailed = false
const scroller = ref<ScrollerInstance | null>(null)
const messagesReady = ref(false)
const accountStore = useAccountStore()
const playingMessageId = ref('')

// 窄视口（<992px，左侧折叠为图标栏）状态：折叠时给图标显示 hover 气泡 label
const isNarrow = ref(false)
let narrowMediaQuery: MediaQueryList | null = null
const onNarrowChange = (e: MediaQueryListEvent | MediaQueryList) => {
  isNarrow.value = e.matches
}
onMounted(() => {
  narrowMediaQuery = window.matchMedia('(max-width: 991px)')
  onNarrowChange(narrowMediaQuery)
  narrowMediaQuery.addEventListener('change', onNarrowChange)
})
onBeforeUnmount(() => {
  narrowMediaQuery?.removeEventListener('change', onNarrowChange)
})

const { loading: getWebAppLoading, web_app, loadWebApp } = useGetWebApp()

// ===== App 选择（右侧悬浮按钮 + 弹框） =====
const apps = ref<{ token: string; name: string; icon: string }[]>([])
const appsLoading = ref(false)
const appPickerVisible = ref(false)

/** 拉取当前账号已发布的、有 token 的应用列表（用于 App 切换弹框）。 */
const loadApps = async () => {
  try {
    appsLoading.value = true
    const resp = await getAppsWithPage({ current_page: 1, page_size: 50, search_word: '' })
    const list = resp.data?.list ?? []
    apps.value = list
      .filter((a) => a.status === 'published' && a.token)
      .map((a) => ({ token: a.token, name: a.name, icon: a.icon }))
  } catch (e) {
    console.error('[WebApp] load apps failed:', e)
    apps.value = []
  } finally {
    appsLoading.value = false
  }
}

/** App 切换：记录最后选择并跳转到对应 /web-apps/:token 页面（整页刷新重新加载）。 */
const switchApp = (token: string) => {
  appPickerVisible.value = false
  if (!token || token === String(route.params?.token ?? '')) return
  rememberLastApp(token)
  // 整页跳转：保证切换后组件重新挂载、会话/消息/应用信息全部按新 app 加载
  window.location.href = `/web-apps/${token}${location.search}`
}

/** 当前 App token（路由参数），用于弹框高亮。 */
const currentAppToken = computed(() => String(route.params?.token ?? ''))

// ===== 记住最后一次选择的 App（localStorage） =====
const LAST_APP_KEY = 'webapp.lastSelectedAppToken'

/** 记录最后选择的 app token（下次打开 /web-apps 直接进入）。 */
const rememberLastApp = (token: string) => {
  try {
    localStorage.setItem(LAST_APP_KEY, token)
  } catch {
    /* localStorage 不可用时静默（如隐私模式） */
  }
}

/** 读取上次选择的 app token；无记录返回空串。 */
const lastSelectedAppToken = (): string => {
  try {
    return localStorage.getItem(LAST_APP_KEY) ?? ''
  } catch {
    return ''
  }
}

// ===== 右侧悬浮按钮（可拖拽） =====
const fabRef = ref<HTMLElement | null>(null)
/** 悬浮按钮尺寸（与 .app-fab 样式保持一致，用于边界计算）。 */
const FAB_SIZE = 44
const FAB_MARGIN = 16
/** 距边不超过这个数算"贴边"，贴边的按钮在窗口变化后跟着那条边走 */
const FAB_SNAP = 24
/** 悬浮按钮位置（left/top，相对视口），默认右边垂直居中。 */
const fabPos = ref({ x: 0, y: 0 })
/** 用户是否拖动过：没拖过就一直待在默认锚点上 */
const fabDragged = ref(false)
/** 上一次布局用的视口尺寸：判断"贴哪条边"必须用变化前的数，变化后到右边的距离已经不是原来的了 */
let fabLastViewport = { w: window.innerWidth, h: window.innerHeight }

/** 计算默认位置：右侧贴边、垂直居中。 */
const resetFabToDefault = () => {
  fabPos.value = defaultFabPosition(
    { w: window.innerWidth, h: window.innerHeight }, FAB_SIZE, FAB_MARGIN,
  )
}
resetFabToDefault()

/** 窗口尺寸变化时：贴边的按钮跟着那条边走，停在中间的只保证不出屏。 */
const onFabViewportResize = () => {
  const current = { w: window.innerWidth, h: window.innerHeight }
  const prev = fabLastViewport
  fabLastViewport = current
  fabPos.value = resolveFabPosition({
    x: fabPos.value.x,
    y: fabPos.value.y,
    prev,
    current,
    size: FAB_SIZE,
    margin: FAB_MARGIN,
    snap: FAB_SNAP,
    dragged: fabDragged.value,
  })
}
window.addEventListener('resize', onFabViewportResize)
onBeforeUnmount(() => window.removeEventListener('resize', onFabViewportResize))

let dragging = false
let dragStartX = 0
let dragStartY = 0
let dragOriginX = 0
let dragOriginY = 0

const onFabPointerDown = (e: PointerEvent) => {
  dragging = true
  dragStartX = e.clientX
  dragStartY = e.clientY
  dragOriginX = fabPos.value.x
  dragOriginY = fabPos.value.y
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
}

const onFabPointerMove = (e: PointerEvent) => {
  if (!dragging) return
  const dx = e.clientX - dragStartX
  const dy = e.clientY - dragStartY
  fabPos.value = {
    x: Math.max(0, Math.min(window.innerWidth - FAB_SIZE, dragOriginX + dx)),
    y: Math.max(0, Math.min(window.innerHeight - FAB_SIZE, dragOriginY + dy)),
  }
}

const onFabPointerUp = (e: PointerEvent) => {
  if (!dragging) return
  dragging = false
  ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
  // 拖拽位移很小视为点击：打开弹框
  const dx = Math.abs(e.clientX - dragStartX)
  const dy = Math.abs(e.clientY - dragStartY)
  if (dx < 6 && dy < 6) {
    appPickerVisible.value = !appPickerVisible.value
  } else {
    // 真拖动过：此后窗口变化按"它贴住哪条边"重算，不再回到默认锚点
    fabDragged.value = true
  }
}

/** 弹框位置（fixed，优先按钮左侧；左侧空间不足时放右侧）。 */
const fabPopoverPos = computed(() => {
  const popWidth = 280
  const leftSpace = fabPos.value.x - 12
  const left = leftSpace >= popWidth ? fabPos.value.x - 12 - popWidth : fabPos.value.x + FAB_SIZE + 12
  // 垂直方向与按钮大致对齐，视口内修正
  const top = Math.max(8, Math.min(fabPos.value.y + (FAB_SIZE - 300) / 2, window.innerHeight - 320))
  return { left, top }
})

// 点击弹框外部关闭（弹框自身与按钮的点击不触发关闭）
const onDocPointerDown = (e: PointerEvent) => {
  if (!appPickerVisible.value) return
  const target = e.target as Node
  const fab = fabRef.value
  const pop = popoverRef.value
  if (fab && fab.contains(target)) return
  if (pop && pop.contains(target)) return
  appPickerVisible.value = false
}
const popoverRef = ref<HTMLElement | null>(null)
document.addEventListener('pointerdown', onDocPointerDown)
onBeforeUnmount(() => document.removeEventListener('pointerdown', onDocPointerDown))

const {
  loading: getWebAppConversationsLoading,
  pinned_conversations,
  unpinned_conversations,
  loadWebAppConversations,
} = useGetAppConversations()

const { handleDeleteConversation } = useDeleteConversation()
const { handleUpdateConversationIsPinned } = useUpdateConversationIsPinned()
const {
  loading: getConversationMessagesWithPageLoading,
  messages,
  loadConversationMessagesWithPage,
} = useGetConversationMessagesWithPage()
const {
  loading: webAppChatLoading,
  handleWebAppChat,
  handleResumeWebAppChat,
  abort: abortWebAppChat,
} = useWebAppChat()
const { loading: stopWebAppChatLoading, handleStopWebAppChat } = useStopWebAppChat()
const { suggested_questions, handleGenerateSuggestedQuestions } = useGenerateSuggestedQuestions()
const {
  startAudioStream: _startAudioStream,
  stopAudioStream: _stopAudioStream,
  isPlaying,
  textToAudioLoading,
} = useAudioPlayer()

const can_image_input = computed(() => {
  if (web_app.value) {
    return (web_app.value?.app_config as WebAppAppConfig | undefined)?.features?.includes(
      'image_input',
    )
  }
  return false
})

const can_speech_to_text = computed(() => {
  if (web_app.value) {
    return (web_app.value?.app_config as WebAppAppConfig | undefined)?.speech_to_text?.enable
  }
  return false
})

// 定义会话计算属性，动态展示当前选中会话
const conversation = computed(() => {
  // 判断是否选中新会话，如果是则直接返回新会话数据
  if (selectedConversation.value === 'new_conversation') {
    return newConversation.value
  } else if (selectedConversation.value !== '') {
    // 查询置顶会话数据，如果不为空则直接返回
    const item = pinned_conversations.value.find((item) => item.id === selectedConversation.value)
    if (item) return item

    // 置顶会话查询不到数据，则查询非置顶数据
    return unpinned_conversations.value.find((item) => item.id === selectedConversation.value)
  }
  return null
})

const navItems = computed(() => messages.value.slice().reverse())
const userMessageNavRef = ref<InstanceType<typeof UserMessageNav> | null>(null)

// ===== 顶部右栏「子任务」下拉：当前上下文消息中出现的编排子任务（按首次出现顺序去重） =====
type SubTaskOption = { label: string; value: string }

/** 当前会话上下文里出现的全部编排子任务选项（标题为空回退"子任务 N"，规则同任务详情分组）。 */
const subTaskOptions = computed<SubTaskOption[]>(() => {
  const result: SubTaskOption[] = []
  const seen = new Set<string>()
  // messages 最新在前：反转后按时间先后遍历，与"任务详情"视图的分组/编号口径一致
  const ordered = [...messages.value].reverse()
  for (const msg of ordered) {
    for (const thought of msg.agent_thoughts || []) {
      const subTaskId = thought.sub_task_id
      if (!subTaskId || seen.has(subTaskId)) continue
      seen.add(subTaskId)
      const title = thought.sub_task_title?.trim() || `子任务 ${result.length + 1}`
      result.push({ label: title, value: subTaskId })
    }
  }
  return result
})

// 下拉选中值：非空 = 任务详情视图聚焦该子任务（仅该子任务轨迹）；空 = 查看全部子任务
const activeSubTaskId = ref('')

/** 选中某子任务 → 切到"任务详情"视图并聚焦该子任务（复用任务详情同款轨迹渲染，不另开路由）。
 *  选中"查看全部子任务"（__all__）→ 显示全部子任务轨迹。 */
const onSubTaskSelect = (subTaskId: unknown) => {
  const raw = String(subTaskId ?? '')
  // '__all__' 与 '' 均表示查看全部
  activeSubTaskId.value = raw === '__all__' || raw === '' ? '' : raw
  viewMode.value = 'subagents'
}

// ===== 运行中流式消息（跨会话隔离）：SSE 回调固定写入发起会话的消息对象 =====
// 切走会话时不 abort SSE：任务在后台继续，事件继续到达。
// 回调绝不能写 messages.value[0]——messages 已被替换为新会话数组，会把旧任务事件写进新会话。
// 因此发送时捕获消息对象快照，回调只写该对象；切回原会话时再合并回视图（见 loadConversationWithScroll）。
const activeStreamMessage = shallowRef<MessageItem | null>(null)
// 开流那一刻选中的会话键（'new_conversation' 或真实 id），整个流期间不变；
// activeStreamConversationId 会在回包后换成真实 id，两者一起用于判定"在挂的流属于哪个会话"
const activeStreamKey = ref('')
// 该进行中消息所属会话 id（'' = new_conversation 尚未落会话）
const activeStreamConversationId = ref('')

const changeIsPinned = async (idx: number, origin_is_pinned: boolean) => {
  const conversation = origin_is_pinned
    ? pinned_conversations.value[idx]
    : unpinned_conversations.value[idx]

  if (!conversation) return

// 调用 hooks 发起 api 请求
  await handleUpdateConversationIsPinned(conversation.id, !origin_is_pinned, () => {
// 执行成功调用回调，更新会话位置
    if (origin_is_pinned) {
      pinned_conversations.value.splice(idx, 1)
      unpinned_conversations.value.push(conversation)
    } else {
      unpinned_conversations.value.splice(idx, 1)
      pinned_conversations.value.push(conversation)
    }
  })
}

const updateName = (idx: number, origin_is_pinned: boolean) => {
  const conversation = origin_is_pinned
    ? pinned_conversations.value[idx]
    : unpinned_conversations.value[idx]

  if (!conversation) return

  updateConversationNameId.value = conversation.id
  updateConversationNameModalVisible.value = true
}

const successUpdateNameCallback = (conversation_id: string, conversation_name: string) => {
  const pinnedItem = pinned_conversations.value.find((item) => item.id === conversation_id)
  if (pinnedItem) {
    pinnedItem.name = conversation_name
  } else {
    const unpinnedItem = unpinned_conversations.value.find((item) => item.id === conversation_id)
    if (unpinnedItem) {
      unpinnedItem.name = conversation_name
    }
  }
}

// 定义删除回话处理器
const deleteConversation = async (idx: number, origin_is_pinned: boolean) => {
  // 根据idx提取数据
  const conversation = origin_is_pinned
    ? pinned_conversations.value[idx]
    : unpinned_conversations.value[idx]

  if (!conversation) return

  // 调用hooks发起请求
  handleDeleteConversation(conversation.id, async () => {
    if (selectedConversation.value === conversation.id) {
      // 删除的是当前会话：会话本身已销毁，"后台继续"无处可看，直接停止任务再切新会话
      // （不弹"停止/后台继续"确认框——删除对话框已确认过销毁语义）
      await handleStop()
      switchToNewConversation()
    }
    if (origin_is_pinned) {
      pinned_conversations.value.splice(idx, 1)
    } else {
      unpinned_conversations.value.splice(idx, 1)
    }
  })
}

// 无确认的纯切换函数：addConversation（弹确认）与 deleteConversation（会话已销毁无需确认）共用
const switchToNewConversation = () => {
  // 将选择会话切换到new_conversation
  selectedConversation.value = 'new_conversation'
  viewMode.value = 'chat'

  // 如果没有新会话则创建一个
  if (!newConversation.value) {
    newConversation.value = {
      id: '',
      name: 'New Conversation',
      summary: '',
      created_at: 0,
    }
  }
}

// 定义新增会话处理器（任务运行中新建会话同样不中断：切走即可，后台继续跑）
const addConversation = () => {
  switchToNewConversation()
}

// 定义还原滚动高度函数
let navLoadingMore = false
let restoreMsgScrollTop = 0
let restoreMsgScrollHeight = 0

const restoreMessageScroll = () => {
  const msgEl = scroller.value?.$el as HTMLElement | undefined
  if (msgEl) {
    msgEl.scrollTop = restoreMsgScrollTop + (msgEl.scrollHeight - restoreMsgScrollHeight)
  }
  navLoadingMore = false
}

const loadMoreConversations = async () => {
  if (getConversationMessagesWithPageLoading.value || navLoadingMore) return
  const conversationId = conversation.value?.id
  if (!conversationId) return

  const msgEl = scroller.value?.$el as HTMLElement | undefined
  restoreMsgScrollTop = msgEl?.scrollTop ?? 0
  restoreMsgScrollHeight = msgEl?.scrollHeight ?? 0

  navLoadingMore = true
  await loadConversationMessagesWithPage(conversationId, false)
  await nextTick()
  requestAnimationFrame(() => {
    if (navLoadingMore) restoreMessageScroll()
  })
}

// 定义滚动函数
const handleScroll = async (event: UIEvent) => {
  const { scrollTop } = event.target as HTMLElement
  if (scrollTop <= 0 && !getConversationMessagesWithPageLoading.value) {
    await loadMoreConversations()
  }
}

// 归档消息历史原文展开状态（按消息 id 记录）
const archivedExpandedIds = ref<Set<string>>(new Set())
const openArchivedMessage = (item: { id: string }) => {
  const next = new Set(archivedExpandedIds.value)
  if (next.has(item.id)) {
    next.delete(item.id)
  } else {
    next.add(item.id)
  }
  archivedExpandedIds.value = next
}

// ===== 任务详情：页内 tab（对话 / 任务详情 / 短期记忆） =====
// 所有任务都显示任务详情：tab 常显；任务详情展示当前上下文全部消息的完整轨迹。
type ViewMode = 'chat' | 'subagents' | 'memory'
const viewMode = ref<ViewMode>('chat')

// 运行流程点击步骤 → 任务详情跳转联动（module 级共享焦点）
const onThoughtStepClick = (messageId: string, thought: AgentThought) => {
  setFocusThought(messageId, thought.id)
  viewMode.value = 'subagents'
}

// ===== 设置弹框：短期记忆（上下文携带轮数，按会话保存） =====
const settingsVisible = ref(false)
const settingsRound = ref<number>(3)
const settingsUseDefault = ref(false)
const settingsSaving = ref(false)

// 应用默认短期记忆轮数
const appDefaultRound = computed(() => {
  const cfg = web_app.value?.app_config as WebAppAppConfig | undefined
  return typeof cfg?.dialog_round === 'number' ? cfg.dialog_round : 3
})

// 当前会话设置的短期记忆轮数（会话覆盖值，未设置则为 null）
const conversationDialogRound = computed<number | null>(() => {
  const conv = conversation.value
  return conv && 'dialog_round' in conv
    ? ((conv as unknown as { dialog_round?: number | null }).dialog_round ?? null)
    : null
})

// 短期记忆视图展示用的生效轮数（会话覆盖值或应用默认值）
const effectiveDialogRound = computed<number>(() => conversationDialogRound.value ?? appDefaultRound.value)

const openSettings = () => {
  const override = conversationDialogRound.value
  settingsUseDefault.value = override === null
  settingsRound.value = override ?? appDefaultRound.value
  settingsVisible.value = true
}

// 数字输入框（普通 input，不用 Arco a-input-number——其内部输入框自带 aria-hidden 且有高度塌陷问题）
const onSettingsRoundInput = (e: Event) => {
  const raw = (e.target as HTMLInputElement).value
  const n = Number(raw)
  if (raw === '' || Number.isNaN(n)) {
    settingsRound.value = 0
    return
  }
  settingsRound.value = Math.min(100, Math.max(0, Math.trunc(n)))
}

const saveSettings = async () => {
  const conv = conversation.value
  if (!conv?.id) {
    Message.warning('请先选择会话')
    return
  }
  const dialogRound = settingsUseDefault.value ? null : settingsRound.value
  settingsSaving.value = true
  try {
    await updateWebAppConversationSettings(String(route.params?.token), conv.id, {
      dialog_round: dialogRound,
    })
    // 本地回写会话覆盖值
    const target = pinned_conversations.value.find((c) => c.id === conv.id)
    if (target) {
      ;(target as unknown as { dialog_round?: number | null }).dialog_round = dialogRound
    } else {
      const un = unpinned_conversations.value.find((c) => c.id === conv.id)
      if (un) (un as unknown as { dialog_round?: number | null }).dialog_round = dialogRound
    }
    Message.success('短期记忆设置已保存，下次对话生效')
    settingsVisible.value = false
  } catch {
    Message.error('保存失败，请重试')
  } finally {
    settingsSaving.value = false
  }
}

// 摘要行/tab 出现时压缩内容区高度，避免挤掉底部输入框
const contentHeightStyle = computed(() => {
  // 摘要行已并入顶部会话名称栏（h-16，高度不随子任务变化），内容区无需额外补偿
  return { height: `calc(100vh - 64px)` }
})

// 定义输入框提交函数
const handleSubmit = async () => {
  // 检测是否录入了query，如果没有则结束
  if (query.value.trim() === '') {
    Message.warning('用户提问不能为空')
    return
  }
  await sendChat(query.value, image_urls.value, file_urls.value, {})
}

// 断点续跑：重发原 query 并携带 resume: true + 被恢复的原始消息 id（后端按 message_id 定位断点）
const resumeMessage = async (message: MessageItem) => {
  await sendChat(message.query, [], [], { resume: true, resumeMessageId: message.id })
}

// 重新生成：用该条回答对应的用户输入再发一次（仅文本）
const onRegenerate = async (message: MessageItem) => {
  await sendChat(message.query, [], [], {})
}

// 正在编辑的用户消息 id（提升到父级管理：虚拟列表会复用/重建 HumanMessage，
// 本地编辑态会被重置导致“闪一下又收起”，由父级持有才能稳定展开）
const editingMessageId = ref('')

// 编辑用户消息后发送：用修改后的文本重新生成（仅文本）
const onEditSubmit = async (editedText: string) => {
  editingMessageId.value = ''
  await sendChat(editedText, [], [], {})
}

// 通用发送逻辑：普通提问 / 断点续跑共用
const sendChat = async (
  text: string,
  images: string[],
  files: ChatFileItem[],
  options: { resume?: boolean; resumeMessageId?: string },
) => {
  // 检测上次提问是否结束，如果没结束不能发起新提问
  if (webAppChatLoading.value) {
    Message.warning('上一次提问还未结束，请稍等')
    return
  }

  suggested_questions.value = []
  message_id.value = ''
  task_id.value = ''
  viewMode.value = 'chat'
  const selectedConversationTmp = cloneDeep(selectedConversation.value)
  // 复位共用游标与失败标记（applyStreamFrame 读写组件级同名变量）
  position = 0
  chatFailed = false

  // 往消息列表中添加基础人类消息。注意：必须从 messages.value[0] 取 Vue reactive proxy 作为
  // 后续写入口——直接用原始对象字面量会导致 agent_thoughts.push 落在普通数组上，视图不更新
  // （表现为 ask_user 已落库、切任务详情能看到，但实时气泡/弹框不渲染）。
  messages.value.unshift({
    id: `temp_${Date.now()}_${Math.random().toString(36).substring(2)}`,
    conversation_id: '',
    query: text,
    image_urls: images,
    file_urls: files,
    answer: '',
    total_token_count: 0,
    latency: 0,
    feedback: '',
    error: '',
    agent_thoughts: [],
    is_archived: false,
    created_at: 0,
  } as MessageItem)
  // 登记进行中消息（reactive proxy 引用）：SSE 回调固定写该对象——即使后续切走会话
  // messages.value 被替换，事件也只更新本条消息（不串会话）；切回时由
  // loadConversationWithScroll 合并回视图。切走「后台继续」期间该 proxy 仍由 Vue 托管。
  const streamedMessage = messages.value[0] as MessageItem | undefined
  activeStreamKey.value = selectedConversationTmp
  if (!streamedMessage) {
    // 理论不可达（刚 unshift）；防御性兜底：直接丢弃本条流式更新，避免回调写空
    activeStreamMessage.value = null
    activeStreamConversationId.value = ''
  } else {
    activeStreamMessage.value = streamedMessage
    activeStreamConversationId.value =
      selectedConversationTmp === 'new_conversation' ? '' : selectedConversationTmp
  }

  // 初始化推理过程数据，并清空输入数据
  const humanImageUrls = images
  const humanQuery = text
  const humanFileIds = files.map((file) => file.id)
  query.value = ''
  image_urls.value = []
  file_urls.value = []

  // 调用hooks发起请求
  const req = {
    conversation_id:
      selectedConversation.value === 'new_conversation' ? '' : selectedConversation.value,
    query: humanQuery,
    image_urls: humanImageUrls,
    file_ids: humanFileIds,
    ...(options.resume ? { resume: true, resume_message_id: options.resumeMessageId ?? '' } : {}),
  }

  await handleWebAppChat(String(route.params?.token), req, applyStreamFrame)
  await finishStream(selectedConversationTmp)
}

/**
 * 应用一帧 SSE。首次提问与断流重连共用同一处理器：后端真实流与 resume 端点走同一个
 * agent_thought_to_sse_frame 序列化，帧结构一致，因此这里不需要区分来源。
 */
const applyStreamFrame = (event_response: WebAppSseFrame) => {
    // 提取流式事件响应数据以及事件名称
    const event = event_response?.event
    const data = event_response?.data as ChatEventData | undefined
    // 断流重连游标：记下 run_id 与最后收到的帧序号，断开后按它续传
    if (event_response?.lastEventId) {
      last_event_id.value = Number(event_response.lastEventId) || last_event_id.value
    }
    if (data?.run_id) run_id.value = data.run_id
    const event_id = data?.id

    // 固定写发送时捕获的消息对象（绝不读 messages.value[0]：切走会话后数组已被替换，
    // 读它会把手头任务的事件写进新会话的首条消息 → 串会话）
    const currentMessage = activeStreamMessage.value
    if (!currentMessage) return

    const agent_thoughts = currentMessage.agent_thoughts

    // 初始化数据检测与赋值
    if (message_id.value === '' && data?.message_id) {
      task_id.value = data?.task_id ?? ''
      message_id.value = data?.message_id ?? ''
      currentMessage.id = data?.message_id ?? ''
      currentMessage.conversation_id = data?.conversation_id ?? ''
      // 会话已确定（new_conversation 首轮或已有会话回包）：登记归属，供切回合并
      if (data?.conversation_id) {
        activeStreamConversationId.value = String(data.conversation_id)
      }
    }

    // 循环处理得到的事件
    if (event !== QueueEvent.ping) {
      // Task 4 ruling：后端 ask_user 分支后仍会发布重复的 agent_action(tool='ask_user') 事件，
      // 过滤掉，避免渲染幻影"调用工具"卡片
      if (event === QueueEvent.agentAction && data?.tool === 'ask_user') {
        // 忽略重复事件
      } else if (event === QueueEvent.askUser) {
        // ask_user 交互式选项事件：按 event_id 去重写入 agent_thoughts
        const exists = agent_thoughts.findIndex((item) => item?.id === event_id)
        const payload = {
          id: event_id || `temp_thought_${Date.now()}_${Math.random().toString(36).substring(2)}`,
          position,
          event: QueueEvent.askUser,
          thought: '',
          observation: '',
          tool: '',
          tool_input: {},
          latency: 0,
          created_at: 0,
          question: data?.question ?? '',
          options: data?.options ?? [],
          allow_custom: data?.allow_custom ?? true,
          choice: data?.choice ?? '',
          task_id: data?.task_id,
          sub_task_options: data?.sub_task_options ?? [],
        } as AgentThought
        if (exists === -1) {
          position += 1
          agent_thoughts.push(payload)
        } else {
          // 同 event_id 重发（确认后 republish 回显）：保留已有 sub_task_options 与 choice，
          // 防止 plan 模式被替换成 option 模式（勾选项与回显错乱），也防止无 choice 的
          // republish 覆盖本地乐观回写（markAskUserChoice）的结果
          const existingThought = agent_thoughts[exists] as AgentThought | undefined
          agent_thoughts[exists] = {
            ...payload,
            choice: data?.choice ?? existingThought?.choice ?? '',
            sub_task_options:
              data?.sub_task_options ?? existingThought?.sub_task_options ?? [],
          } as AgentThought
        }
      } else if (
        event === QueueEvent.error ||
        event === QueueEvent.stop ||
        event === QueueEvent.timeout
      ) {
        // error / stop / timeout 都算"这一轮没有正常产出"：后续推荐问题与自动播报一律终止。
        // 原来只认 error——用户点停止或监听超时后仍然会去取推荐问题、仍然会开播。
        chatFailed = true
        if (event === QueueEvent.error) {
          // 仅异常需要展示错误文案；停止/超时由消息列表按状态给出「继续执行」入口
          currentMessage.error = data?.observation || '推理过程发生异常，请稍后重试'
        }
      } else if (event === QueueEvent.agentMessage) {
        const idx = agent_thoughts.findIndex((item) => item?.id === event_id)
        if (idx === -1) {
          position += 1
          agent_thoughts.push({
            id: event_id || `temp_thought_${Date.now()}_${Math.random().toString(36).substring(2)}`,
            position,
            event: data?.event,
            thought: data?.thought,
            observation: data?.observation,
            llm_output: data?.llm_output,
            tool_calls: data?.tool_calls,
            model_name: data?.model_name,
            message: data?.message,
            tool: data?.tool,
            tool_input: data?.tool_input,
            trace: data?.trace,
            latency: data?.latency,
            total_token_count: data?.total_token_count,
            total_price: data?.total_price,
            created_at: 0,
            sub_task_id: data?.sub_task_id,
            sub_task_title: data?.sub_task_title,
          } as AgentThought)
        } else {
          const currentThought = agent_thoughts[idx]
          if (currentThought) {
            agent_thoughts[idx] = {
              ...currentThought,
              thought: (currentThought.thought || '') + (data?.thought || ''),
              latency: data?.latency || currentThought.latency,
              total_token_count: data?.total_token_count ?? currentThought.total_token_count,
              total_price: data?.total_price ?? currentThought.total_price,
              llm_output: data?.llm_output ?? currentThought.llm_output,
              model_name: data?.model_name ?? currentThought.model_name,
              message: data?.message ?? currentThought.message,
            }
          }
        }
        currentMessage.answer += data?.thought || ''
        currentMessage.latency = data?.latency || currentMessage.latency
        currentMessage.total_token_count =
          data?.total_token_count || currentMessage.total_token_count
      } else {
        // 处理其他类型事件，先查找是否已经存在相同 event_id
        const idx = agent_thoughts.findIndex((item) => item?.id === event_id)
        if (idx === -1) {
          position += 1
          agent_thoughts.push({
            id: event_id || `temp_thought_${Date.now()}_${Math.random().toString(36).substring(2)}`,
            position,
            event: data?.event,
            thought: data?.thought,
            observation: data?.observation,
            llm_output: data?.llm_output,
            tool_calls: data?.tool_calls,
            model_name: data?.model_name,
            message: data?.message,
            tool: data?.tool,
            tool_input: data?.tool_input,
            trace: data?.trace,
            latency: data?.latency,
            total_token_count: data?.total_token_count,
            total_price: data?.total_price,
            created_at: 0,
            sub_task_id: data?.sub_task_id,
            sub_task_title: data?.sub_task_title,
          } as AgentThought)
        } else {
          // 存在相同 id 时，平滑追加拼接（例如追加工具的流式入参 tool_input 或 observation）
          const currentThought = agent_thoughts[idx]
          if (currentThought) {
            agent_thoughts[idx] = {
              ...currentThought,
              event: data?.event || currentThought.event,
              thought: data?.llm_output
                ? (data?.thought || currentThought.thought)
                : data?.thought
                  ? (currentThought.thought || '') + data.thought
                  : currentThought.thought,
              observation: data?.observation
                ? (currentThought.observation || '') + data.observation
                : currentThought.observation,
              tool: data?.tool || currentThought.tool,
              tool_input: data?.tool_input
                ? ((String(currentThought.tool_input || '') +
                    String(data.tool_input)) as unknown as Record<string, unknown>)
                : currentThought.tool_input,
              latency: data?.latency || currentThought.latency,
              total_token_count: data?.total_token_count ?? currentThought.total_token_count,
              total_price: data?.total_price ?? currentThought.total_price,
              sub_task_id: data?.sub_task_id ?? currentThought.sub_task_id,
              sub_task_title: data?.sub_task_title ?? currentThought.sub_task_title,
              trace: data?.trace ?? currentThought.trace,
              llm_output: data?.llm_output ?? currentThought.llm_output,
              tool_calls: data?.tool_calls ?? currentThought.tool_calls,
              model_name: data?.model_name ?? currentThought.model_name,
              message: data?.message ?? currentThought.message,
            }
          }
        }
      }
      currentMessage.agent_thoughts = agent_thoughts
      scroller.value?.scrollToBottom()
    }
}

/** 流结束收尾：新会话入列、解除在挂登记、按配置取推荐问题与自动播报 */
const finishStream = async (selectedConversationTmp: string) => {
  const firstMessage = activeStreamMessage.value
  if (firstMessage) {
    if (selectedConversationTmp === 'new_conversation') {
      // 将newConversation填充到会话列表中
      unpinned_conversations.value.unshift({
        id: firstMessage.conversation_id,
        name: 'New Conversation',
        summary: '',
        created_at: firstMessage.created_at,
      })
      // 清空newConversation并修改选中
      newConversation.value = null
      if (selectedConversation.value === 'new_conversation') {
        selectedConversation.value = firstMessage.conversation_id
      }
    }
    // 清空newConversation并修改选中
    newConversation.value = null
    if (selectedConversation.value === 'new_conversation') {
      selectedConversation.value = firstMessage.conversation_id
    }
  }

  // 本次流结束（正常完成 / 客户端停止 / 后端终止）：解除进行中登记。
  // 若用户已切到别的会话，本条消息对象仍保留在旧会话加载结果与本地缓存中；
  // 重新进入该会话由 loadConversationWithScroll 从服务端拉取完整结果。
  activeStreamMessage.value = null
  activeStreamConversationId.value = ''
  activeStreamKey.value = ''
  run_id.value = ''
  last_event_id.value = 0
  // 后续动作（推荐问题 / 自动播报）的统一闸门：见 utils/chat-followups
  const canFollowUp = followupsAllowed({
    failed: chatFailed,
    answer: firstMessage?.answer,
    messageId: message_id.value,
  })

  if (canFollowUp && web_app.value?.app_config?.suggested_after_answer.enable) {
    await handleGenerateSuggestedQuestions(message_id.value)
    setTimeout(() => scroller.value?.scrollToBottom(), 100)
  }

  // 判断是否自动播放
  const app_config = web_app.value?.app_config as WebAppAppConfig | undefined
  if (
    canFollowUp &&
    app_config?.text_to_speech?.enable &&
    app_config?.text_to_speech?.auto_play
  ) {
    await handleStartAudio(message_id.value)
  }
}

/**
 * 断流重连：刷新或重新进入页面后，把仍在服务端生成的回答接回来。
 *
 * 依据是消息列表接口的 run_status=running + run_id —— 后端 run 的生命周期独立于这条
 * HTTP 连接（客户端断开只结束 SSE，不结束 run），所以这里不新建 run，只重挂事件流。
 * 重连前清空该条消息的正文与推理过程：resume 端点从缓冲第 1 帧起重放整段事件，
 * 逐帧累加会和服务端在断开时已落库的半截答案重复一遍。
 */
const attachResumeStream = (message: MessageItem, conversationId: string, targetRunId: string) => {
  message.answer = ''
  message.agent_thoughts = []
  message.error = ''
  position = 0
  chatFailed = false
  activeStreamMessage.value = message
  activeStreamConversationId.value = conversationId
  activeStreamKey.value = conversationId
  message_id.value = message.id
  // 顶层 task_id 与 run_id 同源（后端 chat_runner 固定 task_id=run_id），停止接口按它取任务
  task_id.value = targetRunId
  run_id.value = targetRunId
  last_event_id.value = 0
  // 不 await：重连流与首答一样是长连接，期间页面可以在别的会话继续操作
  void handleResumeWebAppChat(String(route.params?.token), targetRunId, 0, applyStreamFrame).finally(
    async () => {
      // 续传一个字都没拿到：run 是在这次重连之前就被服务端跑完的，事件日志已随落库清掉，
      // 后端只能补一帧 agent_end 收流。此时正文在库里，回源取一次，别留一个空气泡。
      const refillFromServer = !message.answer.trim() && !message.error
      activeStreamMessage.value = null
      activeStreamConversationId.value = ''
      activeStreamKey.value = ''
      run_id.value = ''
      last_event_id.value = 0
      if (refillFromServer && selectedConversation.value === conversationId) {
        await loadConversationMessagesWithPage(conversationId, true)
      }
    },
  )
}

// 定义停止调试会话函数
const handleStop = async () => {
  // 如果没有任务id或者未在加载中，则直接停止
  if (task_id.value === '' || !webAppChatLoading.value) return
  // 用户主动停止：先本地置位失败标记。abort 之后我们再也收不到后端的 stop 事件，
  // 不在此置位的话，停止后仍会去取推荐问题、仍会自动播那段没说完的回答。
  chatFailed = true
  // 1、先客户端中断 SSE 流：页面立即停止接收/渲染新输出（不依赖后端停止传播）
  abortWebAppChat()
  // 2、再调用后端 stop 接口停止 Agent 任务（防止继续消耗推理；失败不影响界面已停止）
  try {
    await handleStopWebAppChat(String(route.params?.token), task_id.value)
  } catch {
    // 忽略：客户端已停止，后端停止失败不阻塞
  }
  run_id.value = ''
  last_event_id.value = 0
}

// ===== 切会话/新建会话不再中断正在生成的回答 =====
// 后端 run 的生命周期独立于这条 SSE 连接（chat_runner 的 GeneratorExit 分支明确不终结 run），
// 所以离开会话只是不再渲染它：同一页面会话内切回由 activeStreamMessage 合并回视图，
// 刷新后由消息列表的 run_status=running + run_id 走 attachResumeStream 重连。
// 归属判定要同时比对"开流时选中的会话"和"回包后确定的会话"：new_conversation 首轮
// 开流时还没有真实 id，只比一个会让停止按钮在首答期间消失。
const isCurrentStreamRunning = computed(
  () =>
    task_id.value !== '' &&
    webAppChatLoading.value &&
    (activeStreamKey.value === selectedConversation.value ||
      activeStreamConversationId.value === selectedConversation.value),
)

// 定义切换会话处理器（不弹确认框、不 abort：任务照旧在后台跑）
const changeConversation = (conversation_id: string) => {
  selectedConversation.value = conversation_id
}

// 定义问题提交函数
const handleSubmitQuestion = async (question: string) => {
  // 将问题同步到query中
  query.value = question
  // 触发handleSubmit函数
  await handleSubmit()
}

// 处理消息反馈（点赞/点踩），同步到后端
const handleMessageFeedback = async (payload: { message_id: string; feedback: string | null }) => {
  const { message_id: msgId, feedback } = payload
  if (!msgId) return
  const item = messages.value.find((m) => m.id === msgId)
  const conversationId = item?.conversation_id
  if (!conversationId) return
  const previous = item.feedback
  item.feedback = feedback || ''
  try {
    await updateMessageFeedback(conversationId, msgId, feedback || '')
    Message.success(feedback ? '感谢你的反馈' : '已取消反馈')
  } catch {
    item.feedback = previous
    Message.error('反馈提交失败')
  }
}

// ===== ask_user 交互式选项：取该消息最后一个 ask_user 思考事件 + 提交选择 =====
// 取该消息 agent_thoughts 中最后一个 event === ask_user 的 thought（不存在返回 null）
const getAskUserThought = (item: MessageItem): AgentThought | null => {
  const thoughts = item.agent_thoughts || []
  for (let i = thoughts.length - 1; i >= 0; i--) {
    const thought = thoughts[i] as AgentThought | undefined
    if (thought?.event === QueueEvent.askUser) return thought
  }
  return null
}

// 按消息 id 缓存，避免模板 v-for 内重复遍历
const askUserThoughtMap = computed(() => {
  const map = new Map<string, AgentThought | null>()
  for (const msg of messages.value) {
    map.set(msg.id, getAskUserThought(msg))
  }
  return map
})

const askUserThought = (item: MessageItem): AgentThought | null =>
  askUserThoughtMap.value.get(item.id) ?? null

// 消息所属任务是否已终态（停止/取消/超时/出错）：终态任务的计划确认框不再可交互，
// 避免"任务已停但确认框看似可选"的困惑态
const isTerminalTask = (item: MessageItem): boolean => {
  const s = item.status ?? ''
  const rs = item.run_status ?? ''
  return (
    s === 'stop' || s === 'timeout' || s === 'error' ||
    ['cancelled', 'timed_out', 'failed'].includes(rs)
  )
}

// ask_user 组件实例字典（按消息 id）：choice 接口失败时复位组件允许重试
const askUserOptionsRefs = new Map<string, { reset: () => void }>()
const setAskUserOptionsRef = (msgId: string, el: unknown) => {
  const inst = el as { reset: () => void } | null
  if (inst) askUserOptionsRefs.set(msgId, inst)
  else askUserOptionsRefs.delete(msgId)
}

// 提交成功后本地回写该 ask_user thought 的 choice，组件据此切换为回显模式（与后端 SSE 后续事件双保险）
const markAskUserChoice = (taskId: string, choice: string) => {
  for (const msg of messages.value) {
    for (const thought of msg.agent_thoughts || []) {
      const t = thought as AgentThought
      if (t.event === QueueEvent.askUser && t.task_id === taskId) {
        t.choice = choice
      }
    }
  }
}

// 回退乐观回显：choice 提交接口失败时清空本地回写的 choice，配合 reset 恢复可交互态
const clearAskUserChoice = (taskId: string) => {
  for (const msg of messages.value) {
    for (const thought of msg.agent_thoughts || []) {
      const t = thought as AgentThought
      if (t.event === QueueEvent.askUser && t.task_id === taskId) {
        t.choice = ''
      }
    }
  }
}

// 提交/跳过 ask_user 选择（task_id 拼进 URL 路径；option 模式 body 带 { choice, custom, skip, event_id }，
// plan 模式 body 带 { action, keep_orders, custom, skip, event_id }）
const onChoiceSubmitted = async (payload: {
  taskId: string
  choice?: string
  skip: boolean
  eventId: string
  action?: 'confirm' | 'replan'
  keepOrders?: number[]
  custom?: string
}) => {
  const token = String(route.params?.token)
  if (!payload.taskId || !token) {
    // 历史消息里未回答的 ask_user（如 agent 等待超时后刷新页面）可能缺 task_id：
    // 静默 return 会让卡片卡在"已提交，继续处理中…"灰色态，提示并复位组件允许重试
    Message.error('该问题已失效，无法提交选择，请刷新页面重试')
    const staleTarget = messages.value.find((m) =>
      (m.agent_thoughts || []).some((t) => (t as AgentThought).id === payload.eventId),
    )
    if (staleTarget) askUserOptionsRefs.get(staleTarget.id)?.reset()
    return
  }
  // 乐观回显：先把 choice 写回本地 thought，卡片立即显示"已选：X"（不等接口返回，
  // 页面第一时间有反馈；接口失败再回退复位）
  const displayChoice = payload.action
    ? payload.action === 'replan'
      ? '重新规划'
      : '确认执行'
    : (payload.choice ?? '')
  markAskUserChoice(payload.taskId, displayChoice)
  try {
    const body = payload.action
      ? {
          action: payload.action,
          keep_orders: payload.keepOrders ?? [],
          custom: payload.custom ?? '',
          skip: payload.skip,
          event_id: payload.eventId,
        }
      : {
          choice: payload.choice ?? '',
          custom: payload.custom ?? '',
          skip: payload.skip,
          event_id: payload.eventId,
        }
    // submitWebAppChoice 服务层 body 类型未含 action/keep_orders/custom（后端已支持，此处透传）
    await submitWebAppChoice(
      token,
      payload.taskId,
      body as unknown as Parameters<typeof submitWebAppChoice>[2],
    )
    Message.success(payload.skip ? '已跳过该问题' : '选择已提交')
  } catch {
    Message.error('选择提交失败，请重试')
    // 回退乐观回显：清空本地 choice + 复位对应 AskUserOptions 组件，恢复按钮可点击以便重试
    clearAskUserChoice(payload.taskId)
    const target = messages.value.find((m) =>
      (m.agent_thoughts || []).some((t) => (t as AgentThought).task_id === payload.taskId),
    )
    if (target) askUserOptionsRefs.get(target.id)?.reset()
  }
}

const handleStartAudio = async (msgId: string) => {
  playingMessageId.value = msgId
  await _startAudioStream(msgId)
}

const handleStopAudio = () => {
  _stopAudioStream()
  playingMessageId.value = ''
}

// 监听isPlaying，音频真正播完后才清空
watch(isPlaying, (val) => {
  if (!val) {
    playingMessageId.value = ''
  }
})

// 监听选择会话变化
watch(
  () => selectedConversation.value,
  async (newValue) => {
    viewMode.value = 'chat'
    // 切会话后旧的子任务聚焦不再适用，复位为"查看全部"
    activeSubTaskId.value = ''
    if (newValue && newValue !== 'new_conversation') {
      await router.replace({
        query: { ...route.query, conversation_id: newValue },
      })
    } else if (newValue === 'new_conversation') {
      const newQuery = { ...route.query }
      delete newQuery.conversation_id
      await router.replace({ query: newQuery })
    }

    if (newValue === 'new_conversation') {
      // 点击了新会话，将消息清空
      messages.value = []
      messagesReady.value = true
    } else if (newValue !== '') {
      // 选择了已有会话：先隐藏消息区，加载后滚动到底部再显示，避免先顶部后底部闪烁
      await loadConversationWithScroll(newValue)
    }
  },
  { immediate: false },
)

let scrollConfirmTimer: number | null = null
let scrollPendingReflown = false
let scrollStartTime = 0
const SCROLL_CONFIRM_INTERVAL = 150
const SCROLL_CONFIRM_TIMEOUT = 3000

const scrollToBottomNow = () => {
  const scrollerEl = scroller.value
  if (!scrollerEl) return
  const el = (scrollerEl.$el || scrollerEl) as HTMLElement
  if (el) el.scrollTop = el.scrollHeight
}

const showMessages = () => {
  messagesReady.value = true
  requestAnimationFrame(() => {
    scrollToBottomNow()
  })
}

const scrollToBottomAndConfirm = () => {
  scrollToBottomNow()

  if (scrollConfirmTimer !== null) {
    clearTimeout(scrollConfirmTimer)
    scrollConfirmTimer = null
  }
  scrollConfirmTimer = window.setTimeout(() => {
    scrollConfirmTimer = null
    const scrollerEl = scroller.value
    const el = (scrollerEl?.$el || scrollerEl) as HTMLElement | undefined
    if (!el) {
      scrollToBottomAndConfirm()
      return
    }

    const atBottom =
      el.scrollHeight <= el.clientHeight || el.scrollTop + el.clientHeight >= el.scrollHeight - 10
    const waitedTooLong = Date.now() - scrollStartTime > SCROLL_CONFIRM_TIMEOUT

    if ((atBottom && !scrollPendingReflown) || waitedTooLong) {
      scrollPendingReflown = false
      showMessages()
    } else {
      scrollPendingReflown = false
      scrollToBottomAndConfirm()
    }
  }, SCROLL_CONFIRM_INTERVAL)
}

const loadConversationWithScroll = async (conversationId: string) => {
  messagesReady.value = false
  scrollPendingReflown = false
  scrollStartTime = Date.now()
  await loadConversationMessagesWithPage(conversationId, true)
  await nextTick()
  // 切回会话时合并"后台继续"的进行中消息：同一 run 的 SSE 仍在后台推送，服务端尚未落库
  // 完整结果（落库在流结束 finally），若只显示服务端快照会丢失进行中内容。
  // 决策规则见 utils/chat-live-merge（id 相同但服务端那行还是空占位时，必须换成在流式的对象）。
  const live = activeStreamMessage.value
  if (live && activeStreamConversationId.value === conversationId) {
    const plan = planLiveMerge(messages.value, live)
    if (plan.action === 'unshift') {
      messages.value.unshift(live as MessageItem)
    } else if (plan.action === 'replace') {
      messages.value.splice(plan.index, 1, live)
    }
  }
  // 服务端仍在生成、且本页当前没有在挂的流：按 run_id 重连事件流把答案接回来。
  // 这是刷新后的唯一入口——刷新会丢掉 activeStreamMessage，但后端 run 与事件队列照旧在跑。
  if (!activeStreamMessage.value) {
    const running = messages.value.find((m) => m.run_status === 'running' && m.run_id)
    if (running) attachResumeStream(running, conversationId, String(running.run_id))
  }
  scrollToBottomAndConfirm()
}

const handleScrollerReflown = () => {
  if (navLoadingMore) {
    restoreMessageScroll()
    return
  }
  if (!messagesReady.value) {
    scrollPendingReflown = true
    scrollToBottomAndConfirm()
  }
  userMessageNavRef.value?.refresh()
}

onMounted(async () => {
  // App 选择器数据（已发布 + 有 token）
  await loadApps()

  // 无 token 入口（/web-apps 或 /web-apps/）：优先进入上次选择的 app，
  // 没有记录或该 app 已不在可用列表时，回退到第一个已发布的 app。
  // 不跳转、不报错——原地加载该 app（同时更新 URL 便于分享/刷新保持）。
  let token = String(route.params?.token ?? '')
  if (!token) {
    const remembered = lastSelectedAppToken()
    const fallback = apps.value[0]
    const target =
      (remembered && apps.value.some((a) => a.token === remembered) && remembered) ||
      (fallback?.token || '')
    if (target) {
      token = target
      router.replace({ path: `/web-apps/${token}`, query: route.query }).catch(() => {})
    }
  }

  if (!token) {
    Message.warning('当前没有已发布的 WebApp，请先在应用列表中发布应用')
    return
  }

  // 记录当前进入的 app（带 token 直达时也记住，下次 /web-apps 直接进入）
  rememberLastApp(token)

  await Promise.all([loadWebApp(token), loadWebAppConversations(token)])

  const queryConversationId = route.query.conversation_id as string
  let found = false
  if (queryConversationId) {
    if (pinned_conversations.value.some((item) => item.id === queryConversationId)) found = true
    else if (unpinned_conversations.value.some((item) => item.id === queryConversationId))
      found = true
  }

  if (found) {
    // 设置选中会话，由 watch 统一负责加载+滚动+显示，避免双触发竞争
    selectedConversation.value = queryConversationId
  } else {
    addConversation()
  }
})
</script>

<template>
  <div class="flex h-screen w-full overflow-hidden">
    <!-- 左侧会话记录（视口 <992px 时折叠为图标栏） -->
    <div
      class="w-[240px] max-lg:w-16 flex-shrink-0 border-r border-gray-200 p-4 max-lg:p-2 flex flex-col h-full overflow-hidden"
    >
      <!-- 顶部应用信息 -->
      <div
        class="flex items-center gap-3 mb-8 flex-shrink-0 max-lg:justify-center max-lg:mb-4 max-lg:gap-0"
      >
        <a-tooltip :content="web_app?.name || ''" position="right" :disabled="!isNarrow">
          <a-avatar :size="32" shape="square" :image-url="web_app?.icon" class="flex-shrink-0">
          </a-avatar>
        </a-tooltip>
        <div class="flex-1 text-base font-semibold line-clamp-1 break-all text-gray-700 max-lg:hidden">
          <a-skeleton :loading="getWebAppLoading" :animation="true">
            <a-skeleton-line :rows="1" :line-height="32" :line-spacing="4" />
          </a-skeleton>
          {{ web_app?.name }}
        </div>
      </div>
      <!-- 新增会话 -->
      <a-tooltip content="新增会话" position="right" :disabled="!isNarrow">
        <a-button
          type="primary"
          class="rounded-lg mb-6 flex-shrink-0 w-full max-lg:w-10 max-lg:!px-0 max-lg:mx-auto max-lg:mb-4"
          @click="addConversation"
        >
          <template #icon>
            <icon-edit />
          </template>
          <span class="max-lg:hidden">新增会话</span>
        </a-button>
      </a-tooltip>
      <!-- 会话列表 -->
      <div class="flex-1 overflow-y-auto scrollbar-w-none">
        <!-- 置顶会话 -->
        <div class="mb-4">
          <div class="text-gray-700 font-semibold mb-2 max-lg:hidden">置顶会话</div>
          <a-skeleton :loading="getWebAppConversationsLoading" :animation="true">
            <a-skeleton-line :rows="2" :line-height="32" :line-spacing="4" />
          </a-skeleton>
          <div class="flex flex-col gap-1">
            <a-tooltip
              v-for="(conversation, idx) in pinned_conversations"
              :key="conversation.id"
              :content="conversation.name"
              position="right"
              :disabled="!isNarrow"
            >
              <div
                @click="changeConversation(conversation.id)"
                :class="[
                  'group flex items-center gap-1 h-8 leading-8 pl-3 pr-1 rounded-lg cursor-pointer max-lg:justify-center max-lg:px-0',
                  selectedConversation === conversation.id
                    ? 'bg-[#f3f4f6] text-blue-700'
                    : 'text-gray-700 hover:bg-blue-50 hover:text-blue-700',
                ]"
              >
                <icon-message class="flex-shrink-0" />
                <div class="flex-1 line-clamp-1 break-all max-lg:hidden">{{ conversation.name }}</div>
                <a-dropdown position="br" class="max-lg:hidden">
                  <a-button aria-label="更多操作"
                    size="mini"
                    type="text"
                    class="!text-inherit !bg-transparent invisible group-hover:visible max-lg:!hidden"
                  >
                    <template #icon>
                      <icon-more />
                    </template>
                  </a-button>
                  <template #content>
                    <a-doption @click="changeIsPinned(idx, true)">取消置顶</a-doption>
                    <a-doption @click="updateName(idx, true)">重命名</a-doption>
                    <a-doption class="text-red-700" @click="deleteConversation(idx, true)">
                      删除
                    </a-doption>
                  </template>
                </a-dropdown>
              </div>
            </a-tooltip>
          </div>
          <a-empty
            v-if="!getWebAppConversationsLoading && pinned_conversations.length == 0"
            class="max-lg:hidden"
          >
            <template #image>
              <icon-empty :size="36" />
            </template>
            暂无置顶会话
          </a-empty>
        </div>
        <!-- 对话列表 -->
        <div class="mb-4">
          <div class="text-gray-700 font-semibold mb-2 max-lg:hidden">对话列表</div>
          <a-skeleton :loading="getWebAppConversationsLoading" :animation="true">
            <a-skeleton-line :rows="2" :line-height="32" :line-spacing="4" />
          </a-skeleton>
          <div class="flex flex-col gap-1">
            <a-tooltip
              v-if="newConversation"
              :content="newConversation.name"
              position="right"
              :disabled="!isNarrow"
            >
              <div
                :class="[
                  'group flex items-center gap-1 h-8 leading-8 pl-3 pr-1 rounded-lg cursor-pointer max-lg:justify-center max-lg:px-0',
                  selectedConversation === 'new_conversation'
                    ? 'bg-[#f3f4f6] text-blue-700'
                    : 'text-gray-700 hover:bg-blue-50 hover:text-blue-700',
                ]"
                @click="changeConversation('new_conversation')"
              >
                <icon-message class="flex-shrink-0" />
                <div class="flex-1 line-clamp-1 break-all max-lg:hidden">{{ newConversation.name }}</div>
              </div>
            </a-tooltip>
            <a-tooltip
              v-for="(conversation, idx) in unpinned_conversations"
              :key="conversation.id"
              :content="conversation.name"
              position="right"
              :disabled="!isNarrow"
            >
              <div
                @click="changeConversation(conversation.id)"
                :class="[
                  'group flex items-center gap-1 h-8 leading-8 pl-3 pr-1 rounded-lg cursor-pointer max-lg:justify-center max-lg:px-0',
                  selectedConversation === conversation.id
                    ? 'bg-[#f3f4f6] text-blue-700'
                    : 'text-gray-700 hover:bg-blue-50 hover:text-blue-700',
                ]"
              >
                <icon-message class="flex-shrink-0" />
                <div class="flex-1 line-clamp-1 break-all max-lg:hidden">{{ conversation.name }}</div>
                <a-dropdown position="br" class="max-lg:hidden">
                  <a-button aria-label="更多操作"
                    size="mini"
                    type="text"
                    class="!text-inherit !bg-transparent invisible group-hover:visible max-lg:!hidden"
                  >
                    <template #icon>
                      <icon-more />
                    </template>
                  </a-button>
                  <template #content>
                    <a-doption @click="changeIsPinned(idx, false)">消息置顶</a-doption>
                    <a-doption @click="updateName(idx, false)">重命名</a-doption>
                    <a-doption class="text-red-700" @click="deleteConversation(idx, false)">
                      删除
                    </a-doption>
                  </template>
                </a-dropdown>
              </div>
            </a-tooltip>
          </div>
          <a-empty
            v-if="!getWebAppConversationsLoading && unpinned_conversations.length == 0"
            class="max-lg:hidden"
          >
            <template #image>
              <icon-empty :size="36" />
            </template>
            暂无会话列表
          </a-empty>
        </div>
      </div>
      <!-- 左下角设置入口（短期记忆等会话设置） -->
      <div class="flex-shrink-0 mt-2 pt-2 border-t border-gray-200 max-lg:flex max-lg:justify-center">
        <button
          type="button"
          class="flex items-center gap-2 w-full h-8 px-3 rounded-lg text-gray-700 hover:bg-blue-50 hover:text-blue-700 cursor-pointer max-lg:px-0 max-lg:justify-center"
          @click="openSettings"
        >
          <icon-settings class="flex-shrink-0" />
          <span class="text-sm max-lg:hidden">设置</span>
        </button>
      </div>
    </div>
    <!-- 右侧对话窗口 -->
    <div class="flex-1 h-full bg-white flex flex-col min-w-0">
      <!-- 顶部会话名称 + 子任务摘要行/页内 tab（位于会话名称右侧；字体保持） -->
      <div
        class="h-16 leading-[64px] text-base font-semibold px-6 border-b flex-shrink-0 flex justify-between items-center"
      >
        <span class="truncate">{{ conversation?.name }}</span>
        <div class="flex items-center gap-2 flex-shrink-0 min-w-0">
          <!-- 子任务下拉：当前上下文存在编排子任务时显示；选中聚焦任务详情中该子任务，选中"查看全部"回全量。
               去除"子任务"文字标签，外观与右侧 tab 控件同款（灰底圆角容器 + 紧凑白底块） -->
          <div v-if="subTaskOptions.length > 0" class="flex-shrink-0">
            <a-select
              :model-value="activeSubTaskId || undefined"
              :options="[{ label: '查看全部子任务', value: '__all__' }, ...subTaskOptions]"
              placeholder="选择子任务"
              size="small"
              class="sub-task-select rounded-lg"
              :style="{ width: '150px' }"
              @change="onSubTaskSelect"
            />
          </div>
          <div class="flex items-center gap-1 rounded-lg bg-gray-100 p-0.5 flex-shrink-0">
            <button
              type="button"
              class="h-7 px-3 rounded-md text-xs transition-colors"
              :class="
                viewMode === 'chat'
                  ? 'bg-white text-blue-600 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              "
              @click="viewMode = 'chat'"
            >
              对话
            </button>
            <button
              type="button"
              class="h-7 px-3 rounded-md text-xs transition-colors"
              :class="
                viewMode === 'subagents'
                  ? 'bg-white text-blue-600 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              "
              @click="viewMode = 'subagents'; activeSubTaskId = ''"
            >
              任务详情
            </button>
            <button
              type="button"
              class="h-7 px-3 rounded-md text-xs transition-colors"
              :class="
                viewMode === 'memory'
                  ? 'bg-white text-blue-600 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              "
              @click="viewMode = 'memory'"
            >
              短期记忆
            </button>
          </div>
        </div>
      </div>

      <div
        class="w-full relative flex flex-col transition-all duration-300"
        :class="messages.length === 0 ? 'items-center justify-center overflow-y-auto' : ''"
        :style="contentHeightStyle"
      >
        <!-- 任务详情视图（页内 tab 切换，无新路由；展示当前上下文全部消息的完整轨迹，
             子任务下拉聚焦时仅展示该子任务轨迹——同款渲染组件与"任务详情"完全一致） -->
        <sub-agent-detail
          v-if="viewMode === 'subagents'"
          :messages="messages"
          :focus-message-id="focusState.messageId"
          :focus-thought-id="focusState.thoughtId"
          :focus-nonce="focusState.nonce"
          :filter-sub-task-id="activeSubTaskId || null"
          class="flex-1 min-h-0 w-full"
        />
        <!-- 短期记忆视图（只读展示记忆窗口内未归档消息） -->
        <short-term-memory-view
          v-else-if="viewMode === 'memory'"
          :messages="messages"
          :dialog-round="effectiveDialogRound"
          class="flex-1 min-h-0 w-full"
        />
        <template v-else>
          <!-- 存在历史消息时的滚动对话列表 -->
          <template v-if="messages.length > 0">
            <div class="flex-1 min-h-0 w-full relative">
              <div class="h-full w-full relative" :class="messagesReady ? '' : 'invisible'">
                <dynamic-scroller
                  ref="scroller"
                  :items="messages.slice().reverse()"
                  :min-item-size="1"
                  @scroll="handleScroll"
                  @reflown="handleScrollerReflown"
                  class="h-full w-full overflow-y-auto"
                >
                  <template v-slot="{ item, active }">
                    <dynamic-scroller-item :item="item" :active="active" :data-index="item.id">
                      <div class="max-w-[976px] mx-auto px-6">
                        <div class="flex flex-col gap-2 py-4">
                          <template v-if="item.is_archived">
                            <!-- 归档对话卡片（与"显示运行流程"同款：同宽同左缩进——头像30px+gap8px=38px，右缩40px） -->
                            <div
                              class="flex flex-col rounded-2xl border w-[calc(100%-78px)] ml-[38px] overflow-hidden"
                            >
                              <div
                                class="flex items-center justify-between h-10 rounded-2xl bg-gray-100 px-4 text-gray-700 cursor-pointer w-auto"
                                @click="openArchivedMessage(item)"
                              >
                                <div class="flex items-center gap-2">
                                  <icon-archive />
                                  {{ archivedExpandedIds.has(item.id) ? '隐藏' : '显示' }}归档对话
                                </div>
                                <div>
                                  <icon-up v-if="archivedExpandedIds.has(item.id)" />
                                  <icon-down v-else />
                                </div>
                              </div>
                              <div
                                v-show="archivedExpandedIds.has(item.id)"
                                class="flex flex-col bg-white"
                              >
                                <div class="text-xs text-gray-400 px-4 pt-3">
                                  该轮对话已归档，不再参与模型上下文
                                </div>
                                <div class="px-4 py-3">
                                  <div class="text-sm text-gray-800 break-all">
                                    {{ item.query }}
                                  </div>
                                  <div class="text-sm text-gray-800 mt-2 break-all">
                                    {{ item.answer }}
                                  </div>
                                </div>
                              </div>
                            </div>
                          </template>
                          <template v-else>
                            <human-message
                              :query="item.query"
                              :image_urls="item.image_urls"
                              :file_urls="item.file_urls"
                              :account="accountStore.account"
                              :editing="editingMessageId === item.id"
                              @edit-start="editingMessageId = item.id"
                              @edit-cancel="editingMessageId = ''"
                              @submit-edit="onEditSubmit"
                            />
                            <ai-message
                              :key="item.id"
                              :message_id="item.id"
                              :enable_text_to_speech="
                                (web_app?.app_config as WebAppAppConfig | undefined)?.text_to_speech
                                  ?.enable
                              "
                              :agent_thoughts="item.agent_thoughts"
                              :answer="item.answer"
                              :status="item.status ?? ''"
                              :run_status="item.run_status ?? ''"
                              :can_resume="item.can_resume === true"
                              :error="item.error"
                              :feedback="item.feedback"
                              :app="{ name: web_app.name, icon: web_app.icon }"
                              :jumpable="true"
                              @step-click="(thought) => onThoughtStepClick(item.id, thought)"
                              :suggested_questions="
                                item.id === message_id ? suggested_questions : []
                              "
                              :loading="item.id === message_id && webAppChatLoading"
                              :latency="item.latency"
                              :total_token_count="item.total_token_count"
                              :is_playing="item.id === playingMessageId && isPlaying"
                              :audio_loading="item.id === playingMessageId && textToAudioLoading"
                              :start_audio_stream="handleStartAudio"
                              :stop_audio_stream="handleStopAudio"
                              @select-suggested-question="handleSubmitQuestion"
                              @feedback="handleMessageFeedback"
                              @regenerate="onRegenerate(item)"
                              @continue="resumeMessage(item)"
                            />
                            <!-- ask_user 交互式选项选择（弹框保持原位居中；状态文案与底部按钮在组件内靠右对齐） -->
                            <div v-if="askUserThought(item)" class="pl-[38px]">
                              <ask-user-options
                                :ref="(el) => setAskUserOptionsRef(item.id, el)"
                                :mode="askUserThought(item)?.sub_task_options?.length ? 'plan' : 'option'"
                                :sub-task-options="askUserThought(item)?.sub_task_options ?? []"
                                :requires-reason="true"
                                :question="askUserThought(item)?.question ?? ''"
                                :options="askUserThought(item)?.options ?? []"
                                :allow-custom="askUserThought(item)?.allow_custom ?? true"
                                :task-id="askUserThought(item)?.task_id ?? ''"
                                :event-id="askUserThought(item)?.id ?? ''"
                                :choice="askUserThought(item)?.choice ?? ''"
                                :readonly="isTerminalTask(item)"
                                @submitted="onChoiceSubmitted"
                              />
                            </div>
                          </template>
                        </div>
                      </div>
                    </dynamic-scroller-item>
                  </template>
                </dynamic-scroller>
                <div
                  v-if="isCurrentStreamRunning"
                  class="absolute bottom-4 left-1/2 -translate-x-1/2 z-20"
                >
                  <a-button
                    :loading="stopWebAppChatLoading"
                    class="rounded-lg px-2 shadow-lg"
                    @click="handleStop"
                  >
                    <template #icon>
                      <icon-poweroff />
                    </template>
                    停止响应
                  </a-button>
                </div>
              </div>
              <!-- 右侧用户消息导航条：每条用户消息一个圆点 -->
              <user-message-nav
                ref="userMessageNavRef"
                :items="navItems"
                :scroll-el="scroller?.$el ?? null"
              />
            </div>
          </template>

          <!-- 无历史消息时的上部分 (开场白、建议问题等) -->
          <template v-else>
            <div class="w-full max-w-[976px] px-6 flex flex-col gap-4 pb-4">
              <!-- 应用图标与名称 -->
              <div class="flex flex-col items-center gap-2">
                <a-avatar :size="48" shape="square" class="rounded-lg" :image-url="web_app?.icon" />
                <div class="text-lg text-gray-700">{{ web_app?.name }}</div>
              </div>

              <!-- 开场白 -->
              <div
                v-if="web_app?.app_config?.opening_statement"
                class="bg-gray-100 w-full px-4 py-3 rounded-lg text-gray-700"
              >
                {{ web_app?.app_config?.opening_statement }}
              </div>

              <!-- 建议问题 -->
              <div class="flex items-center flex-wrap gap-2 w-full justify-center">
                <div
                  v-for="(opening_questions, idx) in web_app?.app_config?.opening_questions.filter(
                    (item: string) => item.trim() !== '',
                  )"
                  :key="idx"
                  class="px-4 py-1.5 border rounded-lg text-gray-700 cursor-pointer hover:bg-gray-50"
                  @click="async () => await handleSubmitQuestion(opening_questions)"
                >
                  {{ opening_questions }}
                </div>
              </div>
            </div>
          </template>
        </template>

        <div
          :class="[
            'z-10 bg-white flex-shrink-0',
            messages.length > 0 ? 'w-full  border-gray-100' : 'w-full max-w-[976px]',
          ]"
        >
          <div
            :class="[
              'flex flex-col gap-4 px-6',
              messages.length > 0 ? 'w-full max-w-[976px] mx-auto pt-6' : 'w-full pb-8',
            ]"
          >
            <!-- 动态输入框组件 -->
            <chat-input-bar
              v-model="query"
              v-model:image-urls="image_urls"
              v-model:file-urls="file_urls"
              placeholder="请输入消息..."
              :sending="webAppChatLoading"
              :show-clear-button="false"
              :show-image-button="can_image_input"
              :show-audio-recorder="can_speech_to_text"
              :show-file-button="true"
              @submit="handleSubmit"
            />
          </div>
        </div>
      </div>
    </div>
    <!-- 修改会话名字模态窗 -->
    <update-name-modal
      v-model:visible="updateConversationNameModalVisible"
      v-model:conversation_id="updateConversationNameId"
      :success_callback="successUpdateNameCallback"
    />
    <!-- 设置弹框：短期记忆（上下文携带轮数，按会话保存） -->
    <a-modal
      :visible="settingsVisible"
      :width="'clamp(200px, 80vw, 800px)'"
      title="设置"
      :footer="false"
      @cancel="settingsVisible = false"
    >
      <div class="flex flex-col gap-5 py-1">
        <div class="flex flex-col gap-2">
          <div class="text-sm font-semibold text-gray-700">短期记忆</div>
          <div class="text-xs text-gray-500 leading-5">
            对话时携带最近 {{ settingsUseDefault ? appDefaultRound : settingsRound }} 轮上下文作为短期记忆
            （0 表示不携带历史；不设置时使用应用默认 {{ appDefaultRound }} 轮，按会话独立保存、下次对话生效）。
          </div>
          <div class="flex items-center gap-4 pt-2">
            <a-slider
              v-model="settingsRound"
              :min="0"
              :max="100"
              :step="1"
              :disabled="settingsUseDefault"
              class="flex-1 min-w-0"
            />
            <input
              type="number"
              :value="settingsRound"
              :disabled="settingsUseDefault"
              aria-label="短期记忆轮数"
              min="0"
              max="100"
              step="1"
              class="h-8 w-24 flex-shrink-0 rounded-md border border-gray-300 px-2 text-sm text-gray-700 outline-none focus:border-blue-500 disabled:cursor-not-allowed disabled:bg-gray-50 disabled:text-gray-400"
              @input="onSettingsRoundInput"
            />
          </div>
          <div class="flex items-center gap-2">
            <a-checkbox v-model="settingsUseDefault">跟随应用默认（{{ appDefaultRound }} 轮）</a-checkbox>
            <span v-if="conversationDialogRound === null && !settingsUseDefault" class="text-xs text-gray-400">
              当前未单独设置
            </span>
          </div>
        </div>
        <div class="flex justify-end gap-2">
          <a-button @click="settingsVisible = false">取消</a-button>
          <a-button type="primary" :loading="settingsSaving" @click="saveSettings">保存</a-button>
        </div>
      </div>
    </a-modal>

    <!-- 右侧悬浮 App 切换按钮（可拖拽，默认右边垂直居中；点击弹出选择） -->
    <button
      ref="fabRef"
      type="button"
      title="切换应用"
      class="app-fab"
      :style="{ left: fabPos.x + 'px', top: fabPos.y + 'px' }"
      @pointerdown="onFabPointerDown"
      @pointermove="onFabPointerMove"
      @pointerup="onFabPointerUp"
      @pointercancel="onFabPointerUp"
    >
      <!-- 内容层 pointer-events:none：指针事件始终落在 button 上，
           整个按钮区域（含边框/留白）都能拖动，而不只是图标本身 -->
      <span class="app-fab__inner">
        <a-avatar :size="30" shape="square" :image-url="web_app?.icon" class="flex-shrink-0">
          <template #trigger-icon>
            <icon-swap />
          </template>
        </a-avatar>
      </span>
    </button>

    <!-- App 选择弹框（跟随按钮，位于其左侧） -->
    <div
      ref="popoverRef"
      v-if="appPickerVisible"
      class="app-fab-popover"
      :style="{ left: fabPopoverPos.left + 'px', top: fabPopoverPos.top + 'px' }"
    >
      <div class="app-fab-popover__title">选择应用</div>
      <div class="flex flex-col gap-2 max-h-[50vh] overflow-y-auto">
        <div v-if="appsLoading" class="py-4 text-center text-sm text-gray-400">加载中…</div>
        <div v-else-if="apps.length === 0" class="py-4 text-center text-sm text-gray-400">
          暂无已发布的 WebApp
        </div>
        <button
          v-for="a in apps"
          :key="a.token"
          type="button"
          class="flex items-center gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors hover:bg-gray-50"
          :class="a.token === currentAppToken ? 'border-blue-500 bg-blue-50' : 'border-gray-200'"
          @click="switchApp(a.token)"
        >
          <a-avatar :size="28" shape="square" :image-url="a.icon" class="flex-shrink-0" />
          <span class="flex-1 min-w-0">
            <span class="block truncate text-sm font-medium text-gray-800">{{ a.name || a.token }}</span>
            <span class="block truncate text-xs text-gray-400">{{ a.token }}</span>
          </span>
          <icon-check v-if="a.token === currentAppToken" class="flex-shrink-0 text-blue-500" />
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 右侧悬浮 App 切换按钮：44x44 方形图标按钮，可拖拽，悬停弹出选择 */
.app-fab {
  position: fixed;
  z-index: 50;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  padding: 0;
  border-radius: 12px;
  border: 1px solid rgba(59, 130, 246, 0.4);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
  cursor: grab;
  user-select: none;
  touch-action: none;
  transition: box-shadow 0.15s ease, transform 0.15s ease;
}
.app-fab:hover {
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.18);
  transform: scale(1.04);
}
.app-fab:active {
  cursor: grabbing;
}

/* 内容层不接收指针事件：整按钮可拖动（指针事件统一落在 button 上） */
.app-fab__inner {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}

/* App 选择弹框：fixed 定位，跟随按钮左侧 */
.app-fab-popover {
  position: fixed;
  z-index: 51;
  width: 280px;
  max-width: calc(100vw - 80px);
  padding: 12px;
  border-radius: 12px;
  background: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.08);
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.16);
}
/* 子任务下拉：外观对齐右侧 tab 分段控件（灰底圆角胶囊，激活白底块）。
   Arco select 默认白底带边框、撑高，这里用 :deep 覆盖内部样式，
   使其呈现与"对话/任务详情/短期记忆"tab 同款的紧凑灰底胶囊。 */
.sub-task-select :deep(.arco-select-view) {
  height: 28px;
  line-height: 26px;
  padding: 0 10px;
  border-radius: 8px;
  background: #f3f4f6;
  border: none;
  font-size: 12px;
  color: #374151;
  box-shadow: none;
  transition: background-color 0.15s ease, box-shadow 0.15s ease;
}
.sub-task-select :deep(.arco-select-view:hover) {
  border: none;
  background: #e5e7eb;
}
.sub-task-select :deep(.arco-select-view .arco-select-placeholder) {
  color: #6b7280;
  font-size: 12px;
}
.sub-task-select :deep(.arco-select-view .arco-icon) {
  font-size: 12px;
  color: #6b7280;
}
/* 下拉展开的平板 popup 与 Arco 默认一致即可（仅微调圆角/底色） */
.sub-task-select :deep(.arco-select-popup) {
  border-radius: 8px;
}
</style>
