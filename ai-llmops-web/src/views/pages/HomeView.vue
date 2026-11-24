<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useAccountStore } from '@/stores/account'
import { DynamicScroller, DynamicScrollerItem } from 'vue-virtual-scroller'
import 'vue-virtual-scroller/dist/vue-virtual-scroller.css'
import {
  useAssistantAgentChat,
  useDeleteAssistantAgentConversation,
  useGetAssistantAgentMessagesWithPage,
  useStopAssistantAgentChat,
} from '@/hooks/use-assistant-agent'
import type { GetAssistantAgentMessagesWithPageResponse } from '@/models/assistant-agent.ts'
import type { ChatFileItem } from '@/models/assistant-agent.ts'
import { useGenerateSuggestedQuestions } from '@/hooks/use-ai'
import { Message } from '@arco-design/web-vue'
import { QueueEvent } from '@/config'
import AiMessage from '@/views/space/apps/components/AiMessage.vue'
import AskUserOptions from '@/components/AskUserOptions.vue'
import { updateMessageFeedback } from '@/services/conversation.ts'
import { submitAssistantAgentChoice } from '@/services/assistant-agent.ts'
import HumanMessage from '@/components/HumanMessage.vue'
import UserMessageNav from '@/components/UserMessageNav.vue'
import ChatInputBar from '@/components/ChatInputBar.vue'
import { followupsAllowed } from '@/utils/chat-followups'

// ===== 局部类型：SSE 流式事件数据与推理步骤（类型收窄后视图侧补充） =====
type ChatEventData = {
  id?: string
  message_id?: string
  task_id?: string
  conversation_id?: string
  event?: string
  thought?: string
  observation?: string
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
  sub_task_id?: string | null
  sub_task_title?: string
}

type AgentThought = {
  id: string
  position: number
  event: string
  thought: string
  observation: string
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

type MessageItem = GetAssistantAgentMessagesWithPageResponse['data']['list'][number]

type ScrollerInstance = {
  $el: HTMLElement
  scrollToBottom: () => void
}

const query = ref('')
const image_urls = ref<string[]>([])
const file_urls = ref<ChatFileItem[]>([])
const message_id = ref('')
const task_id = ref('')
// 本轮是否"没有正常产出"：error/stop/timeout 事件或用户点停止时置位。
// 放组件级是因为 handleStop 在流外面，收尾的闸门要读得到它。
let chatFailed = false
const scroller = ref<ScrollerInstance | null>(null)
const scrollHeight = ref(0)
const accountStore = useAccountStore()
const opening_questions = ['什么是量子LLMOps？', '我想创建一个应用', '能介绍下什么是RAG吗？']
const app = ref({
  name: 'Agent',
  icon: '/api/default-app-icon',
})

const { suggested_questions, handleGenerateSuggestedQuestions } = useGenerateSuggestedQuestions()
const { loading: assistantAgentChatLoading, handleAssistantAgentChat, abort: abortAssistantAgentChat } = useAssistantAgentChat()
const { loading: stopAssistantAgentChatLoading, handleStopAssistantAgentChat } =
  useStopAssistantAgentChat()
const {
  loading: getAssistantAgentMessagesWithPageLoading,
  messages,
  loadAssistantAgentMessages,
} = useGetAssistantAgentMessagesWithPage()
const { loading: deleteAssistantAgentConversationLoading, handleDeleteAssistantAgentConversation } =
  useDeleteAssistantAgentConversation()

const reversedMessages = computed(() => messages.value.slice().reverse())

const saveScrollHeight = () => {
  scrollHeight.value = scroller.value?.$el.scrollHeight ?? 0
}
const restoreScrollPosition = () => {
  if (scroller.value) {
    scroller.value.$el.scrollTop = scroller.value.$el.scrollHeight - scrollHeight.value
  }
}
const handleScroll = async (event: UIEvent) => {
  const { scrollTop } = event.target as HTMLElement
  if (scrollTop <= 0 && !getAssistantAgentMessagesWithPageLoading.value) {
    saveScrollHeight()
    await loadAssistantAgentMessages(false)
    restoreScrollPosition()
  }
}

// 空白区滚轮转发：消息区两侧留白（px-6 padding）等非滚动区域没有可滚动的祖先，
// 鼠标悬停其上滚动无效。这里把页面空白处的滚轮增量转发给消息滚动容器，
// 目标已在滚动容器内时（气泡/消息本身）交给原生滚动，避免重复滚动。
const handleWheelForward = (event: WheelEvent) => {
  const target = event.target as HTMLElement | null
  // 输入框等表单控件内部有自己的滚动，不拦截
  if (target?.closest?.('textarea, input')) return
  const el = scroller.value?.$el
  if (!el || el.contains(target)) return
  el.scrollTop += event.deltaY
}

// 停止会话
const handleStop = async () => {
  if (task_id.value === '' || !assistantAgentChatLoading.value) return
  // 用户主动停止：先本地置位。abort 之后收不到后端的 stop 事件，不在此置位的话
  // 停止后仍会去取推荐问题。
  chatFailed = true
  // 1、先客户端中断 SSE 流：页面立即停止接收/渲染新输出（不依赖后端停止传播）
  abortAssistantAgentChat()
  // 2、再调用后端 stop 接口停止 Agent 任务（防止继续消耗推理；失败不影响界面已停止）
  try {
    await handleStopAssistantAgentChat(task_id.value)
  } catch {
    // 忽略：客户端已停止，后端停止失败不阻塞
  }
}

// 清空会话
const handleClearDebugConversation = async () => {
  await handleStop()
  await handleDeleteAssistantAgentConversation()
  await loadAssistantAgentMessages(true)
}

// 提交消息
const handleSubmit = async () => {
  if (query.value.trim() === '') {
    Message.warning('用户提问不能为空')
    return
  }
  await sendChat(query.value, image_urls.value, file_urls.value, {})
}

// 断点续跑：重发原 query 并携带 resume: true
const resumeMessage = async (message: MessageItem) => {
  await sendChat(message.query, [], [], { resume: true })
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
  options: { resume?: boolean },
) => {
  if (assistantAgentChatLoading.value) {
    Message.warning('上一次提问还未结束，请稍等')
    return
  }

  suggested_questions.value = []
  message_id.value = ''
  task_id.value = ''
  // 复位本轮失败标记（推荐问题只在正常产出时发起）
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
    created_at: 0,
  })

  let position = 0
  const humanQuery = text
  const humanImageUrls = images
  const humanFileIds = files.map((file) => file.id)
  query.value = ''
  image_urls.value = []
  file_urls.value = []

  await handleAssistantAgentChat(
    humanQuery,
    humanImageUrls,
    humanFileIds,
    (event_response) => {
      const event = event_response?.event
      const data = event_response?.data as ChatEventData | undefined
      const event_id = data?.id

      const currentMessage = messages.value[0]
      if (!currentMessage) return
      const agent_thoughts = currentMessage.agent_thoughts

      if (message_id.value === '' && data?.message_id) {
        task_id.value = data?.task_id ?? ''
        message_id.value = data?.message_id ?? ''
        currentMessage.id = data?.message_id ?? ''
        currentMessage.conversation_id = data?.conversation_id ?? ''
      }

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
          // error / stop / timeout 都算"这一轮没有正常产出"：终止推荐问题请求。
          // 原来只认 error——点停止或监听超时后仍然会去取推荐问题。
          chatFailed = true
          if (event === QueueEvent.error) {
            currentMessage.error = data?.observation || '推理过程发生异常，请稍后重试'
          }
        } else if (event === QueueEvent.agentMessage) {
          const idx = agent_thoughts.findIndex((item) => item?.id === event_id)
          if (idx === -1) {
            position += 1
            agent_thoughts.push({
              id: event_id,
              position,
              event: data?.event,
              thought: data?.thought,
              observation: data?.observation,
              tool: data?.tool,
              tool_input: data?.tool_input,
              trace: data?.trace,
              latency: data?.latency,
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
                latency: data?.latency,
              } as AgentThought
            }
          }
          currentMessage.answer += data?.thought || ''
          currentMessage.latency = data?.latency || currentMessage.latency
          currentMessage.total_token_count =
            data?.total_token_count || currentMessage.total_token_count
        } else {
          const idx = agent_thoughts.findIndex((item) => item?.id === event_id)
          if (idx === -1) {
            position += 1
            agent_thoughts.push({
              id: event_id || `temp_${Date.now()}_${Math.random().toString(36).substring(2)}`,
              position,
              event: data?.event,
              thought: data?.thought,
              observation: data?.observation,
              tool: data?.tool,
              tool_input: data?.tool_input,
              trace: data?.trace,
              latency: data?.latency,
              created_at: 0,
              sub_task_id: data?.sub_task_id,
              sub_task_title: data?.sub_task_title,
            } as AgentThought)
          } else {
            const currentThought = agent_thoughts[idx]
            if (currentThought) {
              agent_thoughts[idx] = {
                ...currentThought,
                event: data?.event || currentThought.event,
                thought: data?.thought
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
                trace: data?.trace ?? currentThought.trace,
                latency: data?.latency || currentThought.latency,
                sub_task_id: data?.sub_task_id ?? currentThought.sub_task_id,
                sub_task_title: data?.sub_task_title ?? currentThought.sub_task_title,
              }
            }
          }
        }
        currentMessage.agent_thoughts = agent_thoughts
        scroller.value?.scrollToBottom()
      }
    },
    options.resume,
  )

  // 闸门：见 utils/chat-followups（本轮要有正文，且不是失败/停止/超时收尾）
  if (
    followupsAllowed({
      failed: chatFailed,
      answer: messages.value[0]?.answer,
      messageId: message_id.value,
    })
  ) {
    await handleGenerateSuggestedQuestions(message_id.value)
  }
  setTimeout(() => scroller.value?.scrollToBottom(), 100)
}

// 点击建议问题
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
  if (!payload.taskId) {
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
    // submitAssistantAgentChoice 服务层 body 类型未含 action/keep_orders/custom（后端已支持，此处透传）
    await submitAssistantAgentChoice(
      payload.taskId,
      body as unknown as Parameters<typeof submitAssistantAgentChoice>[1],
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

// 页面加载
onMounted(async () => {
  await loadAssistantAgentMessages(true)
  await nextTick(() => scroller.value?.scrollToBottom())
})
</script>

<template>
  <div class="h-full rounded-lg pt-2 bg-cover bg-no-repeat bg-center" @wheel="handleWheelForward">
    <div class="h-full flex flex-col">
      <!-- 页面标题栏 -->
      <div class="flex items-center h-16 px-6 shrink-0 bg-white">
        <div class="text-base font-semibold text-gray-700">Agent Robot 智能管家</div>
      </div>
      <!-- 对话区域：空状态 + 输入框整体居中（对齐 web-apps 样式）；有消息时列表滚动、输入框贴底 -->
      <div
        class="w-full relative flex flex-col flex-1 min-h-0"
        :class="messages.length === 0 ? 'items-center justify-center overflow-y-auto scrollbar-w-none' : ''"
      >
      <!-- 对话列表 -->
      <div v-if="messages.length > 0" class="flex flex-col flex-1 min-h-0 w-full relative">
        <dynamic-scroller
          ref="scroller"
          :items="reversedMessages"
          :min-item-size="50"
          key-field="id"
          @scroll="handleScroll"
          class="h-full w-full overflow-y-auto scrollbar-w-none"
        >
          <template v-slot="{ item, index, active }">
            <dynamic-scroller-item :item="item" :active="active" :data-index="index">
              <!-- 内容列在滚动容器内部居中，与 WebApp 页布局一致：滚动区撑满，留白随内容滚动 -->
              <div class="max-w-[976px] mx-auto px-6">
                <div class="flex flex-col gap-2 pb-4">
                  <human-message
                    :query="item.query"
                    :image_urls="item.image_urls"
                    :file_urls="item.file_urls"
                    :account="accountStore.account"
                    @submit-edit="onEditSubmit"
                  />
                  <ai-message
                    :message_id="item.id"
                    :agent_thoughts="item.agent_thoughts"
                    :answer="item.answer"
                    :status="item.status ?? ''"
                    :run_status="item.run_status ?? ''"
                    :can_resume="item.can_resume === true"
                    :app="app"
                    :feedback="item.feedback"
                    :suggested_questions="item.id === message_id ? suggested_questions : []"
                    :loading="item.id === message_id && assistantAgentChatLoading"
                    :latency="item.latency"
                    :total_token_count="item.total_token_count"
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
                </div>
              </div>
            </dynamic-scroller-item>
          </template>
        </dynamic-scroller>
        <!-- 停止按钮 -->
        <div
          v-if="assistantAgentChatLoading"
          class="h-[50px] flex items-center justify-center shrink-0"
        >
          <a-button
            :loading="stopAssistantAgentChatLoading"
            class="rounded-lg px-2"
            @click="handleStop"
          >
            <template #icon>
              <icon-poweroff />
            </template>
            停止响应
          </a-button>
        </div>
        <!-- 右侧用户消息导航条：每条用户消息一个圆点 -->
        <user-message-nav :items="reversedMessages" :scroll-el="scroller?.$el ?? null" />
      </div>
      <!-- 对话为空开场白 -->
      <div v-else class="w-full px-6 flex flex-col items-center gap-4 pb-4">
        <div class="mb-6 text-center">
            <div class="text-[40px] font-bold text-gray-700 mb-4">嗨，我是量子 AI 应用构建器</div>
            <div class="text-[30px] font-bold text-gray-700 mb-2">
              你的专属 <span class="text-blue-700">AI 原生应用</span> 开发平台
            </div>
            <div class="text-base text-gray-700">
              说出你的创意，我可以快速帮你创建专属应用，并一键发布到各大平台。
            </div>
          </div>
          <div class="flex items-center flex-wrap gap-2 w-full justify-center">
            <div
              v-for="(opening_question, idx) in opening_questions"
              :key="idx"
              class="px-4 py-1.5 border rounded-lg text-gray-700 cursor-pointer hover:bg-gray-50"
              @click="handleSubmitQuestion(opening_question)"
            >
              {{ opening_question }}
            </div>
          </div>
        </div>
        <!-- 输入框区域 -->
        <div class="w-full flex flex-col shrink-0 transition-all duration-300">
          <div class="w-full max-w-[976px] mx-auto px-6">
            <chat-input-bar
              v-model="query"
              v-model:image-urls="image_urls"
              v-model:file-urls="file_urls"
              placeholder="发送消息或创建AI应用..."
              :sending="assistantAgentChatLoading"
              :clear-loading="deleteAssistantAgentConversationLoading"
              :show-file-button="true"
              @submit="handleSubmit"
              @clear="handleClearDebugConversation"
            />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 滚动条隐藏 */
.scrollbar-w-none::-webkit-scrollbar {
  display: none;
}
.scrollbar-w-none {
  -ms-overflow-style: none;
  scrollbar-width: none;
}
</style>
