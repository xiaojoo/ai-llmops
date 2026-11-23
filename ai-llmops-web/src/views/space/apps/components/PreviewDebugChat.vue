<script setup lang="ts">
import { computed, nextTick, onMounted, type PropType, ref, watch } from 'vue'
import { DynamicScroller, DynamicScrollerItem } from 'vue-virtual-scroller'
import {
  useDebugChat,
  useDeleteDebugConversation,
  UseGetDebugConversationMessagesWithPage,
  useStopDebugChat,
} from '@/hooks/use-app.ts'
import 'vue-virtual-scroller/dist/vue-virtual-scroller.css'
import { useAccountStore } from '@/stores/account.ts'
import { useRoute } from 'vue-router'
import AiMessage from '@/views/space/apps/components/AiMessage.vue'
import SubAgentDetail from '@/views/space/apps/components/SubAgentDetail.vue'
import { focusState, setFocusThought } from '@/views/space/apps/components/agent-thought-state'
import AskUserOptions from '@/components/AskUserOptions.vue'
import { Message } from '@arco-design/web-vue'
import { QueueEvent } from '@/config'
import { useGenerateSuggestedQuestions } from '@/hooks/use-ai.ts'
import HumanMessage from '@/components/HumanMessage.vue'
import { useAudioPlayer } from '@/hooks/use-audio.ts'
import { updateMessageFeedback } from '@/services/conversation.ts'
import { submitDebugChoice } from '@/services/app.ts'
import ChatInputBar from '@/components/ChatInputBar.vue'
import type { GetDebugConversationMessagesWithPageResponse } from '@/models/app.ts'
import type { ChatFileItem } from '@/models/chat-file.ts'
import { followupsAllowed } from '@/utils/chat-followups'

type MessageItem = GetDebugConversationMessagesWithPageResponse['data']['list'][number]

// ask_user 交互式选项事件写入 agent_thoughts 时附带的字段
type AskUserThought = {
  id?: string
  event: string
  question?: string
  options?: string[]
  allow_custom?: boolean
  choice?: string
  task_id?: string
  // 编排器任务分配确认：子任务方案（plan 模式）
  sub_task_options?: { order: number; title: string; role_prompt?: string; expect_output?: string; depends_on?: number[] }[]
}

type DebugThought =
  GetDebugConversationMessagesWithPageResponse['data']['list'][number]['agent_thoughts'][number]

const props = defineProps({
  app: {
    type: Object,
    required: true,
    default: () => ({}),
  },
  suggested_after_answer: {
    type: Object as PropType<{ enable: boolean }>,
    required: true,
    default: () => ({ enable: true }),
  },
  opening_statement: {
    type: String,
    required: true,
    default: '',
  },
  opening_questions: {
    type: Array as PropType<string[]>,
    required: true,
    default: () => [],
  },
  text_to_speech: {
    type: Object,
    default: () => {
      return {
        enable: false,
        auto_play: false,
        voice: 'echo',
      }
    },
    required: false,
  },
  speech_to_text: {
    type: Object,
    default: () => ({ enable: false }),
  },
  viewMode: {
    type: String as PropType<ViewMode>,
    default: 'chat',
  },
})

// 摘要行与 tab 切换器由父组件 DetailView 渲染在标题栏正上方，
// 本组件通过 update:view-mode / update:sub-task-summary 事件与之联动
const emit = defineEmits<{
  (e: 'update:viewMode', value: ViewMode): void
  (e: 'update:sub-task-summary', count: number): void
  // 运行态（task_id !== '' && debugChatLoading）上报：父级据此在任务运行中拦截"切换 tab / 离开调试预览"
  (e: 'update:running-state', value: boolean): void
}>()
const route = useRoute()
const query = ref('')
const image_urls = ref<string[]>([])
const file_urls = ref<ChatFileItem[]>([])
const message_id = ref('')
const task_id = ref('')
// 本轮是否"没有正常产出"：error/stop/timeout 事件或用户点停止时置位。
// 放组件级是因为 handleStop 在流外面，收尾的闸门要读得到它。
let chatFailed = false
const accountStore = useAccountStore()
const scroller = ref<{ $el: HTMLElement; scrollToBottom: () => void } | null>(null)
const scrollHeight = ref(0)
const playingMessageId = ref('')
const { loading: deleteDebugConversationLoading, handleDeleteDebugConversation } =
  useDeleteDebugConversation()
const {
  loading: getDebugConversationMessagesWithPageLoading,
  messages,
  loadDebugConversationMessages,
} = UseGetDebugConversationMessagesWithPage()
const { loading: debugChatLoading, handleDebugChat, abort: abortDebugChat } = useDebugChat()
const { loading: stopDebugChatLoading, handleStopDebugChat } = useStopDebugChat()
const { suggested_questions, handleGenerateSuggestedQuestions } = useGenerateSuggestedQuestions()
const {
  startAudioStream: _startAudioStream,
  stopAudioStream: _stopAudioStream,
  isPlaying,
  textToAudioLoading,
} = useAudioPlayer()

const handleClearDebugConversation = async () => {
  await handleStop()
  await handleDeleteDebugConversation(props.app.id)
  emit('update:viewMode', 'chat')
  await loadDebugConversationMessages(props.app.id, true)
}

const saveScrollHeight = () => {
  scrollHeight.value = scroller.value?.$el.scrollHeight ?? 0
}

const restoreScrollPosition = () => {
  if (scroller.value) {
    scroller.value.$el.scrollTop = scroller.value.$el.scrollHeight - scrollHeight.value
  }
}

const handleStop = async () => {
  if (task_id.value === '' || !debugChatLoading.value) return
  // 用户主动停止：先本地置位。abort 之后收不到后端的 stop 事件，不在此置位的话
  // 停止后仍会去取推荐问题、仍会自动播那段没说完的回答。
  chatFailed = true
  // 1、先客户端中断 SSE 流：页面立即停止接收/渲染新输出（不依赖后端停止传播）
  abortDebugChat()
  // 2、再调用后端 stop 接口停止 Agent 任务（防止继续消耗推理；失败不影响界面已停止）
  try {
    await handleStopDebugChat(props.app?.id, task_id.value)
  } catch {
    // 忽略：客户端已停止，后端停止失败不阻塞
  }
}
// ===== 运行态上报：父级（DetailView）据此在任务运行中拦截「切换 tab / 离开调试预览」 =====
const isTaskRunning = computed(() => task_id.value !== '' && debugChatLoading.value)
watch(
  isTaskRunning,
  (running) => {
    emit('update:running-state', running)
  },
  { immediate: true },
)

// 暴露停止逻辑给父级（弹框选择「停止任务并离开」时由父级调用；非运行中 handleStop 本身空转）
defineExpose({ handleStop })
const position = ref(0)
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

// ===== 任务详情：页内 tab（对话 / 任务详情） =====
type ViewMode = 'chat' | 'subagents'

// 子任务总数 = 当前上下文全部消息中出现的去重 sub_task_id（不只看最新一条）
const subTaskCount = computed(() => {
  const ids = new Set<string>()
  for (const message of messages.value) {
    for (const thought of message.agent_thoughts || []) {
      if ((thought as DebugThought).sub_task_id) ids.add((thought as DebugThought).sub_task_id as string)
    }
  }
  return ids.size
})

// 运行流程点击步骤 → 任务详情跳转联动（module 级共享焦点）
const onThoughtStepClick = (messageId: string, thought: DebugThought) => {
  setFocusThought(messageId, thought.id)
  emit('update:viewMode', 'subagents')
}

// 向父组件上报子任务数量（父组件据此在"预览与调试"与"长期记忆"之间渲染摘要行）
watch(
  subTaskCount,
  (count) => {
    emit('update:sub-task-summary', count)
  },
  { immediate: true },
)

// 摘要行已并入预览与调试头部（64px，高度不再随子任务出现变化），消息区高度无需额外补偿
const handleSubmit = async () => {
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

// 编辑用户消息后发送：用修改后的文本重新生成（仅文本）
const onEditSubmit = async (editedText: string) => {
  await sendChat(editedText, [], [], {})
}

// 通用发送逻辑：普通提问 / 断点续跑共用
const sendChat = async (
  text: string,
  images: string[],
  files: ChatFileItem[],
  options: { resume?: boolean; resumeMessageId?: string },
) => {
  if (debugChatLoading.value) {
    Message.warning('上一次提问还未结束，请稍等')
    return
  }

  position.value = 0
  suggested_questions.value = []
  message_id.value = ''
  task_id.value = ''
  emit('update:viewMode', 'chat')
  // 复位本轮失败标记（推荐问题/自动播报只在正常产出时发起）
  chatFailed = false

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
  })

  const humanQuery = text
  const humanImageUrls = images
  const humanFileIds = files.map((file) => file.id)
  query.value = ''
  image_urls.value = []
  file_urls.value = []

  await handleDebugChat(
    props.app?.id,
    humanQuery,
    humanImageUrls,
    humanFileIds,
    (event_response) => {
      const event = event_response?.event
      const data = event_response?.data as
        | {
            id?: string
            message_id?: string
            task_id?: string
            conversation_id?: string
            event?: string
            thought?: string
            observation?: string
            llm_output?: string
            tool_calls?: { name?: string; args?: Record<string, unknown>; id?: string; type?: string }[]
            model_name?: string
            message?: unknown[]
            tool?: string
            tool_input?: string
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
        | undefined

      const currentMessage = messages.value[0]
      if (!currentMessage) return

      const event_id = data?.id
      const agent_thoughts = currentMessage.agent_thoughts

      if (message_id.value === '' && data?.message_id) {
        task_id.value = data?.task_id ?? ''
        message_id.value = data?.message_id
        currentMessage.id = data?.message_id
        currentMessage.conversation_id = data?.conversation_id ?? ''
      }

      // 循环处理得到的事件，记录除ping外的事件
      if (event !== QueueEvent.ping) {
        // Task 4 ruling：后端 ask_user 分支后仍会发布重复的 agent_action(tool='ask_user') 事件，
        // 过滤掉，避免渲染幻影"调用工具"卡片
        if (event === QueueEvent.agentAction && data?.tool === 'ask_user') {
          // 忽略重复事件
        } else if (event === QueueEvent.askUser) {
          // ask_user 交互式选项事件：按 event_id 去重写入 agent_thoughts
          const exists = agent_thoughts.findIndex((item) => item?.id === event_id)
          const payload = {
            id:
              event_id || `temp_thought_${Date.now()}_${Math.random().toString(36).substring(2)}`,
            position: position.value,
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
          } as DebugThought
          if (exists === -1) {
            position.value += 1
            agent_thoughts.push(payload)
          } else {
            // 同 event_id 重发（确认后 republish 回显）：保留已有 sub_task_options 与 choice，
            // 防止 plan 模式被替换成 option 模式（勾选项与回显错乱），也防止无 choice 的
            // republish 覆盖本地乐观回写（markAskUserChoice）的结果
            const existingThought = agent_thoughts[exists] as AskUserThought | undefined
            agent_thoughts[exists] = {
              ...payload,
              choice: data?.choice ?? existingThought?.choice ?? '',
              sub_task_options:
                data?.sub_task_options ?? existingThought?.sub_task_options ?? [],
            } as DebugThought
          }
        } else if (
          event === QueueEvent.error ||
          event === QueueEvent.stop ||
          event === QueueEvent.timeout
        ) {
          // error / stop / timeout 都算"这一轮没有正常产出"：终止推荐问题与自动播报。
          // 原来只认 error——点停止或监听超时后仍然会去取推荐问题、仍然会开播。
          chatFailed = true
          if (event === QueueEvent.error) {
            // 仅异常需要展示错误文案；停止/超时由消息列表按状态给出「继续执行」入口
            currentMessage.error = data?.observation || '推理过程发生异常，请稍后重试'
          }
        } else if (event === QueueEvent.agentMessage) {
          const agent_thought_idx = agent_thoughts.findIndex((item) => item?.id == event_id)

          if (agent_thought_idx === -1) {
            position.value += 1
            agent_thoughts.push({
              id:
                event_id || `temp_thought_${Date.now()}_${Math.random().toString(36).substring(2)}`,
              position: position.value,
              event: data?.event ?? '',
              thought: data?.thought ?? '',
              observation: data?.observation ?? '',
              llm_output: data?.llm_output,
              tool_calls: data?.tool_calls,
              model_name: data?.model_name,
              message: data?.message,
              tool: data?.tool ?? '',
              tool_input: (data?.tool_input ?? '') as unknown as Record<string, unknown>,
              trace: data?.trace,
              latency: data?.latency ?? 0,
              total_token_count: data?.total_token_count,
              total_price: data?.total_price,
              created_at: 0,
              sub_task_id: data?.sub_task_id,
              sub_task_title: data?.sub_task_title,
            })
          } else {
            const currentThought = agent_thoughts[agent_thought_idx]
            if (currentThought) {
              agent_thoughts[agent_thought_idx] = {
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
          // 更新/添加answer答案
          currentMessage.answer += data?.thought || ''
          currentMessage.latency = data?.latency || currentMessage.latency
          currentMessage.total_token_count =
            data?.total_token_count || currentMessage.total_token_count
        } else {
          // 处理其他类型的事件，直接填充覆盖数据
          const exists = agent_thoughts.findIndex((item) => item?.id === event_id)
          if (exists === -1) {
            position.value += 1
            agent_thoughts.push({
              id:
                event_id || `temp_thought_${Date.now()}_${Math.random().toString(36).substring(2)}`,
              position: position.value,
              event: data?.event ?? '',
              thought: data?.thought ?? '',
              observation: data?.observation ?? '',
              llm_output: data?.llm_output,
              tool_calls: data?.tool_calls,
              model_name: data?.model_name,
              message: data?.message,
              tool: data?.tool ?? '',
              tool_input: (data?.tool_input ?? '') as unknown as Record<string, unknown>,
              trace: data?.trace,
              latency: data?.latency ?? 0,
              total_token_count: data?.total_token_count,
              total_price: data?.total_price,
              created_at: 0,
              sub_task_id: data?.sub_task_id,
              sub_task_title: data?.sub_task_title,
            })
          } else {
            // 如果后端通过流式返回观察结果和工具入参，则将其平滑追加合并，解决由于丢弃而导致的缺失及重复渲染问题
            const currentThought = agent_thoughts[exists]
            if (currentThought) {
              agent_thoughts[exists] = {
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
                  ? ((((currentThought.tool_input as unknown as string) || '') +
                      data.tool_input) as unknown as Record<string, unknown>)
                  : currentThought.tool_input,
                trace: data?.trace ?? currentThought.trace,
                latency: data?.latency || currentThought.latency,
                total_token_count: data?.total_token_count ?? currentThought.total_token_count,
                total_price: data?.total_price ?? currentThought.total_price,
                sub_task_id: data?.sub_task_id ?? currentThought.sub_task_id,
                sub_task_title: data?.sub_task_title ?? currentThought.sub_task_title,
                llm_output: data?.llm_output ?? currentThought.llm_output,
                tool_calls: data?.tool_calls ?? currentThought.tool_calls,
                model_name: data?.model_name ?? currentThought.model_name,
                message: data?.message ?? currentThought.message,
              }
            }
          }
        }
        // 更新agent_thoughts
        currentMessage.agent_thoughts = agent_thoughts
        scroller.value?.scrollToBottom()
      }
    },
    options.resume,
    options.resumeMessageId ?? '',
  )

  // 后续动作（推荐问题 / 自动播报）的统一闸门：见 utils/chat-followups
  const canFollowUp = followupsAllowed({
    failed: chatFailed,
    answer: messages.value[0]?.answer,
    messageId: message_id.value,
  })

  if (canFollowUp && props.suggested_after_answer.enable) {
    await handleGenerateSuggestedQuestions(message_id.value)
    setTimeout(() => scroller.value && scroller.value.scrollToBottom(), 100)
  }

  // 检测是否自动播放，如果是则调用hooks播放音频
  if (canFollowUp && props.text_to_speech.enable && props.text_to_speech.auto_play) {
    await handleStartAudio(message_id.value)
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

const handleSubmitQuestion = async (question: string) => {
  query.value = question
  await handleSubmit()
}

// 处理消息反馈（点赞/点踩），同步到后端
const handleMessageFeedback = async (payload: { message_id: string; feedback: string | null }) => {
  const { message_id: msgId, feedback } = payload
  if (!msgId) return
  const item = messages.value.find((m) => m.id === msgId)
  const conversationId = item?.conversation_id
  if (!conversationId) return
  try {
    await updateMessageFeedback(conversationId, msgId, feedback || '')
    // 同步本地消息数据，避免虚拟滚动复用组件实例时回显旧值
    if (item) item.feedback = feedback || ''
    Message.success(feedback ? '感谢你的反馈' : '已取消反馈')
  } catch {
    Message.error('反馈提交失败')
  }
}

// ===== ask_user 交互式选项：取该消息最后一个 ask_user 思考事件 + 提交选择 =====
// 取该消息 agent_thoughts 中最后一个 event === ask_user 的 thought（不存在返回 null）
const getAskUserThought = (item: MessageItem): AskUserThought | null => {
  const thoughts = item.agent_thoughts || []
  for (let i = thoughts.length - 1; i >= 0; i--) {
    const thought = thoughts[i] as AskUserThought | undefined
    if (thought?.event === QueueEvent.askUser) return thought
  }
  return null
}

// 按消息 id 缓存，避免模板 v-for 内重复遍历
const askUserThoughtMap = computed(() => {
  const map = new Map<string, AskUserThought | null>()
  for (const msg of messages.value) {
    map.set(msg.id, getAskUserThought(msg))
  }
  return map
})

const askUserThought = (item: MessageItem): AskUserThought | null =>
  askUserThoughtMap.value.get(item.id) ?? null

// 消息所属任务是否已终态（停止/取消/超时/出错）：终态任务的计划确认框不再可交互
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
      const t = thought as AskUserThought
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
      const t = thought as AskUserThought
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
  if (!payload.taskId || !props.app?.id) {
    // 历史消息里未回答的 ask_user（如 agent 等待超时后刷新页面）可能缺 task_id：
    // 静默 return 会让卡片卡在"已提交，继续处理中…"灰色态，提示并复位组件允许重试
    Message.error('该问题已失效，无法提交选择，请刷新页面重试')
    const staleTarget = messages.value.find((m) =>
      (m.agent_thoughts || []).some((t) => (t as AskUserThought).id === payload.eventId),
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
    // submitDebugChoice 服务层 body 类型未含 action/keep_orders/custom（后端已支持，此处透传）
    await submitDebugChoice(
      props.app.id,
      payload.taskId,
      body as unknown as Parameters<typeof submitDebugChoice>[2],
    )
    Message.success(payload.skip ? '已跳过该问题' : '选择已提交')
  } catch {
    Message.error('选择提交失败，请重试')
    // 回退乐观回显：清空本地 choice + 复位对应 AskUserOptions 组件，恢复按钮可点击以便重试
    clearAskUserChoice(payload.taskId)
    const target = messages.value.find((m) =>
      (m.agent_thoughts || []).some((t) => (t as AskUserThought).task_id === payload.taskId),
    )
    if (target) askUserOptionsRefs.get(target.id)?.reset()
  }
}

const handleScroll = async (event: UIEvent) => {
  const { scrollTop } = event.target as HTMLElement
  if (scrollTop <= 0 && !getDebugConversationMessagesWithPageLoading.value) {
    saveScrollHeight()
    await loadDebugConversationMessages(String(route.params?.app_id), false)
    restoreScrollPosition()
  }
}

const can_speech_to_text = computed(() => {
  if (props) {
    return props.speech_to_text?.enable
  }
  return false
})

// 监听isPlaying，音频真正播完后才清空
watch(isPlaying, (val) => {
  if (!val) {
    playingMessageId.value = ''
  }
})

onMounted(async () => {
  await loadDebugConversationMessages(String(route.params?.app_id), true)
  await nextTick(() => {
    // 确保在视图更新完成后执行滚动操作
    if (scroller.value) {
      scroller.value.scrollToBottom()
    }
  })
})
</script>

<template>
  <div
    class="flex flex-col h-full min-h-0 w-full max-w-[976px] mx-auto"
    :class="messages.length === 0 ? 'items-center justify-center' : ''"
  >
    <!-- 任务详情视图（页内 tab 切换；展示当前上下文全部消息的完整轨迹） -->
    <sub-agent-detail
      v-if="viewMode === 'subagents'"
      :messages="messages"
      :focus-message-id="focusState.messageId"
      :focus-thought-id="focusState.thoughtId"
      :focus-nonce="focusState.nonce"
      class="flex-1 min-h-0 w-full"
    />
    <template v-else>
      <!-- 历史对话列表 -->
      <div
        v-if="messages.length > 0"
        class="flex flex-col px-6 py-2 flex-1 min-h-0 overflow-hidden"
      >
        <dynamic-scroller
          ref="scroller"
          :items="messages.slice().reverse()"
          :min-item-size="1"
          @scroll="handleScroll"
          class="h-full scrollbar-w-none"
        >
          <template v-slot="{ item, active }">
            <dynamic-scroller-item :item="item" :active="active" :data-index="item.id">
              <div class="flex flex-col gap-2 pb-4">
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
                    <div v-show="archivedExpandedIds.has(item.id)" class="flex flex-col bg-white">
                      <div class="text-xs text-gray-400 px-4 pt-3">
                        该轮对话已归档，不再参与模型上下文
                      </div>
                      <div class="px-4 py-3">
                        <div class="text-sm text-gray-800 break-all">{{ item.query }}</div>
                        <div class="text-sm text-gray-800 mt-2 break-all">{{ item.answer }}</div>
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
                    @submit-edit="onEditSubmit"
                  />
                  <ai-message
                    :key="item.id"
                    :message_id="item.id"
                    :enable_text_to_speech="props.text_to_speech.enable"
                    :agent_thoughts="item.agent_thoughts"
                    :answer="item.answer"
                    :status="item.status ?? ''"
                    :run_status="item.run_status ?? ''"
                    :can_resume="item.can_resume === true"
                    :error="item.error"
                    :feedback="item.feedback"
                    :app="props.app"
                    :jumpable="true"
                    @step-click="(thought) => onThoughtStepClick(item.id, thought)"
                    :suggested_questions="item.id === message_id ? suggested_questions : []"
                    :loading="item.id === message_id && debugChatLoading"
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
            </dynamic-scroller-item>
          </template>
        </dynamic-scroller>
        <!-- 停止调试会话 -->
        <div v-if="task_id && debugChatLoading" class="h-[50px] flex items-center justify-center">
          <a-button :loading="stopDebugChatLoading" class="rounded-lg px-2" @click="handleStop">
            <template #icon>
              <icon-poweroff />
            </template>
            停止响应
          </a-button>
        </div>
      </div>
      <div v-else class="w-full px-6 flex flex-col gap-4 pb-4 ab-chat-empty">
        <!-- 应用图标与名称（对齐 demo：图标、推荐问题、输入框整体居中） -->
        <div class="flex flex-col items-center gap-2">
          <a-avatar :size="48" shape="square" class="rounded-lg" :image-url="props.app?.icon" />
          <div class="text-lg text-gray-700 font-semibold">{{ props.app?.name }}</div>
        </div>
        <!-- 对话开场白（对齐 demo .msg.ai 气泡样式） -->
        <div v-if="props.opening_statement" class="ab-opening-bubble">
          {{ props.opening_statement }}
        </div>
        <!-- 开场白建议问题（对齐 demo .qs 两列推荐问题） -->
        <div v-if="props.opening_questions.filter((item) => item.trim() !== '').length" class="ab-qs">
          <button
            v-for="(opening_questions, idx) in props.opening_questions.filter(
              (item) => item.trim() !== '',
            )"
            :key="idx"
            type="button"
            class="ab-q"
            @click="async () => await handleSubmitQuestion(opening_questions)"
          >
            {{ opening_questions }}
          </button>
        </div>
      </div>
    </template>
    <!-- 对话输入框 -->
    <div class="w-full flex flex-col flex-shrink-0 bg-white">
      <!-- 输入栏（清空按钮 + 输入框 + 免责声明，共用组件） -->
      <chat-input-bar
        class="px-6 pt-2"
        v-model="query"
        v-model:image-urls="image_urls"
        v-model:file-urls="file_urls"
        placeholder="请输入内容..."
        :sending="debugChatLoading"
        :clear-loading="deleteDebugConversationLoading"
        :show-audio-recorder="can_speech_to_text"
        :show-file-button="true"
        @submit="handleSubmit"
        @clear="handleClearDebugConversation"
      />
    </div>
  </div>
</template>

<style scoped></style>
