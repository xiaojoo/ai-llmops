/**
 * WebApp 后端 API 客户端（移植自 idea-plugin 的 WebAppApiClient.java）。
 * 基于 Node 全局 fetch（Node >= 18），无第三方运行时依赖。
 *
 * 对接后端 FastAPI：
 * - POST /auth/password_login                 → { access_token, expire_at }
 * - GET  /web_apps/{token}                    → 应用信息
 * - GET  /apps?page_size=50                   → 应用列表
 * - GET  /web_apps/{token}/conversations?is_pinned=false → 会话列表
 * - GET  /conversations/{id}/messages         → 消息历史
 * - POST /web_apps/{token}/chat               → SSE 流式对话
 * - POST /web_apps/{token}/chat/{task_id}/stop → 停止
 * - POST /web_apps/{token}/chat/{task_id}/choice → ask_user 选择
 * - POST /upload-files/file                   → multipart 文件上传
 * - POST /audio/audio_to_text                 → 语音转文字
 * - POST /web_apps/plugin/bootstrap           → 兜底：无已发布 App 时创建+发布默认应用
 * - POST /web_apps/{token}/conversations/{cid}/settings → 短期记忆轮数
 * - POST /conversations/{cid}/messages/{mid}/feedback  → 消息反馈
 */

export interface ChatEvent {
  eventName: string
  data: string
  /** 该帧 SSE `id:` 序号（对齐服务端 [sse-write] 的 seq，断流定位/Last-Event-ID 续传用） */
  seqId: number
}

/** 后端统一响应 { code, message, data } */
interface ApiEnvelope {
  code?: unknown
  message?: unknown
  data?: unknown
}

function parseObject(body: string): ApiEnvelope | null {
  if (!body || !body.trim()) return null
  try {
    const e: unknown = JSON.parse(body)
    return e && typeof e === 'object' && !Array.isArray(e) ? (e as ApiEnvelope) : null
  } catch {
    return null
  }
}

function getString(o: Record<string, unknown>, key: string): string {
  const v = o[key]
  return typeof v === 'string' ? v : ''
}

function getDataObject(json: ApiEnvelope | null): Record<string, unknown> | null {
  if (!json) return null
  const d = json['data']
  return d && typeof d === 'object' && !Array.isArray(d) ? (d as Record<string, unknown>) : null
}

/** 从事件数据（data JSON）里提取 run_id（顶层 run 标识，断线续传用）。 */
function extractRunId(json: string): string | null {
  try {
    const e: unknown = JSON.parse(json)
    if (e && typeof e === 'object' && !Array.isArray(e)) {
      const r = (e as Record<string, unknown>)['run_id']
      return typeof r === 'string' ? r : null
    }
  } catch {
    // ignore
  }
  return null
}

/** 从 agent_message 的 JSON 里提取 task_id */
function extractTaskId(json: string): string | null {
  try {
    const e: unknown = JSON.parse(json)
    if (e && typeof e === 'object' && !Array.isArray(e)) {
      const t = (e as Record<string, unknown>)['task_id']
      return typeof t === 'string' ? t : null
    }
  } catch {
    // ignore
  }
  return null
}

export class WebAppApiClient {
  private readonly baseUrl: string
  private readonly fetchImpl: typeof fetch
  /** 诊断日志（断流定位：chatSSE stream ended / submitToolResult 重试等）。不传则静默。 */
  private readonly log: (line: string) => void
  /** 后端鉴权失败（200 + {code:"unauthorized"}）时触发，供宿主退出登录并提示重新登录。 */
  onAuthFailure?: (message: string) => void

  constructor(baseUrl: string, fetchImpl: typeof fetch = fetch, log?: (line: string) => void) {
    this.baseUrl = trimSlash(baseUrl)
    this.fetchImpl = fetchImpl
    this.log = log ?? (() => {})
  }

  private logLine(line: string): void {
    try {
      this.log(line)
    } catch {
      // 日志通道异常不影响主流程
    }
  }

  /**
   * 识别后端鉴权失败：后端把 401 语义返回成 HTTP 200 + {code:"unauthorized"}，
   * 插件只判断 resp.status 会漏掉。命中时触发 onAuthFailure 并返回 true。
   */
  private checkAuthFailure(json: ApiEnvelope | null): boolean {
    if (json && json['code'] === 'unauthorized') {
      const msg = typeof json['message'] === 'string' ? json['message'] : '登录已过期，请重新登录'
      this.onAuthFailure?.(msg)
      return true
    }
    return false
  }

  // ===== 登录 =====

  /**
   * 账号密码登录。
   * @return 成功：{access_token, expire_at}；失败：{message: <后端真实错误文案>}；null：无法解析
   */
  async login(email: string, password: string): Promise<Record<string, unknown> | null> {
    const resp = await this.fetchImpl(this.baseUrl + '/auth/password_login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    const json = parseObject(await resp.text())
    if (resp.status >= 400 || !json) return null
    const data = getDataObject(json)
    if (data && typeof data['access_token'] === 'string') return data
    // 失败：透传后端 message
    const failure: Record<string, unknown> = {}
    if (typeof json['message'] === 'string') failure['message'] = json['message']
    return failure
  }

  // ===== 应用信息 =====

  async getWebApp(webAppToken: string, authToken: string): Promise<Record<string, unknown> | null> {
    const resp = await this.fetchImpl(this.baseUrl + '/web_apps/' + webAppToken, {
      headers: { Authorization: 'Bearer ' + authToken },
    })
    const json = parseObject(await resp.text())
    if (this.checkAuthFailure(json)) return null
    return getDataObject(json)
  }

  // ===== 应用列表（多 App 切换） =====

  /** 列出当前账号可用的已发布 WebApp 应用（GET /apps?page_size=50，仅 published 且有 token）。 */
  async listWebApps(authToken: string): Promise<{ token: string; name: string; icon: string }[]> {
    const result: { token: string; name: string; icon: string }[] = []
    const resp = await this.fetchImpl(this.baseUrl + '/apps?page_size=50', {
      headers: { Authorization: 'Bearer ' + authToken },
    })
    const json = parseObject(await resp.text())
    this.checkAuthFailure(json)
    const data = getDataObject(json)
    if (!data) return result
    const list = data['list']
    if (Array.isArray(list)) {
      for (const e of list) {
        if (!e || typeof e !== 'object') continue
        const app = e as Record<string, unknown>
        if (getString(app, 'status') !== 'published') continue
        const token = getString(app, 'token')
        if (!token) continue
        result.push({ token, name: getString(app, 'name'), icon: getString(app, 'icon') })
      }
    }
    return result
  }

  // ===== 会话列表 =====

  async listConversations(webAppToken: string, authToken: string): Promise<Record<string, unknown>[]> {
    const result: Record<string, unknown>[] = []
    const resp = await this.fetchImpl(this.baseUrl + '/web_apps/' + webAppToken + '/conversations?is_pinned=false', {
      headers: { Authorization: 'Bearer ' + authToken },
    })
    const json = parseObject(await resp.text())
    this.checkAuthFailure(json)
    const data = json ? json['data'] : undefined
    if (Array.isArray(data)) {
      for (const e of data) {
        if (e && typeof e === 'object' && !Array.isArray(e)) result.push(e as Record<string, unknown>)
      }
    }
    return result
  }

  // ===== 消息历史 =====

  async getMessages(conversationId: string, authToken: string): Promise<Record<string, unknown>[]> {
    const result: Record<string, unknown>[] = []
    const resp = await this.fetchImpl(this.baseUrl + '/conversations/' + conversationId + '/messages', {
      headers: { Authorization: 'Bearer ' + authToken },
    })
    const json = parseObject(await resp.text())
    this.checkAuthFailure(json)
    const data = json ? json['data'] : undefined
    if (data && typeof data === 'object' && !Array.isArray(data)) {
      const list = (data as Record<string, unknown>)['list']
      if (Array.isArray(list)) {
        for (const e of list) {
          if (e && typeof e === 'object' && !Array.isArray(e)) result.push(e as Record<string, unknown>)
        }
      }
    } else if (Array.isArray(data)) {
      for (const e of data) {
        if (e && typeof e === 'object' && !Array.isArray(e)) result.push(e as Record<string, unknown>)
      }
    }
    return result
  }

  // ===== 本地文件上传 =====

  /**
   * 把本地文件以 multipart/form-data（字段名 file）上传到 /upload-files/file。
   * @return 后端 data 对象（{id, name, size, extension, ...}）；失败返回 null
   */
  async uploadFile(authToken: string, filePath: string): Promise<Record<string, unknown> | null> {
    const { readFileSync } = await import('node:fs')
    const bytes = readFileSync(filePath)
    const fileName = filePath.split(/[\\/]/).pop() || 'file'
    const form = new FormData()
    // Buffer 是 Uint8Array，Blob 构造器运行时直接接受；类型上按 ArrayBuffer 处理（无 DOM lib）
    form.append(
      'file',
      new Blob([bytes as unknown as ArrayBuffer], { type: 'application/octet-stream' }),
      fileName,
    )
    const resp = await this.fetchImpl(this.baseUrl + '/upload-files/file', {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + authToken },
      body: form,
    })
    const json = parseObject(await resp.text())
    if (this.checkAuthFailure(json)) return null
    if (resp.status >= 400 || !json) return null
    const data = getDataObject(json)
    if (!data || !data['id']) return null
    return data
  }

  /**
   * 插件兜底：确保账号下至少有一个已发布的 WebApp（没有则后端自动创建+发布）。
   * @return 后端 data 对象（{token, name, icon, id}）；失败返回 null
   */
  async bootstrapDefaultApp(authToken: string): Promise<Record<string, unknown> | null> {
    const resp = await this.fetchImpl(this.baseUrl + '/web_apps/plugin/bootstrap', {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + authToken },
    })
    const json = parseObject(await resp.text())
    if (this.checkAuthFailure(json)) return null
    if (resp.status >= 400 || !json) return null
    const data = getDataObject(json)
    if (!data || !data['token']) return null
    return data
  }

  // ===== SSE 流式对话 =====

  /**
   * 发起流式对话（SSE），逐事件回调 onEvent；流正常结束后返回 taskId（可用来停止）。
   * 与 Java 版一致：HTTP 层失败返回 null；事件在流过程中实时回调。
   *
   * @param mode 对话模式：chat=纯聊天 / agent=智能体（注入工作区文件/命令工具）
   * @param projectRoot Agent 模式的工作区根目录（VS Code 当前工作区路径）
   */
  async chat(
    webAppToken: string,
    authToken: string,
    conversationId: string,
    query: string,
    fileIds: string[] | null,
    mode: string,
    projectRoot: string,
    onEvent: (evt: ChatEvent) => void,
    localToolRuntime = false,
    resume = false,
    resumeMessageId = '',
  ): Promise<string | null> {
    const body = {
      conversation_id: conversationId,
      query,
      image_urls: [],
      file_ids: fileIds ?? [],
      resume,
      ...(resumeMessageId ? { resume_message_id: resumeMessageId } : {}),
      mode,
      project_root: projectRoot,
      local_tool_runtime: localToolRuntime,
    }
    const resp = await this.fetchImpl(this.baseUrl + '/web_apps/' + webAppToken + '/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer ' + authToken,
        Accept: 'text/event-stream',
      },
      body: JSON.stringify(body),
    })
    if (resp.status >= 400 || !resp.body) return null

    // 后端把鉴权/业务错误返回成 HTTP 200 + JSON（非 SSE）
    const contentType = resp.headers.get('content-type') || ''
    if (!contentType.includes('text/event-stream')) {
      const json = parseObject(await resp.text())
      if (this.checkAuthFailure(json)) return null
      // 非鉴权业务错误（如"该WebApp不存在或者未发布"）：透传后端 message，
      // 避免在前端静默变成"未获取到回复"，让用户看到真实原因。
      const msg = json && typeof json['message'] === 'string' ? json['message'] : '回复失败'
      throw new Error(msg)
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    let eventName = 'message'
    let dataBuf = ''
    let taskId: string | null = null
    let runId: string | null = null
    // 最近一帧的 SSE `id:` 序号：断流续传的起点，也是服务端 [sse-write] seq 的对齐锚点
    let lastEventId = 0
    let reconnectAttempts = 0

    const dispatch = (): void => {
      if (dataBuf.length > 0) {
        const evt: ChatEvent = { eventName, data: dataBuf, seqId: lastEventId }
        if (eventName === 'agent_message') {
          const tid = extractTaskId(dataBuf)
          if (tid) taskId = tid
          if (!runId) runId = extractRunId(dataBuf)
        } else if (!runId) {
          runId = extractRunId(dataBuf)
        }
        onEvent(evt)
        dataBuf = ''
      }
      eventName = 'message'
    }

    // 单次连接的逐行读取；被硬断（read 抛错）时带 Last-Event-ID 重连续传端点补发漏掉的事件。
    // 与 Java 版一致：最多重连 3 次，都失败才向外抛（本地工具结果丢失 → 服务器 wait 超时）。
    let current = reader
    for (;;) {
      let streamEnded = false
      try {
        for (;;) {
          const { done, value } = await current.read()
          if (done) {
            streamEnded = true
            break
          }
          buffer += decoder.decode(value, { stream: true })
          let idx: number
          while ((idx = buffer.indexOf('\n')) >= 0) {
            const line = buffer.slice(0, idx)
            buffer = buffer.slice(idx + 1)
            const trimmed = line.endsWith('\r') ? line.slice(0, -1) : line
            if (trimmed === '') {
              dispatch()
            } else if (trimmed.startsWith('event:')) {
              eventName = trimmed.slice(6).trim()
            } else if (trimmed.startsWith('data:')) {
              dataBuf += trimmed.slice(5).trim()
            } else if (trimmed.startsWith('id:')) {
              const seq = parseInt(trimmed.slice(3).trim(), 10)
              if (!Number.isNaN(seq)) lastEventId = seq
            }
          }
        }
      } catch (e) {
        // 连接被硬断：带 Last-Event-ID 重连续传端点（run_id + last_event_id）
        if (!runId || reconnectAttempts >= 3) throw e
        reconnectAttempts++
        this.logLine(
          'chatSSE stream reset, reconnect run=' + runId + ' last_event_id=' + lastEventId
            + ' attempt=' + reconnectAttempts,
        )
        const resumeUrl = this.baseUrl + '/web_apps/' + webAppToken + '/chat/' + runId
          + '/resume?last_event_id=' + lastEventId
        try {
          const r = await this.fetchImpl(resumeUrl, {
            headers: { Authorization: 'Bearer ' + authToken, Accept: 'text/event-stream' },
          })
          if (r.status >= 400 || !r.body) throw e
          current = r.body.getReader()
        } catch {
          throw e // 续传也失败：抛原始断开错误，交由上层提示"连接已断开/请重试"
        }
        continue // 用新连接继续读
      }
      if (streamEnded) break
    }
    // 流结束时 flush 尾部未以空行结尾的事件（比 Java 版更宽容，无副作用）
    if (dataBuf.length > 0) dispatch()
    this.logLine(
      'chatSSE stream ended task=' + (taskId ?? '') + ' last_event_id=' + lastEventId
        + ' reconnect_attempts=' + reconnectAttempts,
    )
    return taskId
  }

  // ===== 本地工具结果回传（Remote Agent + Local Tool Runtime） =====

  /**
   * 把插件本地执行的工具结果回传给后端，供 Agent 解除等待并继续推理。
   * POST /web_apps/{token}/chat/{task_id}/tool-result
   *
   * 失败自动重试（最多 3 次，300/600ms 退避）：本地工具结果一旦丢失，服务器
   * wait_for_tool_result（约 60s）只能等满超时。4xx（除 408）为不可重试的
   * 客户端/校验错误，直接失败；5xx/网络异常可重试。
   *
   * @return true=提交成功（2xx）；false=重试后仍未成功。调用方据 false 提示
   *         "本地工具结果回传失败/超时"，避免静默等待 60s。
   */
  async submitToolResult(
    webAppToken: string,
    authToken: string,
    taskId: string,
    toolCallId: string,
    result: string,
    error: string,
  ): Promise<boolean> {
    const path = '/web_apps/' + webAppToken + '/chat/' + taskId + '/tool-result'
    const body = JSON.stringify({ tool_call_id: toolCallId, result: result ?? '', error: error ?? '' })
    const attempts = 3
    for (let i = 1; i <= attempts; i++) {
      const suffix = i > 1 ? ' (尝试 ' + i + '/' + attempts + ')' : ''
      try {
        const resp = await this.fetchImpl(this.baseUrl + path, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + authToken },
          body,
        })
        if (resp.status < 400) {
          this.logLine('submitToolResult -> ' + path + ' tool_call_id=' + toolCallId
            + ' result_len=' + (result ?? '').length + ' error=' + (error ?? '') + suffix)
          return true
        }
        this.logLine('submitToolResult FAILED status=' + resp.status + ' path=' + path + suffix)
        if (resp.status < 500 && resp.status !== 408) return false
      } catch (e) {
        this.logLine('submitToolResult EXCEPTION path=' + path + suffix + ' '
          + (e instanceof Error ? e.message : String(e)))
      }
      if (i < attempts) await sleep(300 * i) // 300ms / 600ms 退避
    }
    this.logLine('submitToolResult FAILED after ' + attempts + ' attempts: ' + path
      + ' tool_call_id=' + toolCallId)
    return false
  }

  // ===== 停止 =====

  async stop(webAppToken: string, authToken: string, taskId: string): Promise<void> {
    await this.fetchImpl(this.baseUrl + '/web_apps/' + webAppToken + '/chat/' + taskId + '/stop', {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + authToken },
    })
  }

  // ===== 消息反馈（点赞/点踩） =====

  async feedback(
    conversationId: string,
    messageId: string,
    feedback: string,
    authToken: string,
  ): Promise<void> {
    await this.fetchImpl(this.baseUrl + '/conversations/' + conversationId + '/messages/' + messageId + '/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + authToken },
      body: JSON.stringify({ feedback }),
    })
  }

  // ===== ask_user 选择/计划确认 =====

  async choice(webAppToken: string, taskId: string, bodyObj: Record<string, unknown>, authToken: string): Promise<void> {
    await this.fetchImpl(this.baseUrl + '/web_apps/' + webAppToken + '/chat/' + taskId + '/choice', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + authToken },
      body: JSON.stringify(bodyObj),
    })
  }

  // ===== 会话设置（短期记忆轮数） =====

  /** dialogRound: 0-100；null = 恢复使用应用默认（对应后端 JsonNull） */
  async updateConversationDialogRound(
    webAppToken: string,
    conversationId: string,
    dialogRound: number | null,
    authToken: string,
  ): Promise<Record<string, unknown> | null> {
    const resp = await this.fetchImpl(
      this.baseUrl + '/web_apps/' + webAppToken + '/conversations/' + conversationId + '/settings',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + authToken },
        body: JSON.stringify({ dialog_round: dialogRound }),
      },
    )
    const json = parseObject(await resp.text())
    if (this.checkAuthFailure(json)) return null
    if (resp.status >= 400 || !json) return null
    return getDataObject(json)
  }

  // ===== 编辑器代码操作（优化/解释/注释） =====

  /**
   * 编辑器选中代码的 AI 操作（POST /web_apps/{token}/code_action）。
   * @return 成功：{code, explanation}；失败：null
   */
  async codeAction(
    webAppToken: string,
    authToken: string,
    action: 'optimize' | 'explain' | 'comment',
    code: string,
    language: string,
  ): Promise<Record<string, unknown> | null> {
    const resp = await this.fetchImpl(this.baseUrl + '/web_apps/' + webAppToken + '/code_action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + authToken },
      body: JSON.stringify({ action, code, language }),
    })
    const json = parseObject(await resp.text())
    if (resp.status >= 400 || !json) return null
    return getDataObject(json)
  }

  // ===== 语音转文字 =====

  /** ossKey 为 /upload-files/file 返回的 data.key；成功返回识别文本，失败返回 null */
  async audioToText(authToken: string, ossKey: string): Promise<string | null> {
    const resp = await this.fetchImpl(this.baseUrl + '/audio/audio_to_text', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + authToken },
      body: JSON.stringify({ ossUrl: ossKey }),
    })
    const json = parseObject(await resp.text())
    if (this.checkAuthFailure(json)) return null
    if (resp.status >= 400 || !json) return null
    if (json['code'] !== 'success') return null
    const data = getDataObject(json)
    if (!data) return null
    const textArr = data['text']
    if (Array.isArray(textArr) && textArr.length > 0) {
      const first = textArr[0]
      if (first && typeof first === 'object') {
        const transcripts = (first as Record<string, unknown>)['transcripts']
        if (Array.isArray(transcripts) && transcripts.length > 0) {
          const t = transcripts[0]
          if (t && typeof t === 'object') {
            const txt = (t as Record<string, unknown>)['text']
            if (typeof txt === 'string') return txt
          }
        }
      }
    }
    return ''
  }
}

function trimSlash(s: string): string {
  if (!s) return ''
  return s.replace(/\/+$/, '')
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
