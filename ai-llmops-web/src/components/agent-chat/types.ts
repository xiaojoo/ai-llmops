/**
 * AgentChat 数据模型
 * 会话、上下文附件、消息等类型的统一定义。
 */

/** 会话列表项 */
export interface ChatSession {
  id: string
  title: string
  /** 相对时间文案，如 "7小时前" */
  time: string
  /** 是否收藏 */
  pinned?: boolean
  /** 分组标签：recent = 最近 */
  tags?: string[]
  /** 会话级短期记忆轮数覆盖（null/缺省 = 跟随应用默认） */
  dialogRound?: number | null
}

/** 输入框中的上下文附件（Context Chip） */
export interface ContextAttachment {
  id: string
  /** 显示名称，如 "3. Agentic RAG和普通RAG对文档处理有什么区别？.txt:98" */
  label: string
  type?: 'file' | 'context'
}

/** @ 提及项目文件（Java listProjectFiles 返回） */
export interface FileMentionItem {
  /** 文件名（路径最后一段） */
  name: string
  /** 相对项目根目录的路径，如 "src/main.py" */
  path: string
}

/** WebApp 应用项（插件多 App 切换，Java listWebApps 返回） */
export interface WebAppItem {
  /** web_app_token（/web_apps/{token} 路径中的标识） */
  token: string
  name: string
  icon: string
}

/** 聊天消息 */
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  /** 流式生成中 */
  streaming?: boolean
  /** 消息时间戳 */
  createdAt?: number
  /** 会话 id（SSE 事件携带，用于反馈等） */
  conversationId?: string
  /** 后端消息 id（用于反馈） */
  messageId?: string
  /** 任务 id（SSE 事件 task_id，用于停止/选择） */
  taskId?: string
  /** 点赞/点踩反馈 */
  feedback?: '' | 'like' | 'dislike'
  /** 耗时（秒） */
  latency?: number
  /** token 数 */
  totalTokenCount?: number
  /** 错误信息 */
  error?: string
  /** 用户消息携带的附件（发送时从输入框移入） */
  files?: { id: string; label: string }[]
  /** 待回答的 ask_user 交互（选项/计划确认） */
  askUser?: AskUserInfo | null
  /** 消息状态投影：normal / stop / timeout / error（用于区分生成中 vs 已终态） */
  status?: string
  /** 最新 run 终态：succeeded / cancelled / timed_out / failed / ''(无 run) */
  runStatus?: string
  /** 可断点续跑：显示"继续执行"按钮 */
  canResume?: boolean
}

/** ask_user 交互信息（选项选择 / 计划确认） */
export interface AskUserInfo {
  taskId: string
  eventId: string
  question: string
  options?: string[]
  allowCustom?: boolean
  mode: 'option' | 'plan'
  subTaskOptions?: SubTaskOption[]
  /** 已提交的回显（option: 选项文本；plan: {"action":"confirm","keep_orders":[...]} 或 "重新规划"） */
  choice?: string
}

/** ask_user 提交载荷（发往 Java 桥 choice action） */
export interface AskUserSubmitPayload {
  taskId: string
  eventId: string
  action?: 'confirm' | 'replan'
  choice?: string
  keepOrders?: number[]
  custom?: string
  skip?: boolean
}

/** 计划模式子任务 */
export interface SubTaskOption {
  order: number
  title: string
  role_prompt?: string
  expect_output?: string
}

/** 输入模式：Agent（智能体，可操作工作区文件/执行命令）/ Chat（纯聊天） */
export type ComposerMode = 'agent' | 'chat'

/** 工作区（IDE 当前打开的项目/文件夹），由插件侧 listWorkspaces 提供 */
export interface WorkspaceItem {
  /** 工作区显示名（VS Code 文件夹名 / IDEA 项目名） */
  name: string
  /** 工作区绝对路径（作为 agent 模式 project_root） */
  path: string
}

/** 筛选条件 */
export type SessionFilter = 'all' | 'recent' | 'pinned'
