# WebApp Session Window — IntelliJ 插件

在 JetBrains IDE（2024.2+，IU 2025.3 开发/验证）右侧工具窗口嵌入 WebApp AI 会话窗口。
**插件自建聊天 UI，直连后端 FastAPI**（不再加载外部 WebApp 页面），前端界面复用
`ai-llmops-web` 的 Vue 组件，样式与 Web 端一致。

> VS Code 移植版见 `../vscode-plugin/README.md`；
> 两端共享同一后端接口与前端界面，桥协议逐字一致。

## 功能

- 右侧工具窗口内嵌 Chromium（JCEF）加载本地打包的聊天界面
- 账号密码登录，token 持久化（重启保持登录），可退出登录
- 会话列表 / 切换 / 新建 / 恢复上次会话
- SSE 流式对话（增量渲染、耗时与 token 统计、60s 超时保护、ask_user 等待放行）
- ask_user 选项选择 / 计划确认（confirm / replan / 跳过）
- 加号上传附件；输入框 `@` 提及项目文件并随消息上传
- 点赞 / 点踩反馈
- 会话短期记忆轮数设置（会话级覆盖，默认跟随应用）
- 多 App 切换（App 下拉，乐观跳转 + 后端校正）
- 语音转文字（Java 侧 `javax.sound` 录音 → 后端 STT）

## 前置条件

- JDK 21 + Gradle Wrapper（`gradlew.bat` 已固定版本）
- 前端单文件产物：`ai-llmops-web/dist/agent-chat-embed/index.html`
  （构建插件前必须先执行，否则 `syncWebUi` 跳过、插件里界面缺失）

```bash
cd ../ai-llmops-web
npx vite build --config vite.agent-chat.config.ts
```

## 打包

```bash
# 在 idea-plugin 目录
.\gradlew.bat buildPlugin
```

产物：`build/distributions/webapp-session-window-0.1.0.zip`（可安装发行包）
插件 jar：`build/libs/webapp-session-window-0.1.0.jar`

> `processResources` 会自动把前端单文件产物同步到 `src/main/resources/web-ui/index.html`。

## 使用方法

### 开发调试

```bash
.\gradlew.bat runIde
```

启动沙箱 IDE（首次会下载/复用平台发行版，耗时较长）。

### 安装到日常 IDE

1. `.\gradlew.bat buildPlugin` 得到 zip
2. IDE 菜单 **Settings → Plugins → ⚙ → Install Plugin from Disk…** 选择该 zip
3. 重启 IDE，右侧出现 **WebApp** 工具窗口

### 配置（Settings → Tools → WebApp）

| 字段 | 说明 | 默认 |
|---|---|---|
| 后端地址 (FastAPI) | 后端 API 基地址（含端口） | `http://localhost:5000` |
| WebApp Token | `/web_apps/{token}` 路径中的标识 | `M0GEcQmJvGMCN5ou` |
| Test Connection | 探测后端地址可达性（HEAD 请求） | — |
| 登录账号 / 退出登录 | 当前登录态展示与登出 | — |

### 使用

- 打开右侧 **WebApp** 工具窗口 → 首次显示登录界面，输入账号密码登录
- 顶部：App 下拉切换、刷新、会话设置（记忆轮数）
- 输入框：`@` 提及项目文件、加号上传附件、发送后流式渲染回复
- 消息：点赞/点踩反馈；含文件路径的消息可点击跳转打开文件（openFile）
- 顶部刷新按钮：重新加载页面

## 桥协议（JS ↔ Java）

- JS → Java：`window.agentChatHost({ request, onSuccess, onFailure })`
  - `request` = `JSON.stringify({ action, payload })`
  - `onSuccess` 收到 `{"ok":...,"data":...}` JSON 字符串；出错走 `onFailure(errorCode, errorMessage)`
- Java → JS：`window.__agentChatEvent(JSON.stringify({ type, data }))`

支持 action：`authStatus / login / logout / getAuthToken / getLastConversation / getWebApp /
listWebApps / switchWebApp / listSessions / updateDialogRound / loadMessages / send / stop /
feedback / choice / listProjectFiles / openFile / getCurrentFile / refresh /
startVoiceRecording / stopVoiceRecording`（`openDirectory` / `getProjectRoot` 已声明未实现）。

SSE 事件映射：`agent_message → messageDelta`、`agent_end/stop/timeout → messageEnd`、
`error → error`、`ask_user → askUser`、`agent_thought`（v1 不渲染）。

## 架构

```
ToolWindow(WebApp, right)
  └─ WebAppPanel (Disposable)
       ├─ JBCefBrowser (JCEF, file:// 加载 web-ui/index.html)
       ├─ LoadStateOverlay (加载/网络错误/认证失效覆盖层)
       └─ WebAppBridge (JBCefJSQuery, JS↔Java)
            ├─ WebAppApiClient (JDK HttpClient 调后端, 强制 HTTP/1.1)
            ├─ SseEventParser (SSE 事件语义解析)
            ├─ VoiceRecorder (javax.sound 录音)
            └─ WebAppSettingsState (持久化: 后端地址/token/登录态/上次会话)
```

## 已知限制

- JCEF 是 IDE 进程级单例，localStorage 存于 IDE 的 JCEF 缓存目录；"Invalidate Caches" 会清空缓存导致需重新登录
- 语音转文字在 Java 侧录音（JCEF 不支持 `getUserMedia`），需系统默认输入设备可用
- 单文件 UI 以 `file://` 加载；改动前端后需重建单文件产物并重新 `buildPlugin`

## 版本

- id: `com.webapp.session-window`，名称 *WebApp Session Window*
- since-build: 253（2025.3），until-build: 261.*（2026.1）
- 依赖：`com.intellij.modules.platform`（JCEF 随 IU 平台提供，运行期 `JbcEFApp.isSupported()` 检测，不可用时展示降级面板）
