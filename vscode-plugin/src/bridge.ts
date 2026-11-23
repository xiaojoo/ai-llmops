/**
 * 桥接分发层（移植自 idea-plugin 的 WebAppBridge.java 非静态部分）。
 * 把 webview 发来的 {action, payload} 请求分发到具体 handler，并把 SSE 事件
 * 通过 pushEvent 回推给 webview（对应 Java 的 executeJavaScript 推送）。
 *
 * 保持与 Java 侧完全一致的 action 名、payload 字段、返回结构，前端零改动。
 * 纯逻辑（协议解析/映射/事件数据构建）在 protocol.ts，可单测。
 */
import * as fs from 'node:fs'
import * as vscode from 'vscode'
import { WebAppApiClient } from './api/client'
import { parseSseEvent, type ParsedEvent } from './api/sse'
import { executeLocalTool } from './api/localTools'
import {
  arrField,
  deltaJson,
  errorJson,
  ok,
  err,
  askUserJson,
  parseRequest,
  resolveProjectPath,
  strField,
  toChatMessages,
  toChatSessions,
  toWebAppInfo,
  CHAT_TIMEOUT_MS,
  MAX_MENTION_FILES,
  MAX_TOTAL_FILE_IDS,
  MAX_PROJECT_FILE_BYTES,
  type BridgeReply,
} from './protocol'
import { StateStore } from './state'

export type { BridgeReply } from './protocol'

const DECLARED_NOT_IMPLEMENTED = new Set(['openDirectory', 'getProjectRoot'])

/**
 * 本地工具"执行+回传"看门狗阈值（ms）：须小于服务器 LOCAL_TOOL_WAIT_TIMEOUT(60s)，
 * 让看门狗先到先报，服务器能提前解除 wait_for_tool_result，不空等满 60s。
 */
const LOCAL_TOOL_WATCHDOG_TIMEOUT_MS = 40_000

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

// ===== 桥 =====

export class Bridge {
  private readonly client: WebAppApiClient
  private lastLatency = 0
  private lastTotalTokens = 0

  constructor(
    private readonly state: StateStore,
    private readonly pushEvent: (type: string, data?: unknown) => void,
    private readonly log: (line: string) => void = (line) => console.log('[webapp-chat] ' + line),
  ) {
    this.client = new WebAppApiClient(state.backendUrl(), fetch, this.log)
    // 后端把鉴权失败返回成 HTTP 200 + {code:"unauthorized"}，交给 client 识别；
    // 命中即清空登录态 + 通知前端切回登录页（避免"发送失败/空白回复"式的静默失败）。
    this.client.onAuthFailure = (message) => {
      void this.state.clearAuth()
      this.pushEvent('sessionExpired', { message })
    }
  }

  async handle(request: string): Promise<BridgeReply> {
    const { action, payload } = parseRequest(request)
    if (!action) return err('请求格式错误')
    try {
      switch (action) {
        case 'authStatus':
          return ok({ loggedIn: await this.state.isLoggedIn() })
        case 'getLastConversation':
          return ok({ conversationId: this.state.lastConversationId() })
        case 'getAuthToken':
          return ok({ token: await this.state.authToken(), baseUrl: this.state.backendUrl() })
        case 'login':
          return this.handleLogin(payload)
        case 'logout':
          await this.state.clearAuth()
          return ok('logged out')
        case 'getWebApp':
          return this.handleGetWebApp()
        case 'listWebApps':
          return this.handleListWebApps()
        case 'ensureDefaultApp':
          return this.handleEnsureDefaultApp()
        case 'switchWebApp':
          return this.handleSwitchWebApp(payload)
        case 'listSessions':
          return this.handleListSessions()
        case 'updateDialogRound':
          return this.handleUpdateDialogRound(payload)
        case 'loadMessages':
          return this.handleLoadMessages(payload)
        case 'send':
          return this.handleSend(payload)
        case 'stop':
          return this.handleStop(payload)
        case 'feedback':
          return this.handleFeedback(payload)
        case 'choice':
          return this.handleChoice(payload)
        case 'listProjectFiles':
          return this.handleListProjectFiles(payload)
        case 'listWorkspaces':
          return this.handleListWorkspaces()
        case 'openFile':
          return this.handleOpenFile(payload)
        case 'getCurrentFile':
          return ok({ path: vscode.window.activeTextEditor?.document.uri.fsPath ?? '' })
        case 'refresh':
          // 新聊天 UI 不再用该 action（刷新走 listSessions/listWebApps）；保留以兼容
          return ok('ok')
        case 'startVoiceRecording':
        case 'stopVoiceRecording':
          return err('未实现（v1 不支持语音输入）')
        default:
          if (DECLARED_NOT_IMPLEMENTED.has(action)) return err('未实现: ' + action)
          return err('未知 action: ' + action)
      }
    } catch (e) {
      return err('处理失败: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  // ===== 登录 =====

  private async handleLogin(payload: Record<string, unknown>): Promise<BridgeReply> {
    const email = strField(payload, 'email')
    const password = strField(payload, 'password')
    if (email == null || password == null) return err('email/password 缺失')
    try {
      const data = await this.client.login(email, password)
      if (!data || typeof data['access_token'] !== 'string') {
        const reason = data && typeof data['message'] === 'string' ? data['message'] : '登录失败（账号或密码错误）'
        return err(reason)
      }
      await this.state.setAuthToken(data['access_token'])
      await this.state.setEmail(email)
      const result: Record<string, unknown> = { access_token: data['access_token'] }
      if (typeof data['expire_at'] === 'number') result['expire_at'] = data['expire_at']
      return ok(result)
    } catch (e) {
      return err('登录异常: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  // ===== 应用信息 =====

  private async requireAuth(): Promise<string | null> {
    const token = await this.state.authToken()
    return token ? token : null
  }

  private async handleGetWebApp(): Promise<BridgeReply> {
    const authToken = await this.requireAuth()
    if (!authToken) return err('未登录')
    try {
      const info = await this.client.getWebApp(this.state.webAppToken(), authToken)
      return ok(toWebAppInfo(info, this.state.webAppToken()))
    } catch (e) {
      return err('获取应用信息失败: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  /**
   * 兜底：确保账号下至少有一个已发布的 WebApp（没有则后端创建+发布），
   * 并把返回的 token 持久化为当前应用。前端在"账号下无已发布应用"时调用。
   */
  private async handleEnsureDefaultApp(): Promise<BridgeReply> {
    const authToken = await this.requireAuth()
    if (!authToken) return err('未登录')
    try {
      const info = await this.client.bootstrapDefaultApp(authToken)
      if (!info || !info['token']) return err('获取默认应用失败')
      const token = String(info['token'])
      await this.state.setWebAppToken(token)
      // 应用变了：清掉旧应用的会话 id，避免下次发送带着不属于新应用的会话（后端会报"The conversation 不存在"）
      await this.state.setLastConversationId('')
      const result: Record<string, unknown> = { token }
      if (typeof info['name'] === 'string') result['name'] = info['name']
      if (typeof info['icon'] === 'string') result['icon'] = info['icon']
      return ok(result)
    } catch (e) {
      return err('获取默认应用失败: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  private async handleListWebApps(): Promise<BridgeReply> {
    const authToken = await this.requireAuth()
    if (!authToken) return err('未登录')
    try {
      return ok(await this.client.listWebApps(authToken))
    } catch (e) {
      return err('获取应用列表失败: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  private async handleSwitchWebApp(payload: Record<string, unknown>): Promise<BridgeReply> {
    const authToken = await this.requireAuth()
    const token = strField(payload, 'token')
    if (!authToken || !token || !token.trim()) return err('未登录或缺少 token')
    try {
      // 先校验 token 有效（getWebApp 对不存在/未发布会抛错）
      const info = await this.client.getWebApp(token, authToken)
      await this.state.setWebAppToken(token)
      await this.state.setLastConversationId('') // 换 App 后从该 App 最新会话重新恢复
      return ok(toWebAppInfo(info, token))
    } catch (e) {
      return err('切换应用失败: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  // ===== 会话 =====

  private async handleListSessions(): Promise<BridgeReply> {
    const authToken = await this.requireAuth()
    if (!authToken) return err('未登录')
    try {
      const convs = await this.client.listConversations(this.state.webAppToken(), authToken)
      return ok(toChatSessions(convs))
    } catch (e) {
      return err('获取会话列表失败: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  private async handleUpdateDialogRound(payload: Record<string, unknown>): Promise<BridgeReply> {
    const authToken = await this.requireAuth()
    const conversationId = strField(payload, 'conversationId')
    if (!authToken || !conversationId || !conversationId.trim()) return err('未登录或缺少会话 id')
    const roundRaw = payload['dialogRound']
    let dialogRound: number | null = null
    if (roundRaw !== null && roundRaw !== undefined) {
      dialogRound = typeof roundRaw === 'number' ? roundRaw : parseInt(String(roundRaw), 10)
      if (Number.isNaN(dialogRound)) return err('短期记忆轮数格式错误')
    }
    try {
      const data = await this.client.updateConversationDialogRound(
        this.state.webAppToken(),
        conversationId,
        dialogRound,
        authToken,
      )
      if (!data) return err('保存会话设置失败')
      const result: Record<string, unknown> = { conversationId }
      if (typeof data['dialog_round'] === 'number') result['dialogRound'] = data['dialog_round']
      return ok(result)
    } catch (e) {
      return err('保存会话设置失败: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  // ===== 消息历史 =====

  private async handleLoadMessages(payload: Record<string, unknown>): Promise<BridgeReply> {
    const authToken = await this.requireAuth()
    const conversationId = strField(payload, 'conversationId')
    if (!authToken || conversationId == null) return err('未登录或缺少会话 id')
    try {
      const msgs = await this.client.getMessages(conversationId, authToken)
      return ok(toChatMessages(msgs, conversationId))
    } catch (e) {
      return err('加载消息失败: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  // ===== 发送（SSE 流式） =====

  private async handleSend(payload: Record<string, unknown>): Promise<BridgeReply> {
    const authToken = await this.requireAuth()
    const query = strField(payload, 'query')
    const conversationId = strField(payload, 'conversationId')
    if (!authToken || query == null) return err('未登录或缺少 query')

    // 对话模式:agent=智能体(可操作当前工作区文件/执行命令) / chat=纯聊天(默认,兼容旧 auto)
    let mode = strField(payload, 'mode') || 'chat'
    if (mode === 'auto') mode = 'chat' // 兼容旧前端值
    if (mode !== 'agent' && mode !== 'chat') return err('mode 只能是 agent/chat')

    const ids: string[] = []
    for (const e of arrField(payload, 'fileIds')) {
      if (typeof e === 'string' && e) ids.push(e)
    }

    // Agent 模式必须能拿到工作区(工具的工作目录)：优先用前端选定的工作区，否则取第一个文件夹
    let projectRoot = ''
    if (mode === 'agent') {
      projectRoot = strField(payload, 'projectRoot') ?? ''
      if (!projectRoot) projectRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? ''
      if (!projectRoot) return err('Agent 模式需要打开工作区（文件夹），请先打开项目再使用')
    }

    // 1) 同步上传 @ 提及的项目文件（复用后端上传通道 → 上传 id 并入 file_ids）
    const projectFilePaths = arrField(payload, 'projectFilePaths').filter(
      (e): e is string => typeof e === 'string' && !!e.trim(),
    )
    if (projectFilePaths.length > 0) {
      if (ids.length + projectFilePaths.length > MAX_TOTAL_FILE_IDS) {
        return err('附件数量不能超过' + MAX_TOTAL_FILE_IDS + '个')
      }
      const basePath = strField(payload, 'projectRoot') || vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
      if (!basePath) return err('当前工作区无根目录，无法上传项目文件')
      for (const rel of projectFilePaths) {
        const abs = resolveProjectPath(basePath, rel)
        if (!abs) return err('项目文件路径不合法: ' + rel)
        try {
          if (fs.statSync(abs).size > MAX_PROJECT_FILE_BYTES) {
            return err('项目文件过大（超过10MB）: ' + rel)
          }
          const up = await this.client.uploadFile(authToken, abs)
          if (!up || !up['id']) return err('上传项目文件失败: ' + rel)
          ids.push(String(up['id']))
        } catch (e) {
          return err('上传项目文件失败: ' + rel + '（' + (e instanceof Error ? e.message : String(e)) + '）')
        }
      }
    }

    // 2) 发起 SSE 流式对话（不阻塞；事件经 pushEvent 回推 webview）
    this.lastLatency = 0
    this.lastTotalTokens = 0
    let askUserPending = false
    // 本地工具运行时等待插件执行期间置位：60s 超时保护对"等本地工具结果"场景放行（同 ask_user）
    let localToolPending = false
    // 断点续跑：透传前端传来的 resume 标记 + 原始消息 id
    const resume = payload['resume'] === true
    const resumeMessageId = strField(payload, 'resumeMessageId') ?? ''
    // 最近一次收到 SSE 事件的时间：超时改为"空闲超时"——只要流里有任何事件就重置计时。
    // 编排器规划（曾耗时 44s）+ 工具等待 + 续跑叠加远超固定 60s，固定总时长会误杀。
    let lastActivityAt = Date.now()
    const streamDone = (async (): Promise<void> => {
      try {
        await this.client.chat(
          this.state.webAppToken(),
          authToken,
          conversationId ?? '',
          query,
          ids,
          mode,
          projectRoot,
          (evt) => {
            lastActivityAt = Date.now()
            const parsed = parseSseEvent(evt.eventName, evt.data)
            // 断流定位日志：只记粗粒度事件（thought/end/askUser/error/localToolCall），
            // 忽略 MESSAGE_DELTA(每 token chunk) 与 IGNORE(ping 心跳)——配合服务端
            // [sse-write] 的 seq，可判断事件是"服务端没发出"还是"发出后插件没收到"。
            if (parsed.kind !== 'messageDelta' && parsed.kind !== 'ignore') {
              this.log('SSE recv kind=' + parsed.kind + ' event=' + evt.eventName
                + ' seq=' + evt.seqId + ' dataLen=' + evt.data.length)
            }
            if (parsed.kind === 'localToolCall') {
              // 本地工具运行时：插件本地执行并回传结果（不阻塞 SSE 消费，异步执行）
              localToolPending = true
              void this.handleLocalToolCall(parsed, authToken, projectRoot)
              return
            }
            this.onSseEvent(parsed, {
              onAskUser: () => {
                askUserPending = true
              },
              onEnd: () => {
                askUserPending = false
                localToolPending = false
              },
            })
          },
          // Agent 模式 + 选定本地工作区 → 启用本地工具运行时（文件工具在插件本地执行）
          mode === 'agent' && !!projectRoot,
          // 断点续跑：透传 resume + resume_message_id 到后端
          resume,
          resumeMessageId,
        )
        this.pushEvent('messageEnd', this.endStatsJson())
      } catch (e) {
        this.pushEvent('error', errorJson(e instanceof Error ? e.message : String(e)))
      }
    })()
    // 空闲超时保护：超过 CHAT_TIMEOUT_MS（60s）没有任何事件/等待才判超时；
    // ask_user/本地工具等待期间不视为超时（后端 ASK_USER_WAIT_TIMEOUT=300s）
    void this.watchChat(streamDone, () => askUserPending || localToolPending, () => lastActivityAt)
    return ok('started')
  }

  private async watchChat(
    task: Promise<void>,
    pending: () => boolean,
    lastActivityAt: () => number,
  ): Promise<void> {
    for (;;) {
      const result = await Promise.race([
        task.then(() => 'done' as const),
        sleep(CHAT_TIMEOUT_MS).then(() => 'timeout' as const),
      ])
      if (result === 'done') return
      if (pending()) continue
      // 空闲超时：只要最近仍有事件（含 ping 心跳）就继续等，避免编排器规划/工具等待误杀
      if (Date.now() - lastActivityAt() < CHAT_TIMEOUT_MS) continue
      this.pushEvent('error', errorJson('回复超时，请重试'))
      return
    }
  }

  private async handleStop(payload: Record<string, unknown>): Promise<BridgeReply> {
    const authToken = await this.requireAuth()
    const taskId = strField(payload, 'taskId')
    if (!authToken || taskId == null) return err('未登录或缺少 taskId')
    void this.client
      .stop(this.state.webAppToken(), authToken, taskId)
      .catch(() => {
        /* 停止失败静默 */
      })
    return ok('stopping')
  }

  // ===== 消息反馈 =====

  private async handleFeedback(payload: Record<string, unknown>): Promise<BridgeReply> {
    const authToken = await this.requireAuth()
    const conversationId = strField(payload, 'conversationId')
    const messageId = strField(payload, 'messageId')
    const feedback = strField(payload, 'feedback')
    if (!authToken || conversationId == null || messageId == null || feedback == null) {
      return err('参数缺失或未登录')
    }
    try {
      await this.client.feedback(conversationId, messageId, feedback, authToken)
      return ok('ok')
    } catch {
      return err('反馈提交失败')
    }
  }

  // ===== ask_user 选择 / 计划确认 =====

  private async handleChoice(payload: Record<string, unknown>): Promise<BridgeReply> {
    const authToken = await this.requireAuth()
    const taskId = strField(payload, 'taskId')
    if (!authToken || taskId == null) return err('未登录或缺少 taskId')
    const action = strField(payload, 'action') // plan 模式: confirm / replan
    const choice = strField(payload, 'choice') // option 模式
    const custom = strField(payload, 'custom')
    const body: Record<string, unknown> = {}
    if (action != null) {
      body['action'] = action
      body['keep_orders'] = arrField(payload, 'keepOrders')
      body['custom'] = custom ?? ''
    } else {
      body['choice'] = choice ?? ''
      body['custom'] = custom ?? ''
    }
    // 前端发 boolean 或字符串 "true"（对应 Java "true".equals(skipRaw)）
    const skipVal = payload['skip']
    body['skip'] = skipVal === true || skipVal === 'true'
    const eventId = strField(payload, 'eventId')
    if (eventId != null && eventId.trim()) body['event_id'] = eventId
    void this.client
      .choice(this.state.webAppToken(), taskId, body, authToken)
      .catch(() => {
        /* 静默 */
      })
    return ok('submitted')
  }

  // ===== @ 提及项目文件 =====

  private async handleListProjectFiles(payload: Record<string, unknown>): Promise<BridgeReply> {
    const query = strField(payload, 'query')
    try {
      const uris = await vscode.workspace.findFiles(
        '**/*',
        '**/{.git,.idea,.gradle,node_modules,build,out,dist,target,venv,.venv,__pycache__,.tox,.mypy_cache,.pytest_cache,.next,.nuxt,coverage}/**',
        MAX_MENTION_FILES,
      )
      const q = (query ?? '').trim().toLowerCase()
      let rels = uris.map((u) => vscode.workspace.asRelativePath(u, false).replace(/\\/g, '/'))
      if (q) rels = rels.filter((p) => p.toLowerCase().includes(q))
      rels.sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }))
      if (rels.length > MAX_MENTION_FILES) rels = rels.slice(0, MAX_MENTION_FILES)
      return ok(
        rels.map((rel) => {
          const idx = rel.lastIndexOf('/')
          return { name: idx >= 0 ? rel.slice(idx + 1) : rel, path: rel }
        }),
      )
    } catch (e) {
      return err('列出项目文件失败: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  // ===== 工作区列表（IDE 当前打开的项目/文件夹） =====

  private async handleListWorkspaces(): Promise<BridgeReply> {
    const folders = vscode.workspace.workspaceFolders ?? []
    return ok(
      folders.map((f) => ({ name: f.name, path: f.uri.fsPath })),
    )
  }

  // ===== 打开文件 =====

  private async handleOpenFile(payload: Record<string, unknown>): Promise<BridgeReply> {
    const filePath = strField(payload, 'path')
    if (!filePath || !filePath.trim()) return err('path 缺失')
    try {
      const uri = vscode.Uri.file(filePath)
      const doc = await vscode.workspace.openTextDocument(uri)
      await vscode.window.showTextDocument(doc, { preview: true })
      return ok('opened')
    } catch {
      return err('文件不存在: ' + filePath)
    }
  }

  // ===== 本地工具运行时（Remote Agent + Local Tool Runtime） =====

  /**
   * 处理服务器下发的 local_tool_call：在插件本地执行 fs_list/fs_read/fs_search 等
   * 文件工具，并把结果回传给 /web_apps/{token}/chat/{task_id}/tool-result（含 tool_call_id 关联）。
   * projectRoot 为当前选定工作区（本地绝对路径），是唯一路径权威。
   *
   * 看门狗语义（防静默丢结果 + 防回传黑洞）：
   *   1) 执行前登记 40s 看门狗：若"执行 + 回传"超过 LOCAL_TOOL_WATCHDOG_TIMEOUT_MS
   *      （40s，小于服务器 60s 等待上限）仍未完成，由看门狗尽力 POST 一次超时错误，
   *      服务器可提前解除 wait_for_tool_result；
   *   2) worker / 看门狗经 posted 竞争保证同一 tool_call_id 只会回传一次结果。
   * 帧解析失败 / 缺关键字段不再静默：打 WARN 日志显性化，避免"本地工具莫名超时"无迹可查。
   */
  private async handleLocalToolCall(
    parsed: ParsedEvent,
    authToken: string,
    projectRoot: string,
  ): Promise<void> {
    const raw = parsed.raw
    if (!raw) {
      // 帧解析失败（服务端历史截断/传输问题）会导致 task/tool_call_id 全缺失：
      // 无法回传结果，服务器将等到 60s 超时。此处必须打日志显性化，避免"静默丢失工具"。
      this.log('WARN 本地工具 local_tool_call 帧解析失败（data 为空/非法 JSON，可能被服务端截断），'
        + '本次本地工具调用已丢弃——服务端将等待至超时')
      return
    }
    const taskId = typeof raw['task_id'] === 'string' ? raw['task_id'] : ''
    const toolCallId = typeof raw['tool_call_id'] === 'string' ? raw['tool_call_id'] : ''
    const tool = typeof raw['tool'] === 'string' ? raw['tool'] : ''
    const ti = raw['tool_input']
    const toolInput = ti && typeof ti === 'object' && !Array.isArray(ti)
      ? (ti as Record<string, unknown>)
      : {}
    if (!taskId || !toolCallId || !tool) {
      this.log('WARN 本地工具 local_tool_call 缺少关键字段 task_id=' + (taskId || '-')
        + ' tool_call_id=' + (toolCallId || '-') + ' tool=' + (tool || '-')
        + '（dataLen=' + JSON.stringify(raw).length + '，可能被截断）——已丢弃，无法回传')
      this.pushEvent('error', errorJson('本地工具调用缺少 task_id/tool_call_id/tool'))
      return
    }
    this.log('本地工具执行开始 tool=' + tool + ' task=' + taskId + ' tool_call_id=' + toolCallId
      + ' projectRoot=' + (projectRoot || ''))
    const posted = { value: false }

    // 看门狗：40s 内"执行 + 回传"未完成 → 尽力 POST 超时错误（独立于 SSE，能提前解除服务器等待）
    const watchdog = setTimeout(() => {
      if (posted.value) return
      this.log('WARN 本地工具看门狗触发 tool=' + tool + ' tool_call_id=' + toolCallId
        + '（>' + (LOCAL_TOOL_WATCHDOG_TIMEOUT_MS / 1000) + 's 未完成），尽力回传超时错误')
      void this.postToolResult(posted, authToken, taskId, toolCallId, tool, '',
        '本地工具执行超时（插件看门狗 ' + (LOCAL_TOOL_WATCHDOG_TIMEOUT_MS / 1000) + 's 未完成）', 'watchdog')
    }, LOCAL_TOOL_WATCHDOG_TIMEOUT_MS)

    try {
      if (!projectRoot) {
        // 没有本地工作区：直接回传失败，避免 Agent 空等至超时
        const result = JSON.stringify({
          success: false, operation: tool, error: { code: 'NO_WORKSPACE', message: '未选择本地工作区' },
        })
        await this.postToolResult(posted, authToken, taskId, toolCallId, tool, result, '未选择本地工作区', 'worker')
        return
      }
      const result = executeLocalTool(projectRoot, tool, toolInput)
      await this.postToolResult(posted, authToken, taskId, toolCallId, tool, result, '', 'worker')
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e)
      this.log('WARN 本地工具执行异常 tool=' + tool + '：' + message)
      await this.postToolResult(posted, authToken, taskId, toolCallId, tool, '', message, 'worker')
    } finally {
      clearTimeout(watchdog) // 已回传：撤掉看门狗（未回传时看门狗自带 posted 竞争，重复触发也无害）
    }
  }

  /**
   * 回传工具结果（posted 竞争保证同一 tool_call_id 只回传一次：worker 完成与看门狗超时竞争时只有一个胜出）。
   * 回传彻底失败（重试 3 次后）→ 向 UI 推一条可见提示，避免"莫名中断"式静默。
   */
  private async postToolResult(
    posted: { value: boolean },
    authToken: string,
    taskId: string,
    toolCallId: string,
    tool: string,
    result: string,
    error: string,
    tag: string,
  ): Promise<void> {
    if (posted.value) {
      this.log('WARN 本地工具结果已回传（tag=' + tag + '）tool=' + tool
        + ' tool_call_id=' + toolCallId + ' — 丢弃本次回传')
      return
    }
    posted.value = true
    const ok = await this.client.submitToolResult(
      this.state.webAppToken(), authToken, taskId, toolCallId, result, error,
    )
    if (!ok) this.pushToolTimeout(tool)
  }

  /**
   * 本地工具结果回传重试后仍失败（服务器 wait_for_tool_result 约 60s 后会判超时）时，
   * 向用户界面即时推送一条"执行超时/请重试"提醒，避免用户只见"莫名中断"。
   */
  private pushToolTimeout(tool: string): void {
    this.pushEvent('messageDelta', {
      content: '⏱️ 本地工具 ' + tool + ' 执行超时/结果回传失败（已自动重试）。'
        + '请重试该操作；若持续失败，请检查与后端的连接。',
    })
  }

  // ===== SSE 事件推送 =====

  private onSseEvent(parsed: ParsedEvent, hooks: { onAskUser: () => void; onEnd: () => void }): void {
    // 记录最近会话 id（持久化）：下次打开插件恢复上次会话
    if (parsed.conversationId) {
      void this.state.setLastConversationId(parsed.conversationId)
    }
    switch (parsed.kind) {
      case 'messageDelta': {
        const raw = parsed.raw
        if (raw) {
          if (typeof raw['latency'] === 'number') this.lastLatency = raw['latency']
          if (typeof raw['total_token_count'] === 'number') this.lastTotalTokens = raw['total_token_count']
        }
        this.pushEvent('messageDelta', deltaJson(parsed))
        break
      }
      case 'end':
        hooks.onEnd()
        this.pushEvent('messageEnd', this.endStatsJson())
        break
      case 'error':
        hooks.onEnd()
        this.pushEvent('error', errorJson(parsed.content))
        break
      case 'askUser':
        hooks.onAskUser()
        this.pushEvent('askUser', askUserJson(parsed))
        break
      case 'thought':
      case 'ignore':
        // 第一版不渲染 thought 细节
        break
    }
  }

  /** messageEnd 数据：最后一条 agent_message 的耗时/token 统计 */
  private endStatsJson(): Record<string, unknown> {
    const o: Record<string, unknown> = {}
    if (this.lastLatency > 0) o['latency'] = this.lastLatency
    if (this.lastTotalTokens > 0) o['totalTokenCount'] = this.lastTotalTokens
    return o
  }
}
