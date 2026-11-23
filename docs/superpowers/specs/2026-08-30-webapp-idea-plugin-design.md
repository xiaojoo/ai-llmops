# WebApp 会话窗口 IntelliJ 插件 — 设计文档

- 日期：2026-08-30
- 状态：approved（v2 修订版）
- 目标 IDE：IntelliJ Platform 2024.2+，含 JCEF 的商业 IDE（IDEA Ultimate / PyCharm Professional / WebStorm / GoLand 等；Community 不含 JCEF 不适用）
- 关联代码：`ai-code-llmops-web`（Vue 3 + Vite，`/web-apps/:token` 会话页）、`internal/`（FastAPI 后端，`/web_apps/{token}/chat` SSE 接口）
- 插件工程：`H:\ai-code-llmops\idea-webapp-plugin\`（新建独立 Gradle 工程）

## 背景与目标

用户希望在 JetBrains IDE 中直接使用现有 WebApp 的 AI 会话窗口（`/web-apps/:token`），避免在 IDE 与浏览器之间来回切换。已确认的形态：**IDE 内嵌浏览器窗口（JCEF）**，插件只做"WebApp 容器"，不重复实现登录 / SSE / 会话 / Agent 逻辑。

本次目标：
1. 在 IDE 右侧新增 **WebApp 工具窗口**，内嵌 JCEF 浏览器加载配置的 WebApp URL。
2. 登录态由 WebApp 页面自身管理，插件不参与 Token / 认证。
3. 登录态跨 IDE 重启保持（显式持久化 JCEF 缓存目录）。
4. 预留 WebApp ↔ IDE 双向通信（Bridge）扩展点，第一版只实现最小子集。
5. 明确生命周期（Disposable 链）、加载状态 UI、URL 安全校验、版本兼容策略。

明确不做：
- 不做文件系统读写（与 Agent FileSystem Tool 严格分离）。
- 不实现 WebApp 业务逻辑（登录、SSE、会话、Agent 由页面完成）。
- 第一版不支持 Remote Development（但 URL 配置化，不锁死架构）。

## 方案选型

- **方案（选定）**：Tool Window + JBCefBrowser 内嵌 Chromium，加载现有 WebApp 页面；JBCefJSQuery 提供 Bridge；PersistentStateComponent 持久化设置；Swing 覆盖层承载降级 / 加载状态 UI。
- 弃选：插件直连后端 API 自建聊天 UI（维护两套前端/通信逻辑，工作量大）；JxBrowser 商业组件（收费）。

## 技术基线

| 项 | 值 | 说明 |
|---|---|---|
| IntelliJ Platform | 2024.2+（since-build = 242）；**构建类型 IU（Ultimate）** | JCEF 仅随商业 IDE 分发（IC Community 不含 JCEF，Task 1 已取证）；插件经 `<depends>com.intellij.modules.jcef</depends>` 自动只在含 JCEF 的 IDE（Ultimate / PyCharm Professional / WebStorm / GoLand 等）上加载 |
| until-build | `252.*` | 显式声明，滚动窗口 2 个大版本；发版时随 Plugin Verifier 结果更新 |
| Java | 21（toolchain） | 与 2024.2+ IDE 一致 |
| Gradle | 9.7.1（wrapper 固定版本，用户指定） | IPGP 2.x 要求 Gradle 9.0+ |
| Gradle Plugin | `org.jetbrains.intellij.platform` 2.18.1 | IPGP 2.x 最新；插件 ID 与 1.x 的 `org.jetbrains.intellij` 不同 |
| 浏览器 | JBCefBrowser（JCEF） | IDEA 2020.2+ 提供；2024.2+ 中 API 稳定 |

## 插件架构

```
IntelliJ IDE
   └── WebApp ToolWindow（右侧停靠，可浮动/拖动）
         └── WebAppPanel（工具窗口内容，实现 Disposable）
               ├── JBCefBrowser（JCEF，显式 cache_path）
               │     └── WebApp 页面（登录 / 会话 / SSE / Chat / Agent Trace 由页面负责）
               └── WebAppBridge（JBCefJSQuery 双向通道）
                     ├── openFile(path)          [v1 实现]
                     ├── getCurrentFile()        [v1 实现]
                     ├── refresh()               [v1 实现]
                     ├── openDirectory(path)     [v1 仅接口，返回未实现]
                     └── getProjectRoot()        [v1 仅接口，返回未实现]
```

### 组件清单

| 组件 | 文件 | 职责 |
|---|---|---|
| 工具窗口工厂 | `toolwindow/WebAppToolWindowFactory.java` | 创建工具窗口，注册到 plugin.xml（id=`webapp.toolwindow`，anchor=right） |
| 内容面板 | `toolwindow/WebAppPanel.java` | 组装 JBCefBrowser + 状态覆盖层 + 标题栏 Action；持有 Disposable 生命周期 |
| 状态覆盖层 | `toolwindow/LoadStateOverlay.java` | Loading / NetworkError / WebAppError / AuthError 的 Swing 覆盖层 + [重新加载] 按钮 |
| 桥接层 | `bridge/WebAppBridge.java` | JBCefJSQuery 注册/注销；JS→Java 消息路由 |
| 设置状态 | `settings/WebAppSettingsState.java` | PersistentStateComponent：serverUrl、path、autoLoadOnStartup |
| 设置页 | `settings/WebAppSettingsConfigurable.java` | Settings → Tools → WebApp；URL 校验即时反馈；Test Connection |
| URL 校验 | `util/UrlValidator.java` | 白名单 scheme 校验（http/https），拒绝 javascript:/file:/data:/chrome:/空白 |
| JCEF 探测 | `util/JcefSupport.java` | `JBCefBrowser.isAvailable()` 检测与降级引导 |

## 详细设计

### 1. JCEF 依赖与降级（硬伤 #1 修复）

- `plugin.xml` 显式声明：`<depends>com.intellij.modules.jcef</depends>`。
- `JcefSupport` 在工具窗口创建时检测 `JBCefBrowser.isAvailable()`：
  - 可用 → 正常创建 JBCefBrowser 并加载 URL；
  - 不可用 → 显示 Swing 降级面板（不崩溃）：说明原因 + [用系统浏览器打开] 按钮（`Desktop.browse`）+ JCEF 启用指引文案。
- 降级面板同样提供重新检测入口（用户启用 JCEF 后点 [重试]）。

### 2. URL 配置与安全（硬伤 #2 修复 + 评审二 §6/§12）

- 设置项两段式：
  - **Server URL**（默认 `http://localhost:5173`）
  - **WebApp Path**（默认 `web-apps/Tf5qMSSgDiqHZkdg`）
  - 最终 URL = `serverUrl 去尾斜杠 + "/" + path 去首斜杠`。
- **插件不参与 Token / 认证**：Token 由 WebApp 页面自行管理（localStorage / Cookie / Refresh Token 由 WebApp 决定）；插件只负责打开 URL、刷新、销毁。切换账号/租户的 token 变化由页面路由自行处理。
- `UrlValidator` 校验规则：
  - 仅允许 scheme ∈ {`http`, `https`}；
  - 拒绝 `javascript:`、`file:`、`data:`、`chrome:`、`about:` 及含空白、控制字符的输入；
  - 校验失败 → 设置页红字提示 + 保存按钮禁用；`Test Connection` 用 `HttpURLConnection`（超时 3s）探测可达性。

### 3. 登录态持久化（硬伤 #3 修复 + 评审二 §2）

- 创建 `JBCefBrowser` 时显式指定持久化目录：`PathManager.getSystemDir()/webapp-plugin/cache`，并设置 `CefSettings.cache_path` 指向该目录。不依赖 JCEF 默认缓存目录（IDE 重启可能清空）。
- 边界声明（写入 README 与代码注释）：
  - sessionStorage：不保证跨 IDE 重启保留；
  - localStorage：可持久化，但视为 **WebApp 浏览器存储机制**，不是插件级持久化保证；
  - OAuth/JWT 刷新、HttpOnly/Secure/SameSite Cookie 策略：WebApp 侧职责，插件不干预。

### 4. WebAppBridge（评审一 §4 + 评审二 §7/§8）

- 基于 `JBCefJSQuery`（JS→Java 通道）实现，页面端通过 `window.webAppBridge`（注入的 JS 对象）发起调用。
- v1 实现的方法（真实功能）：
  - `openFile(path)`：`FileEditorManager` 打开文件并定位到编辑器；
  - `getCurrentFile()`：返回当前活动编辑器文件路径（JSON）；
  - `refresh()`：JCEF 重新加载当前 URL。
- v1 仅定义签名、返回"未实现"的方法：
  - `openDirectory(path)`、`getProjectRoot()`（接口就位，后续迭代补齐）。
- 消息协议：`{action: string, payload?: object}` → `{ok: boolean, data?: any, error?: string}`。
- 安全：Bridge 只响应白名单 action；未知 action 返回错误，不执行。

### 5. 生命周期（评审二 §9）

- 显式 Disposable 链：`Project → WebAppToolWindowFactory(Disposable) → WebAppPanel → (JBCefBrowser + WebAppBridge)`。
- `WebAppPanel.dispose()` 顺序：
  1. 注销 JBCefJSQuery / CefMessageRouter 监听；
  2. 释放 JBCefBrowser（`browser.dispose()`）；
  3. 从项目 Disposable 父节点解绑。
- 防止：Chromium 进程残留、ToolWindow 重建后重复监听、多 Project 并发创建多个 JCEF。

### 6. 加载状态 UI（评审二 §10 + 评审一 §5）

- 状态机：`Loading → Connecting → Loaded | NetworkError | WebAppError | AuthError`（经 JCEF 加载事件 + URL 变化判定）。
- 非 Loaded 状态显示 Swing 覆盖层（CardLayout 切换）：
  - Loading/Connecting：居中进度提示"正在连接服务器…"；
  - NetworkError：显示目标 URL + [重新加载] 按钮；
  - WebAppError / AuthError：显示原因 + [重新加载]。
- 工具窗口标题栏注册刷新 Action（`setTitleActions`），白屏/失败时用户始终可操作。

### 7. 设置项（评审二 §11 收敛）

- 第一版仅三项：
  - **Server URL**（文本框，带校验）
  - **WebApp Path**（文本框，带校验）
  - **启动时自动加载**（勾选，默认开；指打开工具窗口时自动加载 URL）
- 附加：[Test Connection] 按钮（探测 Server URL 可达性）。
- 设置存储：`PersistentStateComponent`（`WebAppSettingsState`），无敏感信息（Token 不入插件存储）。

### 8. 工程结构（评审二 §16）

```
idea-webapp-plugin/
├── build.gradle.kts
├── settings.gradle.kts
├── gradle.properties
├── gradlew / gradlew.bat（wrapper 固定 Gradle 9.7.1）
├── README.md
└── src/
    ├── main/
    │   ├── java/com/webapp/plugin/
    │   │   ├── toolwindow/  WebAppToolWindowFactory.java, WebAppPanel.java, LoadStateOverlay.java
    │   │   ├── bridge/      WebAppBridge.java
    │   │   ├── settings/    WebAppSettingsState.java, WebAppSettingsConfigurable.java
    │   │   └── util/        UrlValidator.java, JcefSupport.java
    │   └── resources/META-INF/plugin.xml
    └── test/java/com/webapp/plugin/  UrlValidatorTest, WebAppSettingsStateTest, BridgeProtocolTest
```

### 9. plugin.xml 关键声明

- `<idea-plugin>`：name `webapp-session-window`、id `com.webapp.session-window`、since-build `242`、until-build `252.*`。
- `<depends>com.intellij.modules.platform</depends>` + `<depends>com.intellij.modules.jcef</depends>`。
- `<extension point="com.intellij.toolWindow">`：id `webapp.toolwindow`、anchor `right`、factoryClass `WebAppToolWindowFactory`。
- `<extension point="com.intellij.applicationConfigurable">`：`WebAppSettingsConfigurable`。

### 10. 构建与调试

- `./gradlew buildPlugin` 打包；`./gradlew runIde` 启动调试 IDE 实例（JBR 自动下载）。
- 本机环境：Java 21（`D:\Program\Java21`），Gradle wrapper 首次运行自动下载（用户指定 9.7.1）。

## 错误处理与边界情况

| 场景 | 行为 |
|---|---|
| 后端/前端服务未启动（URL 不可达） | 覆盖层显示 NetworkError + [重新加载] |
| 登录过期 | 页面自行跳转登录页，用户重新登录 |
| JCEF 不可用 | Swing 降级面板 + 系统浏览器打开 + 重试 |
| URL 配置非法 | 设置页红字提示，保存禁用 |
| Bridge 收到未知 action | 返回错误，不执行 |
| 关闭 Project | Disposable 链释放浏览器，无残留 |
| Remote Development / Gateway | 第一版不支持；URL 为配置项，不假定 localhost 恒等于 IDE 所在机器 |

## 测试策略

- **单元测试**（JUnit 5）：
  - `UrlValidatorTest`：http/https 通过；javascript:/file:/data:/chrome:/空白/控制字符拒绝；
  - `WebAppSettingsStateTest`：序列化往返、默认值、URL 拼接逻辑；
  - `BridgeProtocolTest`：消息解析、白名单 action、未知 action 拒绝。
- **集成测试**：
  - JCEF 加载超时（`WaitFor` 条件断言）→ 进入 NetworkError 状态；
  - 加载成功 → Loaded 状态（runIde 下手工验收为主）。
- **兼容性**：Plugin Verifier 针对 IDEA / PyCharm / WebStorm（2024.2+）验证，结果驱动 until-build 更新。
- **手动验收清单**：
  1. `runIde` 启动 → 右侧出现 WebApp 工具窗口；
  2. 页面加载 → 登录 → 发送消息 → SSE 流式回复正常；
  3. 重启 IDE → 登录态保持（无需重新登录）；
  4. 停掉 5173 服务 → 覆盖层显示连接失败 → [重新加载] 恢复；
  5. 设置页改 URL → 校验反馈正确 → 保存后工具窗口加载新 URL。

## 评审意见采纳对照

| 评审项 | 决策 |
|---|---|
| JCEF 非默认可用（硬伤 #1） | ✅ plugin.xml 声明 jcef 依赖 + isAvailable() 降级 UI |
| URL 中 TOKEN 硬编码（硬伤 #2） | ✅ URL 配置化，token 完全交给页面 |
| 登录态持久化描述错误（硬伤 #3） | ✅ 显式 cache_path 到插件目录 |
| JS→Java 双向通信（中 #4） | ✅ WebAppBridge + JBCefJSQuery，v1 最小子集 |
| 刷新按钮位置（中 #5） | ✅ 标题栏 Action + 覆盖层按钮 |
| URL 校验（中 #6） | ✅ UrlValidator 白名单 |
| 工具窗口位置 | ✅ 右侧 |
| until-build 不限（评二） | ✅ 显式 `252.*` + Plugin Verifier |
| 版本矩阵矛盾（评二 §4） | ✅ 2024.2+ / Java 21 / IPGP 2.x（2.18.1）/ Gradle 9.7.1 |
| Base URL + Path 配置（评二 §6） | ✅ 两段式配置 |
| 生命周期 Disposable（评二 §9） | ✅ 显式 Disposable 链 |
| 加载状态 UI（评二 §10） | ✅ 状态机 + 覆盖层 |
| 设置项收敛（评二 §11） | ✅ 三项 + Test Connection |
| 不混合文件系统能力（评二 §17） | ✅ 插件核心不含文件系统操作 |
| Remote Development（评二 §13） | ✅ 第一版不支持，架构不锁死 |

## 待办/后续迭代（不在本版范围）

- Bridge 扩展：openDirectory、getProjectRoot 的完整实现；
- Agent 回复中的"打开文件/定位行"按钮（依赖 Bridge 扩展）；
- 多 WebApp token 管理（若页面支持多实例）；
- 插件签名与 Marketplace 分发（内部使用阶段不需要）。
