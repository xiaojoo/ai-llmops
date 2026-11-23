# IDEA 插件（webapp-session-window）→ VS Code 插件移植方案

> 目标：复用现有 FastAPI 后端接口与 Vue 聊天界面（样式 100% 不变），把 IDEA 插件
> （`idea-plugin`，编译产物 `webapp-session-window-0.1.0.jar`）迁移为 VS Code 扩展。
>
> 结论先行：**可行，工作量中等偏低（v1 全功能约 3–5 个工作日）**。前端 UI 与后端服务基本不动，
> 需要新写的是 VS Code 扩展壳 + 两个 Java 纯逻辑类的 TypeScript 移植 + 桥接适配。

---

## 1. 现有架构（三层，宿主已解耦）

```
FastAPI 后端（HTTP + SSE）                ← 完全复用，不改
        ↑
IDEA 插件（Java, idea-plugin）      ← 被 VS Code 扩展替换
  WebAppPanel (JCEF 工具窗口)
  WebAppBridge (JS↔Java 桥, JBCefJSQuery)
  WebAppApiClient (JDK HttpClient 调后端)
  SseEventParser (SSE 事件语义解析)
  WebAppSettingsState (持久化)
  VoiceRecorder (javax.sound 录音)
        ↑
Vue 3 前端（ai-llmops-web）           ← 几乎不改
  agent-chat-embed/AgentChatEmbed.vue（入口壳）
  src/components/agent-chat/*.vue（全部 UI）
```

前端与宿主的**全部对接点只有两个全局函数**（`AgentChatEmbed.vue` 42–74 行 / 717 行）：

- `window.agentChatHost({ request, onSuccess, onFailure })` — JS → 宿主
  - `request` = `JSON.stringify({ action, payload })`
  - `onSuccess(response)` 收到 `{"ok":true,"data":...}` 或 `{"ok":false,"error":...}` 的 **JSON 字符串**
  - `onFailure(errorCode, errorMessage)` 协议层失败
- `window.__agentChatEvent(JSON.stringify({ type, data }))` — 宿主 → JS

**关键洞察**：在 VS Code 里只需用 `vscode.postMessage()` / `onDidReceiveMessage` 重新实现这两个
函数，并保持 action 名、事件名、数据形状不变，**整个 Vue 界面一行都不用改**。

---

## 2. 复用清单（不动的东西）

| 资产 | 位置 | 说明 |
|---|---|---|
| Vue 全部 UI | `ai-llmops-web/agent-chat-embed/` + `src/components/agent-chat/*.vue` | 已与传输层解耦 |
| 前端数据模型 | `src/components/agent-chat/types.ts` | ChatMessage / ChatSession / AskUserInfo 等 |
| 前端样式 | `style.css`、组件内样式 | 100% 复用，无 JCEF 特定代码 |
| 后端 FastAPI | `H:\ai-code-llmops\app`（后端服务） | 全部端点原样使用 |
| 前端构建配置 | `vite.agent-chat.config.ts`（单文件产物） | 仅需加 CSP meta + 注入 bridge 脚本 |
| 前端协议（action/event 名） | 见第 4、5 节表 | 保持逐字一致 |

---

## 3. 需要新写 / 移植的内容

| 组件 | 来源（Java） | VS Code 对应 | 工作量 |
|---|---|---|---|
| 扩展壳 + 工具窗口 | `WebAppToolWindowFactory` / `WebAppPanel` | `package.json` + `WebviewViewProvider` | ~200 行，0.5–1 天 |
| API 客户端 | `api/WebAppApiClient.java`（518 行） | `src/api/client.ts`（fetch 移植） | ~350 行，1–1.5 天 |
| SSE 语义解析 | `api/SseEventParser.java`（156 行） | `src/api/sse.ts` | ~90 行，0.5 天 |
| 桥接分发 | `bridge/WebAppBridge.java`（1077 行） | `src/bridge.ts` + `src/webview.ts` | ~250 行，1 天 |
| 状态持久化 | `settings/WebAppSettingsState.java` | `src/state.ts`（globalState / secretStorage / VS Code settings） | ~80 行，0.5 天 |
| 设置面板 | `WebAppSettingsConfigurable.java` | `package.json` `contributes.configuration`（原生设置页） | 少量 JSON，0.5 天 |
| 录音 | `util/VoiceRecorder.java` | `src/voice.ts`（扩展宿主 Node 侧录音，可选） | +1 天（可 v2） |
| 加载态/错误卡片 | `toolwindow/LoadStateOverlay.java` | 前端 CSS 内实现（webview 加载失败 → 连接失败弹窗已存在） | 0 |

不需要移植：`JcefSupport.java`（JCEF 可用性探测）、`AgentChatSchemeHandler.java`（自定义 scheme，
已废弃）、`UrlValidator.java`（旧容器时代设置校验，可并入设置项校验）。

### 新扩展工程结构（建议）

```
vscode-plugin/
├── package.json              # contributes.views / configuration / commands
├── tsconfig.json
├── esbuild.js                # 或 @vscode/vsce 标准打包
├── src/
│   ├── extension.ts          # activate(): 注册 WebviewViewProvider + 命令
│   ├── webview.ts            # WebviewViewProvider：加载单文件 HTML + 消息桥
│   ├── bridge.ts             # action 分发器（WebAppBridge.handle 的移植）
│   ├── api/
│   │   ├── client.ts         # WebAppApiClient 移植
│   │   └── sse.ts            # SseEventParser 移植
│   ├── state.ts              # WebAppSettingsState 移植
│   ├── voice.ts              # （可选）VoiceRecorder 移植
│   └── media/
│       └── index.html        # 构建产物：单文件 HTML + 注入的 vscode bridge 脚本
└── web/                      # 指向 ai-llmops-web 的构建产物（或 CI 里拷贝）
```

前端构建仍在 `ai-llmops-web` 执行 `npx vite build --config vite.agent-chat.config.ts`，
扩展消费 `dist/agent-chat-embed/index.html`（与现在 IDEA 插件的 `syncWebUi` 流程同构）。

---

## 4. 桥协议完整对照表（JS action → 后端/宿主）

以下 action、payload、返回结构**原样保留**，前端 `AgentChatEmbed.vue` 无需改动：

| action | payload | Java 实现点 | 后端调用 | VS Code 实现 |
|---|---|---|---|---|
| `authStatus` | — | `WebAppSettingsState.isLoggedIn()` | 无（本地） | `state.isLoggedIn()` |
| `login` | `{email, password}` | `handleLogin` | `POST /auth/password_login` | `client.login()`，成功后写 secretStorage |
| `logout` | — | `clearAuth()` | 无（本地） | `state.clearAuth()` |
| `getAuthToken` | — | settings 直读 | 无（本地） | 返回 `{token, baseUrl}`（供页面直连上传） |
| `getLastConversation` | — | settings 直读 | 无（本地） | 返回 `{conversationId}` |
| `getWebApp` | — | `handleGetWebApp` | `GET /web_apps/{token}` | `client.getWebApp()` |
| `listWebApps` | — | `handleListWebApps` | `GET /apps?page_size=50` | `client.listWebApps()` |
| `switchWebApp` | `{token}` | `handleSwitchWebApp` | `GET /web_apps/{token}` | 校验 + 写 state + 清 lastConversationId |
| `listSessions` | — | `handleListSessions` | `GET /web_apps/{token}/conversations?is_pinned=false` | `client.listConversations()` |
| `updateDialogRound` | `{conversationId, dialogRound}` | `handleUpdateDialogRound` | `POST /web_apps/{token}/conversations/{id}/settings` | `client.updateDialogRound()` |
| `loadMessages` | `{conversationId}` | `handleLoadMessages` + `toChatMessages` | `GET /conversations/{id}/messages` | `client.getMessages()` + `toChatMessages` 移植 |
| `send` | `{query, conversationId, fileIds, projectFilePaths}` | `handleSend` | 项目文件上传 + `POST /web_apps/{token}/chat`（SSE） | `client.chat()` + 事件经 postMessage 转发 |
| `stop` | `{taskId}` | `handleStop` | `POST /web_apps/{token}/chat/{taskId}/stop` | `client.stop()` |
| `feedback` | `{conversationId, messageId, feedback}` | `handleFeedback` | `POST /conversations/{id}/messages/{mid}/feedback` | `client.feedback()` |
| `choice` | `{taskId, eventId, action, choice, custom, skip, keepOrders}` | `handleChoice` | `POST /web_apps/{token}/chat/{taskId}/choice` | `client.choice()` |
| `listProjectFiles` | `{query}` | `scanProjectFiles` + `filterProjectFiles` | 无（本地扫描） | `workspace.findFiles()`（更简单，见 §7.4） |
| `openFile` | `{path}` | `FileEditorManager.openFile` | 无（IDE） | `workspace.openTextDocument` + `showTextDocument` |
| `getCurrentFile` | — | `getSelectedFiles` | 无（IDE） | `window.activeTextEditor?.document.uri.fsPath` |
| `refresh` | — | `browser.reload()` | 无 | 重新 `webview.html` 或通知前端重载 |
| `startVoiceRecording` | — | `VoiceRecorder.start()` | 无 | 扩展宿主录音启动（可选） |
| `stopVoiceRecording` | — | WAV → 上传 → 识别 | `POST /upload-files/file` + `POST /audio/audio_to_text` | `client.uploadFile` + `client.audioToText` |

**返回协议**：Java 侧 `buildResponse(ok, data, error)` 生成 `{"ok":...}` JSON 字符串经
`onSuccess` 回传。TS 侧移植 `buildResponse`，保证前端 `callJava` 解析逻辑零改动。

---

## 5. 宿主 → JS 事件对照表（SSE → 前端）

| 前端事件 type | 触发 | data 结构 | 来源 |
|---|---|---|---|
| `messageDelta` | SSE `agent_message` | `{content, taskId?, conversationId?, messageId?}` | `deltaJson` 移植 |
| `messageEnd` | SSE `agent_end` / `stop` / `timeout` | `{latency?, totalTokenCount?}`（最后一条 agent_message 统计） | `endStatsJson` 移植 |
| `error` | SSE `error` | `{message}` | `errorJson` 移植 |
| `askUser` | SSE `ask_user` | `{taskId, eventId, question, choice?, allowCustom, options?, subTaskOptions?, mode:'plan'\|'option'}` | `askUserJson` 移植（含下划线→驼峰转换） |
| `sessions` / `messages` | 预留 | 前端 `handleEvent` 已支持，Java 当前不推 | 可保留不实现 |

注意点（移植 `SseEventParser` 时逐条保留）：
- `agent_message` 增量取 `answer` 字段（空白也是有效增量，勿回退到 `message` 分支）
- `agent_thought` 第一版不渲染（Java 直接忽略）
- `ping` 忽略
- 后端 `error` 事件优先取 `observation`，其次 `message`

---

## 6. 关键设计决策

### 6.1 SSE 消费位置：推荐「扩展宿主消费并转发」（与 Java 架构同构）

- **方案 A（推荐）**：扩展宿主（Node）`fetch` 流式消费 SSE（`client.chat` + `sse.ts` 解析），
  事件经 `webview.postMessage({type, data})` 转发；前端 `window.__agentChatEvent` 原样接收。
  - 优点：与 Java 架构逐行对应、token 不进 webview、超时/`askUserPending` 逻辑单一位置、不受 webview 网络限制
  - 移植 60s 超时 + ask_user 等待放行（300s）逻辑（Java `handleSend` 中 `CompletableFuture.get(60s)` 循环）
- **方案 B（备选）**：webview 内 `fetch` + `ReadableStream` 直接消费 SSE。
  - 少一层转发，但需 CSP `connect-src` 放行后端、token 暴露给页面、SSE 解析逻辑在页面里重复实现
- 上传仍可沿用现状：页面经 `getAuthToken` 直连 `POST /upload-files/file`（CSP 加 `connect-src`），
  或统一改走宿主（更稳，推荐）。

### 6.2 webview 加载方式

- VS Code webview **不能加载 `file://`**，用 `webview.html = <内联单文件 HTML>`。
  现有 `vite.agent-chat.config.ts`（`vite-plugin-singlefile`）产物恰好是单文件，直接可用。
- `WebviewOptions`：`enableScripts: true`、`localResourceRoots` 指向扩展 media 目录。
- **CSP**（必须加 meta）：`script-src 'unsafe-inline'`（单文件内联脚本）、`style-src 'unsafe-inline'`、
  `img-src data: https: http:`、`connect-src` 按 6.1 方案决定。
- 加载失败态：沿用前端已有的「服务连接失败」弹窗即可，`LoadStateOverlay` 不移植。

### 6.3 桥协议适配（保持前端零改动）

在构建产物 HTML 的 `<head>` 注入一段 bootstrap 脚本（**在应用脚本之前执行**）：

```js
const vscode = acquireVsCodeApi()
const pending = new Map()            // requestId -> { onSuccess, onFailure }
let seq = 0

window.agentChatHost = ({ request, onSuccess, onFailure }) => {
  const id = ++seq
  pending.set(id, { onSuccess, onFailure })
  vscode.postMessage({ kind: 'call', id, request })   // request 仍是 {action,payload} JSON 字符串
}

window.addEventListener('message', (e) => {
  const msg = e.data
  if (msg && msg.__kind === 'reply') {                 // 宿主回包
    const cb = pending.get(msg.id); pending.delete(msg.id)
    if (cb) msg.errorCode ? cb.onFailure(msg.errorCode, msg.errorMessage)
                          : cb.onSuccess(msg.response) // response = '{"ok":...}' JSON 字符串
  } else if (msg && msg.type) {                        // SSE 事件
    window.__agentChatEvent && window.__agentChatEvent(JSON.stringify({ type: msg.type, data: msg.data }))
  }
})
```

`__agentChatEvent` 本体仍由前端 `onMounted` 注册，不冲突。

### 6.4 状态持久化映射

| Java 字段 | VS Code 存储 |
|---|---|
| `backendUrl` | `contributes.configuration` 设置项 `webapp-chat.backendUrl`（默认 `http://localhost:5000`） |
| `webAppToken` | `context.globalState` |
| `authToken` | `context.secrets`（`secretStorage`，勿明文存 globalState） |
| `email` | `context.globalState` |
| `lastConversationId` | `context.globalState` |

### 6.5 语音输入（可选，建议 v2）

webview 内 `getUserMedia` 在 VS Code 中受限。与 Java 相同思路：扩展宿主用 Node 录音
（`node-record-lpcm16` / `mic` 包）→ WAV → 复用 `client.uploadFile` + `client.audioToText`。
v1 可先隐藏麦克风按钮（`speechToTextEnabled` 由 `getWebApp` 返回，宿主侧置 false 即可）。

### 6.6 前端构建接入

与 IDEA 插件 `syncWebUi` 同理：CI/脚本把 `dist/agent-chat-embed/index.html` 拷进扩展
`media/`，打包时注入 6.3 的 bootstrap 脚本与 CSP meta（注入点要在 `</head>` 前）。

---

## 7. 实施步骤（建议顺序）

| 阶段 | 内容 | 产出/验收 | 估算 |
|---|---|---|---|
| P0 脚手架 | `package.json`、esbuild、`WebviewViewProvider` 加载 hello webview、`contributes.views` 侧边栏 | VS Code 里能打开空 webview | 0.5–1 天 |
| P1 纯逻辑移植 | `api/client.ts` + `api/sse.ts`（含单测） | 与 Java 单测等价通过 | 1–1.5 天 |
| P2 桥接 | `bridge.ts` 分发 + webview 桥 + `state.ts` | 登录 → 会话列表 → 流式对话跑通（最小闭环） | 1 天 |
| P3 功能补齐 | 上传/@提及/openFile/feedback/`updateDialogRound`/ask_user/stop | 与 IDEA 插件功能对齐 | 1 天 |
| P4 打磨 | 设置页、CSP、错误态、多 App 切换回归、打包 vsix | 可分发安装 | 0.5 天 |
| P5 语音（可选） | `voice.ts` 扩展宿主录音 | 麦克风按钮可用 | +1 天 |

**合计：v1（不含语音）约 3.5–5 个工作日。**

---

## 8. 回归验收清单（与 IDEA 插件逐项对齐）

- [ ] 登录/登出；重启 VS Code 后保持登录（secretStorage）
- [ ] 会话列表、切换会话、新建会话、恢复上次会话
- [ ] 流式对话增量渲染；`messageEnd` 耗时/token 统计；60s 超时与 ask_user 等待放行
- [ ] ask_user 选项选择 / 计划确认（confirm / replan / 跳过）
- [ ] 加号上传附件；@ 提及项目文件并随消息上传
- [ ] 点赞/点踩反馈
- [ ] 会话短期记忆轮数设置（含 null = 跟随应用默认）
- [ ] 多 App 切换（乐观更新 + 后端校正）
- [ ] 消息里的文件路径可点击打开（openFile）
- [ ] 语音转文字（若做）
- [ ] 后端不可达时「服务连接失败」弹窗 + 重试

---

## 9. 风险与注意点

1. **CSP 与内联脚本**：单文件产物含内联 `<script type="module">`，CSP 必须放行 `script-src 'unsafe-inline'`，否则整页空白。
2. **协议字符串格式**：`onSuccess` 必须回传 `{"ok":...}` **JSON 字符串**（不是对象），前端 `callJava` 按字符串解析——保持与 JBCefJSQuery 行为一致。
3. **HTTP/1.1**：Java 客户端显式强制 HTTP/1.1（后端 uvicorn 仅支持）。Node `fetch` 默认即 HTTP/1.1，无此问题，但注意不要走 HTTP/2 代理。
4. **超时控制**：Node fetch 无内置 timeout，需 `AbortController` 实现 60s 兜底 + `askUserPending` 放行，逻辑与 Java `handleSend` 一致。
5. **`acquireVsCodeApi()` 只能在 webview 页面内调用**，bootstrap 脚本注入位置必须在应用脚本之前。
6. **webview 生命周期**：不可见时可能被回收，`onDidChangeViewState` / `retainContextWhenHidden` 需处理（会话恢复依赖 `getLastConversation` + `loadMessages`，重挂载即恢复）。
7. **token 安全**：authToken 存 `secretStorage`；方案 A 下 token 全程不进 webview，比现状（`getAuthToken` 暴露给页面）更安全。
8. **多实例**：后端 `lastConversationId` 是全局的，多窗口同时用会互相覆盖（现状亦如此，行为保持一致即可）。

---

## 10. 参考源码位置

| 文件 | 路径 |
|---|---|
| IDEA 插件源码 | `H:\ai-code-llmops\idea-plugin\src\main\java\com\webapp\plugin\` |
| 编译产物 jar | `H:\ai-code-llmops\.tmp\plugin-inspect\webapp-session-window\lib\webapp-session-window-0.1.0.jar` |
| 前端入口壳 | `H:\ai-code-llmops\ai-llmops-web\agent-chat-embed\AgentChatEmbed.vue` |
| 前端 UI 组件 | `H:\ai-code-llmops\ai-llmops-web\src\components\agent-chat\` |
| 前端单文件构建 | `H:\ai-code-llmops\ai-llmops-web\vite.agent-chat.config.ts` |
| 插件 plugin.xml | `H:\ai-code-llmops\idea-plugin\src\main\resources\META-INF\plugin.xml` |
