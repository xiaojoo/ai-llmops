<script setup lang="ts">
/**
 * AgentChat 嵌入组件（供 IDEA 插件 JCEF 加载）
 * SFC 形式——vite 编译期处理模板，避免运行时编译器缺失问题。
 *
 * JS ↔ Java 协议：
 * - JS → Java：window.agentChatHost({ request, onSuccess, onFailure })（JBCefJSQuery/cefQuery 对象协议）
 * - Java → JS：window.__agentChatEvent(JSON.stringify({ type, data }))
 */
import { computed, onMounted, ref } from 'vue'
import AgentChatPanel from '../src/components/agent-chat/AgentChatPanel.vue'
import SessionSettingsDialog from '../src/components/agent-chat/SessionSettingsDialog.vue'
import { resolveStreamOwnership } from '../src/utils/chat-stream-owner'
import type {
  AskUserInfo,
  AskUserSubmitPayload,
  ChatMessage,
  ChatSession,
  ComposerMode,
  ContextAttachment,
  FileMentionItem,
  WebAppItem,
  WorkspaceItem,
} from '../src/components/agent-chat/types'

declare global {
  interface Window {
    agentChatHost?: (arg: {
      request: string
      onSuccess?: (response: string) => void
      onFailure?: (errorCode: number, errorMessage: string) => void
    }) => void
    __agentChatEvent?: (msg: string | object) => void
  }
}

// ===== 桥接层 =====
// JBCefJSQuery 暴露的 window.agentChatHost 即 CefMessageRouter 的 cefQuery_<id> 函数：
// 必须按对象协议调用 { request: <JSON 字符串>, onSuccess, onFailure }，且为异步回调式
// （CEF 校验 "Invalid arguments; expecting a single object" 即来自此协议）。
// Java 侧 handler 返回 Response(result, 0, null)，result 即 {"ok":...,"data":...} JSON 字符串，
// 经 onSuccess 回传；出错走 onFailure。

function callJava<T = unknown>(action: string, payload?: unknown): Promise<T> {
  return new Promise((resolve, reject) => {
    const host = window.agentChatHost
    if (!host) {
      reject(new Error('Java bridge 未就绪'))
      return
    }
    try {
      host({
        request: JSON.stringify({ action, payload: payload ?? {} }),
        onSuccess: (response: string | object) => {
          try {
            // JBCefJSQuery 的 onSuccess 可能回传 JSON 字符串或已解析对象，两者都兼容
            const parsed =
              typeof response === 'string' ? (JSON.parse(response) as { ok: boolean; data?: T; error?: string }) : (response as { ok: boolean; data?: T; error?: string })
            if (parsed && parsed.ok) {
              resolve(parsed.data as T)
            } else {
              reject(new Error(parsed?.error || '调用失败'))
            }
          } catch (e) {
            reject(e instanceof Error ? e : new Error(String(e)))
          }
        },
        onFailure: (errorCode: number, errorMessage: string) => {
          reject(new Error(`Java 调用失败 (${errorCode}): ${errorMessage}`))
        },
      })
    } catch (e) {
      reject(e instanceof Error ? e : new Error(String(e)))
    }
  })
}

// ===== 页面状态 =====

const sessions = ref<ChatSession[]>([])
const messages = ref<ChatMessage[]>([])
const composerText = ref('')
// 默认 Chat（纯聊天）模式；需要操作文件/执行命令时用户手动切到 Agent
const composerMode = ref<ComposerMode>('chat')
const recording = ref(false)
const sending = ref(false)
/** 本次会话推理的顶层 run_id（SSE 事件回写）：用于"主动停止"按钮精准停止整个 run（含编排子任务） */
const currentRunId = ref('')
/** 正在流式那一轮归属的会话 id（'' = 本轮发起时还没建会话，等首帧回写）。
 *  SSE 由宿主持有，切会话不掐连接，所以事件会继续到达——落点必须按这个 id 判，
 *  否则上一轮的正文会追加到新会话最后一条回复上。 */
const streamConversationId = ref('')
/** 本轮是否从空白新会话发起：首帧带回 conversation_id 时才把界面落到那个新会话上 */
const pendingNewConversation = ref(false)
/** 切走期间到达的 ask_user：丢了那一轮就永远卡在等用户输入（历史加载不重建这张卡），先存着 */
const pendingAskUser = new Map<string, AskUserInfo>()
/** 这一轮已经收到的完整正文（无论在不在当前界面上）。切回该会话时用它补气泡：
 *  后端是在 agent_end 之后才落库，中途拉消息只能拿到空占位行，光靠服务端会把已生成的内容看丢。 */
const streamText = ref('')
const attachments = ref<ContextAttachment[]>([])
const loginEmail = ref('')
const loginPassword = ref('')
const loggedIn = ref(false)
const loggingIn = ref(false)
const loginError = ref('')
const appName = ref('')
const appIcon = ref('')
/** 语音转文字开关（App 设置开启才显示麦克风按钮） */
const speechToTextEnabled = ref(false)
/** 可切换的 App 列表（listWebApps） */
const apps = ref<WebAppItem[]>([])
/** 当前 App token（getWebApp/switchWebApp 返回） */
const currentAppToken = ref('')
/** 当前会话标题（会话下拉展示；无会话 = 空 → 显示"新会话"） */
const conversationTitle = computed(() => {
  if (!activeConversationId.value) return ''
  const s = sessions.value.find((x) => x.id === activeConversationId.value)
  return s?.title ?? ''
})
/** 正在切换 App / 加载会话（头部按钮转圈动画） */
const switching = ref(false)
/** 当前会话 id（从 SSE 事件回写，用于连续对话/反馈） */
const activeConversationId = ref('')

// ===== 工作区（IDE 当前打开的项目/文件夹） =====
const workspaces = ref<WorkspaceItem[]>([])
/** 当前选中的工作区路径（作为 agent 模式 project_root） */
const workspacePath = ref('')

async function loadWorkspaces() {
  try {
    const list = (await callJava<WorkspaceItem[]>('listWorkspaces')) ?? []
    workspaces.value = list
    // 默认选中第一个；已选中的路径仍存在则保持不变
    if (!workspacePath.value || !list.some((w) => w.path === workspacePath.value)) {
      workspacePath.value = list[0]?.path ?? ''
    }
  } catch (e) {
    console.error('[AgentChat] listWorkspaces failed:', e)
    workspaces.value = []
    workspacePath.value = ''
  }
}

function onSelectWorkspace(path: string) {
  workspacePath.value = path
}

// ===== 服务连接失败弹窗 =====
const connError = ref('')
const connDialogBusy = ref(false)
/** 后端反馈登录已过期（token 失效）：表明要回到登录页，抑制"服务连接失败"弹窗覆盖 */
const sessionExpired = ref(false)

function showConnError(detail: string) {
  if (sessionExpired.value) return // 登录已过期时以重新登录视图为准，不要弹连接失败
  connError.value = detail || '未知错误'
}

/** 重试：重新初始化（已登录）或重新检查登录态（未登录）。成功即关闭弹窗。 */
async function retryConnection() {
  if (connDialogBusy.value) return
  connDialogBusy.value = true
  try {
    if (loggedIn.value) {
      const ok = await initAfterLogin()
      if (ok) connError.value = ''
    } else {
      await bootstrap()
      if (loggedIn.value) connError.value = ''
    }
  } catch (e) {
    console.error('[AgentChat] retry failed:', e)
    showConnError(e instanceof Error ? e.message : String(e))
  } finally {
    connDialogBusy.value = false
  }
}

// ===== 会话设置（短期记忆轮数） =====
const settingsVisible = ref(false)
const settingsSaving = ref(false)
const settingsError = ref('')
/** 应用默认短期记忆轮数（getWebApp 返回；会话未单独设置时生效） */
const appDefaultRound = ref(3)
/** 当前会话的覆盖值（会话列表里带 dialogRound；未设置 = null） */
const currentDialogRound = computed<number | null>(() => {
  if (!activeConversationId.value) return null
  const s = sessions.value.find((x) => x.id === activeConversationId.value)
  return s && s.dialogRound !== undefined && s.dialogRound !== null ? s.dialogRound : null
})

function onOpenSettings() {
  settingsError.value = ''
  settingsVisible.value = true
}

async function onSaveSettings(round: number | null) {
  if (!activeConversationId.value || settingsSaving.value) return
  settingsSaving.value = true
  settingsError.value = ''
  try {
    await callJava('updateDialogRound', {
      conversationId: activeConversationId.value,
      dialogRound: round,
    })
    // 本地回写会话列表（下次打开弹框直接显示新值）
    const s = sessions.value.find((x) => x.id === activeConversationId.value)
    if (s) s.dialogRound = round
    settingsVisible.value = false
  } catch (e) {
    console.error('[AgentChat] updateDialogRound failed:', e)
    settingsError.value = e instanceof Error ? e.message : String(e)
  } finally {
    settingsSaving.value = false
  }
}

// ===== @ 提及项目文件 =====
const mentionFiles = ref<FileMentionItem[]>([])
const mentionLoading = ref(false)
let mentionDebounceTimer: ReturnType<typeof setTimeout> | null = null
/** 已 @ 选中、待随消息上传的项目文件相对路径（发送后清空；删掉输入框中的路径文本即不再上传） */
const projectMentionPaths = ref<string[]>([])

/** 输入框 @ 提及：父级组件把过滤词上报到这里，调 Java 桥拉取项目文件（防抖）。 */
async function onMentionQuery(query: string | null) {
  if (mentionDebounceTimer !== null) {
    clearTimeout(mentionDebounceTimer)
    mentionDebounceTimer = null
  }
  if (query === null) {
    mentionFiles.value = []
    mentionLoading.value = false
    return
  }
  mentionLoading.value = true
  mentionDebounceTimer = setTimeout(async () => {
    mentionDebounceTimer = null
    try {
      const list = await callJava<FileMentionItem[]>('listProjectFiles', { query })
      mentionFiles.value = list ?? []
    } catch (e) {
      console.error('[AgentChat] listProjectFiles failed:', e)
      mentionFiles.value = []
    } finally {
      mentionLoading.value = false
    }
  }, 150)
}

/** @ 选中文件：记录路径（去重），发送时 Java 侧读取并上传。 */
function onMentionSelect(path: string) {
  if (!path) return
  if (!projectMentionPaths.value.includes(path)) {
    projectMentionPaths.value.push(path)
  }
}

// ===== 事件注册（Java → JS） =====

/** 判一条流事件该不该由当前界面接收，顺带完成"首帧定主"。判定表见 utils/chat-stream-owner。 */
function claimStreamFrame(frameConversationId?: string) {
  const r = resolveStreamOwnership({
    owner: streamConversationId.value,
    pendingNewConversation: pendingNewConversation.value,
    viewConversationId: activeConversationId.value,
    frameConversationId,
  })
  streamConversationId.value = r.owner
  if (r.adoptViewId) pendingNewConversation.value = false
  return r
}

function lastAssistant(): ChatMessage | null {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const m = messages.value[i]
    if (m && m.role === 'assistant') return m
  }
  return null
}

function handleEvent(type: string, data: unknown) {
  switch (type) {
    case 'sessions': {
      sessions.value = (data as ChatSession[]) ?? []
      break
    }
    case 'messages': {
      messages.value = (data as ChatMessage[]) ?? []
      break
    }
    case 'messageDelta': {
      const d = data as {
        content?: string
        conversationId?: string
        messageId?: string
        taskId?: string
        runId?: string
      }
      if (d?.runId) currentRunId.value = d.runId
      const own = claimStreamFrame(d?.conversationId)
      // 这一轮已收到的正文照单全记（切走期间到达的也算）：切回该会话时要拿它补气泡
      if (!d?.conversationId || d.conversationId === own.owner) {
        streamText.value += d?.content ?? ''
      }
      if (!own.visible) break
      if (own.adoptViewId) {
        // 新建会话首条消息：SSE 回写会话 id；变更时刷新会话列表供下拉展示
        activeConversationId.value = own.adoptViewId
        onRefreshSessions()
      }
      const msg = appendDelta(d?.content ?? '')
      if (msg) {
        if (d?.messageId) msg.messageId = d.messageId
        if (d?.taskId) msg.taskId = d.taskId
      }
      break
    }
    case 'askUser': {
      const own = claimStreamFrame()
      if (!own.visible) {
        // 用户此刻在别的会话上：卡片不能挂到这段对话里，也不能丢——切回来再挂
        if (own.owner) pendingAskUser.set(own.owner, data as AskUserInfo)
        break
      }
      attachAskUser(data as AskUserInfo)
      break
    }
    case 'messageEnd': {
      const own = claimStreamFrame()
      streamConversationId.value = ''
      pendingNewConversation.value = false
      currentRunId.value = '' // 本轮结束，停止按钮失效
      streamText.value = ''
      // sending 与界面无关：一轮只允许一个 run，切走时输入框同样是锁住的，结束就要解锁
      sending.value = false
      if (!own.visible) {
        // 结束的是后台那一轮：当前界面不动；切回该会话时从库里拿已落库的完整答案
        break
      }
      const msg = lastAssistant()
      if (msg) {
        msg.streaming = false
        // 实时消息的耗时/token 统计（Java 从最后一个 agent_message 带出）
        const d = data as { latency?: number; totalTokenCount?: number } | undefined
        if (typeof d?.latency === 'number' && d.latency > 0) msg.latency = d.latency
        if (typeof d?.totalTokenCount === 'number' && d.totalTokenCount > 0) {
          msg.totalTokenCount = d.totalTokenCount
        }
        // 空回复：不显示空白框，给出明确提示
        if (!msg.content.trim() && !msg.error) {
          msg.error = '未获取到回复'
        }
      }
      break
    }
    case 'error': {
      const own = claimStreamFrame()
      streamConversationId.value = ''
      pendingNewConversation.value = false
      currentRunId.value = ''
      streamText.value = ''
      sending.value = false
      if (!own.visible) {
        console.warn('[AgentChat] 后台会话的推理异常，当前界面不接收：', data)
        break
      }
      const msg = lastAssistant()
      if (msg) {
        msg.streaming = false
        msg.error = ((data as { message?: string } | undefined)?.message) || '推理过程发生异常'
      }
      // 安全网：应用切换后残留的旧会话归属校验失败 → 清掉本地会话 id，下次发送自动新建会话
      const errMsg = msg?.error || ''
      if (/该会话不存在|不属于当前应用|不属于当前用户/.test(errMsg)) {
        activeConversationId.value = ''
      }
      console.error('[AgentChat] error event:', data)
      break
    }
    case 'setComposerText': {
      // 宿主（IDE/编辑器插件）把选中内容填入输入框，不自动发送（右键菜单"自定义"）
      const d = data as { text?: string } | undefined
      const text = d?.text ?? ''
      if (text) {
        composerText.value = text
      }
      break
    }
    case 'sessionExpired': {
      // 后端反馈登录已过期/token 失效：清登录态回登录页，并展示原因
      const d = data as { message?: string } | undefined
      sessionExpired.value = true
      loggedIn.value = false
      sending.value = false
      loginError.value = d?.message || '登录已过期，请重新登录'
      resetConversationState()
      connError.value = ''
      break
    }
    default:
      break
  }
}

function appendDelta(content: string): ChatMessage | null {
  const last = messages.value[messages.value.length - 1]
  if (last && last.role === 'assistant') {
    last.content += content
    return last
  }
  if (!content) return null
  const msg: ChatMessage = { id: `m-${Date.now()}`, role: 'assistant', content, streaming: true }
  messages.value.push(msg)
  return msg
}

/** 挂载/更新 ask_user 交互卡片（同 eventId 重发 → 更新 choice 回显）。 */
function attachAskUser(info: AskUserInfo) {
  if (!info) return
  let msg = lastAssistant()
  if (!msg) {
    msg = { id: `m-${Date.now()}`, role: 'assistant', content: '', streaming: false }
    messages.value.push(msg)
  }
  if (msg.askUser && msg.askUser.eventId === info.eventId) {
    msg.askUser = { ...msg.askUser, ...info }
  } else {
    msg.askUser = info
  }
}

// ===== 登录 =====

async function onLogin() {
  if (loggingIn.value) return
  loggingIn.value = true
  loginError.value = ''
  try {
    const data = await callJava<{ access_token: string; expire_at: number }>('login', {
      email: loginEmail.value,
      password: loginPassword.value,
    })
    if (data?.access_token) {
      loggedIn.value = true
      sessionExpired.value = false
      await initAfterLogin()
    } else {
      loginError.value = '登录失败（账号或密码错误）'
    }
  } catch (e) {
    console.error('[AgentChat] login failed:', e)
    loginError.value = e instanceof Error ? e.message : String(e)
  } finally {
    loggingIn.value = false
  }
}

async function initAfterLogin(): Promise<boolean> {
  try {
    // 1) 应用列表（多 App 切换）：失败不阻断初始化——后端瞬时不可达时用已存 token 继续，
    //    之后点刷新按钮会重新拉取（onRefreshSessions 同时刷新应用列表）。
    try {
      const appsList = await callJava<WebAppItem[]>('listWebApps')
      apps.value = appsList ?? []
    } catch (e) {
      console.error('[AgentChat] listWebApps failed:', e)
      apps.value = []
    }
    // 1.1) 兜底：账号下没有已发布的 WebApp → 让后端创建+发布一个默认应用，
    //      并成为当前应用（避免"没有已发布 App 插件就不可用"）。
    if (apps.value.length === 0) {
      try {
        const def = await callJava<{ token: string; name: string; icon: string }>('ensureDefaultApp')
        if (def?.token) {
          currentAppToken.value = def.token
          appName.value = def.name || appName.value
          appIcon.value = def.icon || appIcon.value
          // 重新拉取应用列表，让下拉展示到新建的默认应用
          apps.value = (await callJava<WebAppItem[]>('listWebApps')) ?? []
        }
      } catch (e) {
        console.error('[AgentChat] ensureDefaultApp failed:', e)
      }
    }
    // 2) 当前应用信息（settings 里存的 webAppToken）
    const info = await callJava<{ name: string; icon: string; dialogRound?: number; token?: string; speechToTextEnabled?: boolean }>('getWebApp')
    appName.value = info?.name ?? ''
    appIcon.value = info?.icon ?? ''
    currentAppToken.value = info?.token ?? ''
    speechToTextEnabled.value = !!info?.speechToTextEnabled
    if (typeof info?.dialogRound === 'number') {
      appDefaultRound.value = info.dialogRound
    }
    // 3) 已存 token 不在可用列表（被删除/更换）：自动切到第一个应用
    const firstApp = apps.value[0]
    if (
      firstApp &&
      currentAppToken.value &&
      !apps.value.some((a) => a.token === currentAppToken.value)
    ) {
      await onSelectApp(firstApp)
      return true
    }
    const list = await callJava<ChatSession[]>('listSessions')
    sessions.value = list ?? []
    // 拉取 IDE 当前打开的工作区（识别的工作区）
    await loadWorkspaces()
    await resumeLastConversation()
    return true
  } catch (e) {
    console.error('[AgentChat] init failed:', e)
    showConnError(e instanceof Error ? e.message : String(e))
    return false
  }
}

/** 恢复上次会话：不每次新建，打开即加载历史消息，后续发送沿用同一会话。 */
async function resumeLastConversation() {
  try {
    const info = await callJava<{ conversationId: string }>('getLastConversation')
    let cid = info?.conversationId || ''
    // 兜底：插件未记录过会话 id 时（如会话在别处创建/旧数据），取会话列表最新一条恢复
    if (!cid && sessions.value.length > 0) {
      cid = sessions.value[0]?.id || ''
    }
    if (!cid) return
    const msgs = await callJava<ChatMessage[]>('loadMessages', { conversationId: cid })
    activeConversationId.value = cid
    messages.value = msgs ?? []
  } catch (e) {
    console.error('[AgentChat] resume conversation failed:', e)
    // 会话可能已被删除：清空 id，下次发送走新建会话
    activeConversationId.value = ''
  }
}

// ===== 会话 =====

async function onRefreshSessions(showError = false) {
  try {
    const list = await callJava<ChatSession[]>('listSessions')
    sessions.value = list ?? []
  } catch (e) {
    console.error('[AgentChat] refresh sessions failed:', e)
    if (showError) showConnError(e instanceof Error ? e.message : String(e))
  }
}

/** 重新拉取应用列表（打开 App 下拉 / 点刷新时调用，新建的 App 能及时出现）。 */
async function onRefreshApps() {
  try {
    const list = await callJava<WebAppItem[]>('listWebApps')
    apps.value = list ?? []
    // 兜底：当前账号没有已发布的 WebApp → 后端创建+发布默认应用并成为当前应用
    if (apps.value.length === 0) {
      const def = await callJava<{ token: string; name: string; icon: string }>('ensureDefaultApp')
      if (def?.token) {
        currentAppToken.value = def.token
        appName.value = def.name || appName.value
        appIcon.value = def.icon || appIcon.value
        apps.value = (await callJava<WebAppItem[]>('listWebApps')) ?? []
      }
    }
  } catch (e) {
    console.error('[AgentChat] listWebApps refresh failed:', e)
  }
}

/** 刷新按钮：刷新会话（失败弹窗提示）+ 应用列表。 */
async function handleRefresh() {
  await Promise.all([onRefreshSessions(true), onRefreshApps()])
}

/** 清空当前对话状态（切 App / 新建会话共用） */
function resetConversationState() {
  messages.value = []
  composerText.value = ''
  attachments.value = []
  projectMentionPaths.value = []
  activeConversationId.value = ''
  // 界面已经离开那一轮了，就不能再把新会话 id 认领到这块视图上
  // （streamConversationId 要留着：后台那一轮的事件仍按它判归属，继续丢弃）
  pendingNewConversation.value = false
}

/** 切换 App：乐观更新——点击瞬间用下拉项数据立即跳转界面，网络请求后台执行。
 *  避免"点击→跳转"之间等网络造成的卡顿；switching 遮罩覆盖会话/消息加载期。 */
async function onSelectApp(item: WebAppItem) {
  const token = item?.token
  if (!token || token === currentAppToken.value) return
  // 乐观：立即切名称/图标并清空消息，不等 switchWebApp 返回
  resetConversationState()
  currentAppToken.value = token
  appName.value = item.name || appName.value
  appIcon.value = item.icon || appIcon.value
  switching.value = true
  try {
    const info = await callJava<{ name: string; icon: string; dialogRound?: number; token?: string; speechToTextEnabled?: boolean }>(
      'switchWebApp',
      { token },
    )
    // 用后端权威数据校正（名称/图标/语音开关/记忆轮数）
    currentAppToken.value = info?.token ?? token
    appName.value = info?.name || appName.value
    appIcon.value = info?.icon || appIcon.value
    speechToTextEnabled.value = !!info?.speechToTextEnabled
    if (typeof info?.dialogRound === 'number') {
      appDefaultRound.value = info.dialogRound
    }
    await onRefreshSessions()
    const firstSession = sessions.value[0]
    if (firstSession) {
      await onSelectConversation(firstSession.id)
    }
  } catch (e) {
    console.error('[AgentChat] switch app failed:', e)
    showConnError(e instanceof Error ? e.message : String(e))
  } finally {
    switching.value = false
  }
}

/** 选择当前 App 下的某个会话：立即清空界面再加载其消息。 */
async function onSelectConversation(conversationId: string) {
  if (!conversationId) return
  // 先重置，界面立即响应
  resetConversationState()
  // 归属要在取数据之前就落定：留一个"当前会话为空"的窗口，切走期间到达的流事件
  // 会被当成新会话首帧认领到这块视图上
  activeConversationId.value = conversationId
  switching.value = true
  try {
    const msgs = await callJava<ChatMessage[]>('loadMessages', { conversationId })
    messages.value = msgs ?? []
    // 这一轮还在跑就切回来了：库里只有空占位行（答案在流结束才落），用本地这份补气泡。
    // 只在本地更长时覆盖——万一后端已经落库完成，服务端那份才是权威的。
    if (conversationId === streamConversationId.value && streamText.value) {
      const tail = lastAssistant()
      if (tail) {
        if (streamText.value.length > (tail.content || '').length) {
          tail.content = streamText.value
        }
        tail.streaming = true
      } else {
        messages.value.push({
          id: `m-${Date.now()}`,
          role: 'assistant',
          content: streamText.value,
          streaming: true,
        })
      }
    }
    // 切走时到达过的 ask_user 卡片：这里补挂回去，否则那一轮永远卡在等用户输入
    const held = pendingAskUser.get(conversationId)
    if (held) {
      pendingAskUser.delete(conversationId)
      attachAskUser(held)
    }
  } catch (e) {
    console.error('[AgentChat] load conversation failed:', e)
    showConnError(e instanceof Error ? e.message : String(e))
  } finally {
    switching.value = false
  }
}

/** 新建会话：清空当前对话，下次发送自动创建。 */
function onNewConversation() {
  resetConversationState()
}

// ===== 发送 =====

/**
 * 检测用户消息是否包含"需要操作文件/执行命令"的意图关键词。
 * Chat 模式下命中时提示切换 Agent 模式（Agent 才拥有工作区文件与命令执行能力）。
 */
const ACTION_INTENT_RE =
  /(运行|执行|启动|创建|新建|修改|写入|保存|删除|安装|卸载|编译|打包|测试|跑一下|执行命令|执行脚本|命令行|pip |npm |npx |python |pytest |git |\.py\b)/i

/** 发送前的模式引导：Chat 模式下检测到操作意图 → 弹窗询问是否切换 Agent 模式。 */
async function ensureModeBeforeSend(text: string): Promise<boolean> {
  if (composerMode.value === 'agent') return true
  if (!ACTION_INTENT_RE.test(text)) return true
  const wantSwitch = window.confirm(
    '当前是 Chat 模式（纯聊天）。该操作可能涉及文件操作或命令执行，需要 Agent 模式才能完成。\n\n是否切换到 Agent 模式再发送？',
  )
  if (!wantSwitch) return true // 用户选择不切换，仍按 Chat 发送
  composerMode.value = 'agent'
  return true
}

/** 发送逻辑（onSend / 重新生成 / 断点续跑共用）：把 text 作为用户消息发出，并流式生成回答 */
async function sendText(text: string, resumeOptions?: { resume: true; resumeMessageId: string }) {
  if (!text || sending.value) return
  // Chat 模式下检测到操作意图：提示是否切换 Agent 模式（不阻断发送）
  await ensureModeBeforeSend(text)
  // 附件移入用户消息（fileIds 供后端读取），随后清空输入框附件
  const files = [...attachments.value]
  const fileIds = files.filter((a) => a.type === 'file').map((a) => a.id)
  // @ 提及的项目文件：只上传仍留在输入框文本里的路径（删掉路径文本即不再携带）
  const projectFilePaths = projectMentionPaths.value.filter((p) => text.includes(p))
  // 断点续跑：复用上一条用户消息语义，不再重复 push 新 user 消息
  if (!resumeOptions) {
    messages.value.push({ id: `u-${Date.now()}`, role: 'user', content: text, files })
    // 预置空助手消息：流式输出期间显示 loading，增量回填正文
    messages.value.push({
      id: `m-${Date.now()}`,
      role: 'assistant',
      content: '',
      streaming: true,
    })
  } else {
    // 续跑：追加一条新的"续跑中"助手消息，等待流式回填
    messages.value.push({
      id: `m-${Date.now()}`,
      role: 'assistant',
      content: '',
      streaming: true,
    })
  }
  attachments.value = []
  projectMentionPaths.value = []
  sending.value = true
  // 登记这一轮归属哪个会话；新会话此时还没有 id，等首帧回写后再定主
  streamConversationId.value = activeConversationId.value
  pendingNewConversation.value = !activeConversationId.value
  streamText.value = ''
  try {
    await callJava('send', {
      query: text,
      conversationId: activeConversationId.value,
      fileIds,
      projectFilePaths,
      // 对话模式:agent=智能体(可操作工作区文件/执行命令) / chat=纯聊天
      mode: composerMode.value,
      // 选定的工作区（agent 模式作为工具工作目录；chat 模式后端忽略）
      projectRoot: workspacePath.value,
      // 断点续跑：透传 resume 标记与原始消息 id（bridge 侧需转发到后端）
      ...(resumeOptions
        ? { resume: resumeOptions.resume, resumeMessageId: resumeOptions.resumeMessageId }
        : {}),
    })
  } catch (e) {
    console.error('[AgentChat] send failed:', e)
    sending.value = false
    const msg = lastAssistant()
    if (msg) {
      msg.streaming = false
      msg.error = e instanceof Error ? e.message : String(e)
    }
  }
}

function onSend() {
  const rawText = composerText.value
  const text = rawText.trim()
  if (!text) return
  composerText.value = ''
  void sendText(text)
}

/** 重新生成：回发最近一条用户输入，追加一条新回答（仅携带文本） */
function onRegenerate(query: string) {
  if (sending.value) return
  void sendText(query)
}

/** 断点续跑：对已停止/超时/出错但可恢复的消息，以原 query 重新发起（resume + resume_message_id） */
function onContinue(message: ChatMessage) {
  if (sending.value) return
  // 原 query：取该消息对应上一条用户消息的正文（后者是这条 assistant 回复的提问）
  const idx = messages.value.indexOf(message)
  let query = ''
  for (let i = idx - 1; i >= 0; i--) {
    const m = messages.value[i]
    if (m && m.role === 'user' && m.content) {
      query = m.content
      break
    }
  }
  if (!query) {
    // 兜底：找不到原提问（如刷新后仅历史消息），直接用断点续跑（后端以断点 query 为准）
    console.warn('[AgentChat] continue: 未找到原提问，按消息 id 续跑')
  }
  if (!message.messageId) {
    console.warn('[AgentChat] continue: 缺少 messageId，无法续跑')
    return
  }
  void sendText(query, { resume: true, resumeMessageId: message.messageId })
}

/** 主动停止正在回复的 Agent（含编排器的所有子任务）：利用 SSE 事件回写的顶层 run_id。 */
async function onStopSend() {
  if (!sending.value) return
  const taskId = currentRunId.value
  if (!taskId) {
    // 兜底：未拿到 run_id（异常流），仍尝试用最近任务 id 停止；无则不动作
    console.warn('[AgentChat] stop: 无 run_id，无法停止')
    return
  }
  try {
    await callJava('stop', { taskId })
  } catch (e) {
    console.error('[AgentChat] stop failed:', e)
  }
  // 乐观更新：停止后结束 loading；真实 end/error 事件到达时也会重置
  sending.value = false
  currentRunId.value = ''
  const msg = lastAssistant()
  if (msg) {
    msg.streaming = false
    if (!msg.content.trim() && !msg.error) msg.error = '已停止'
  }
}

// ===== 文件上传（加号） =====

const fileInputRef = ref<HTMLInputElement | null>(null)

/** 加号点击：打开文件选择器（不再弹"添加"菜单） */
function onUploadFile() {
  fileInputRef.value?.click()
}

/** 选择文件后：页面直接 fetch 上传到后端（token/baseUrl 由 Java 桥提供），成功后加入附件 */
async function onFileSelected(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  try {
    const info = await callJava<{ token: string; baseUrl: string }>('getAuthToken')
    const form = new FormData()
    form.append('file', file)
    const resp = await fetch(`${(info?.baseUrl || '').replace(/\/+$/, '')}/upload-files/file`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${info?.token ?? ''}` },
      body: form,
    })
    const json = (await resp.json()) as { code?: string; message?: string; data?: { id?: string; name?: string } }
    const data = json?.data
    if (!resp.ok || !data?.id) {
      throw new Error(json?.message || '上传失败')
    }
    attachments.value.push({ id: data.id, label: data.name || file.name, type: 'file' })
  } catch (err) {
    console.error('[AgentChat] upload failed:', err)
  }
}

/** 点击附件标签的 x：从输入框附件中移除（发送时不再携带该文件） */
function onRemoveAttachment(id: string) {
  attachments.value = attachments.value.filter((a) => a.id !== id)
}

// ===== 语音输入（Java 侧录音 → 上传 MinIO → 转文字回填输入框） =====
// JCEF 不支持 getUserMedia/MediaRecorder（前端录音在插件里无法启动），
// 改由 Java 桥用 javax.sound 采集麦克风；后端流程与图片一致：
// /upload-files/file 存 MinIO 拿 key → /audio/audio_to_text 直接识别。
const voiceBusy = ref(false)
/** 语音操作失败提示（轻量、自动消失；不进消息列表） */
const voiceHint = ref('')
let voiceHintTimer: ReturnType<typeof setTimeout> | null = null
function showVoiceHint(msg: string) {
  voiceHint.value = msg
  if (voiceHintTimer !== null) clearTimeout(voiceHintTimer)
  voiceHintTimer = setTimeout(() => {
    voiceHint.value = ''
    voiceHintTimer = null
  }, 4000)
}

/** 麦克风按钮切换：开始/停止录音并转文字 */
async function onRecordingChange(val: boolean) {
  if (val) {
    await startVoiceRecording()
  } else {
    await stopVoiceRecordingAndTranscribe()
  }
}

async function startVoiceRecording() {
  if (voiceBusy.value) return
  try {
    await callJava('startVoiceRecording')
    recording.value = true
  } catch (e) {
    console.error('[AgentChat] 录音失败:', e)
    recording.value = false
    showVoiceHint(`无法开始录音：${e instanceof Error ? e.message : String(e)}`)
  }
}

async function stopVoiceRecordingAndTranscribe() {
  if (!recording.value) return
  recording.value = false
  voiceBusy.value = true
  try {
    const data = await callJava<{ text: string }>('stopVoiceRecording')
    const text = data?.text?.trim()
    if (text) {
      composerText.value = text
    } else {
      console.error('[AgentChat] 未识别到语音内容')
      showVoiceHint('未识别到语音内容，请重试')
    }
  } catch (e) {
    console.error('[AgentChat] 语音识别失败:', e)
    showVoiceHint(`语音转文字失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    voiceBusy.value = false
  }
}

// ===== 消息反馈（点赞/点踩） =====

async function onFeedback(payload: {
  message: ChatMessage
  feedback: '' | 'like' | 'dislike'
}) {
  const { message, feedback } = payload
  message.feedback = feedback
  if (!message.conversationId || !message.messageId) return // 无后端 id，仅本地态
  try {
    await callJava('feedback', {
      conversationId: message.conversationId,
      messageId: message.messageId,
      feedback,
    })
  } catch (e) {
    console.error('[AgentChat] feedback failed:', e)
  }
}

// ===== ask_user 选择 / 计划确认 =====

async function onAskUserSubmit(payload: {
  message: ChatMessage
  payload: AskUserSubmitPayload
}) {
  const { message, payload: p } = payload
  try {
    await callJava('choice', {
      taskId: p.taskId,
      eventId: p.eventId,
      action: p.action,
      choice: p.choice,
      custom: p.custom,
      skip: p.skip ?? false,
      keepOrders: p.keepOrders ?? [],
    })
    // 本地回显（后端随后也会 republish ask_user 带 choice，双保险）
    if (message.askUser) {
      if (p.action === 'replan') {
        message.askUser.choice = '重新规划'
      } else if (p.action === 'confirm') {
        message.askUser.choice = JSON.stringify({
          action: 'confirm',
          keep_orders: p.keepOrders ?? [],
        })
      } else {
        message.askUser.choice = p.choice ?? ''
      }
    }
  } catch (e) {
    console.error('[AgentChat] choice failed:', e)
    if (message.askUser) {
      message.askUser = { ...message.askUser, choice: '' }
    }
  }
}

// ===== 启动时检查登录态 =====

async function bootstrap() {
  try {
    const status = await callJava<{ loggedIn: boolean }>('authStatus')
    if (status?.loggedIn) {
      loggedIn.value = true
      await initAfterLogin()
    }
  } catch (e) {
    // 桥未就绪或后端不可达：弹窗提示服务连接失败（重试会重新检查登录态）
    console.error('[AgentChat] bootstrap failed:', e)
    showConnError(e instanceof Error ? e.message : String(e))
  }
}

onMounted(() => {
  // Java 桥按协议推送 JSON 字符串（JSON.stringify({type,data})）；防御性兼容对象直传
  window.__agentChatEvent = (msg: string | object) => {
    try {
      const evt =
        typeof msg === 'string'
          ? (JSON.parse(msg) as { type: string; data?: unknown })
          : (msg as { type: string; data?: unknown })
      handleEvent(evt.type, evt.data)
    } catch {
      // 忽略畸形事件
    }
  }
  setTimeout(bootstrap, 300)
})
</script>

<template>
  <div class="embed-root">
    <!-- 登录界面 -->
    <div v-if="!loggedIn" class="embed-login">
      <div class="embed-login__title">WebApp 登录</div>
      <input
        v-model="loginEmail"
        name="login-email"
        class="embed-login__input"
        type="text"
        placeholder="账号"
        spellcheck="false"
      />
      <input
        v-model="loginPassword"
        name="login-password"
        class="embed-login__input"
        type="password"
        placeholder="密码"
      />
      <button class="embed-login__btn" :disabled="loggingIn" @click="onLogin">
        {{ loggingIn ? '登录中...' : '登录' }}
      </button>
      <div v-if="loginError" class="embed-login__error">{{ loginError }}</div>
    </div>
    <!-- 主界面（单列：标题 + 消息列表 + 输入框） -->
    <AgentChatPanel
      v-else
      :messages="messages"
      :title="appName || 'WebApp 会话'"
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
      :current-conversation-id="activeConversationId"
      :show-audio-recorder="speechToTextEnabled"
      :switching="switching"
      :workspaces="workspaces"
      :current-workspace="workspacePath"
      @update:composer-text="composerText = $event"
      @update:composer-mode="composerMode = $event"
      @update:recording="onRecordingChange"
      @submit="onSend"
      @stop-send="onStopSend"
      @refresh="handleRefresh"
      @settings="onOpenSettings"
      @refresh-apps="onRefreshApps"
      @select-app="onSelectApp"
      @select-conversation="onSelectConversation"
      @new-conversation="onNewConversation"
      @feedback="onFeedback"
      @ask-user-submit="onAskUserSubmit"
      @regenerate="onRegenerate"
      @continue="onContinue"
      @upload-file="onUploadFile"
      @remove-attachment="onRemoveAttachment"
      @mention-query="onMentionQuery"
      @mention-select="onMentionSelect"
      @select-workspace="onSelectWorkspace"
    />
    <!-- 隐藏的文件选择器（加号触发） -->
    <input ref="fileInputRef" type="file" class="embed-file-input" @change="onFileSelected" />
    <!-- 会话设置弹框（短期记忆轮数） -->
    <SessionSettingsDialog
      v-model:visible="settingsVisible"
      :conversation-id="activeConversationId"
      :current-dialog-round="currentDialogRound"
      :app-default-round="appDefaultRound"
      :saving="settingsSaving"
      :save-error="settingsError"
      @save="onSaveSettings"
    />
    <!-- 切换 App / 加载会话：居中加载遮罩 -->
    <div v-if="switching" class="switching-overlay">
      <span class="switching-spinner"></span>
      <span class="switching-text">加载中…</span>
    </div>
    <!-- 语音操作失败提示（轻量，自动消失） -->
    <Transition name="toast-fade">
      <div v-if="voiceHint" class="voice-hint" role="alert">{{ voiceHint }}</div>
    </Transition>
    <!-- 服务连接失败弹窗 -->
    <div v-if="connError" class="conn-dialog-mask">
      <div class="conn-dialog" role="alertdialog" aria-modal="true">
        <div class="conn-dialog__title">服务连接失败</div>
        <div class="conn-dialog__body">
          <div class="conn-dialog__hint">
            无法连接后端服务，请确认服务已启动、设置中的后端地址正确，然后重试。
          </div>
          <div class="conn-dialog__detail">{{ connError }}</div>
        </div>
        <div class="conn-dialog__footer">
          <button type="button" class="conn-dialog__btn" @click="connError = ''">关闭</button>
          <button
            type="button"
            class="conn-dialog__btn conn-dialog__btn--primary"
            :disabled="connDialogBusy"
            @click="retryConnection"
          >
            {{ connDialogBusy ? '重试中…' : '重试' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style>
@import './style.css';
</style>
