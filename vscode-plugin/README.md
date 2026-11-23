# WebApp Chat（VS Code 扩展）

把 WebApp AI 会话窗口嵌入 VS Code 侧边栏。是 IDEA 插件
`webapp-session-window`（`idea-plugin`）的 VS Code 移植版：
**后端 FastAPI 接口与前端 Vue 界面（样式）100% 复用，零改动**。

> 移植方案详见仓库根目录 `docs/vscode-plugin-migration.md`；
> IDEA 插件说明详见 `../idea-plugin/README.md`。

## 功能（与 IDEA 插件对齐）

- 账号密码登录，token 存 `SecretStorage`，重启保持登录
- 会话列表 / 切换 / 新建 / 恢复上次会话
- SSE 流式对话（增量渲染、耗时与 token 统计、60s 超时保护、ask_user 等待放行）
- ask_user 选项选择 / 计划确认（confirm / replan / 跳过）
- 加号上传附件；输入框 `@` 提及项目文件并随消息上传
- 点赞 / 点踩反馈
- 会话短期记忆轮数设置
- 多 App 切换
- 消息内文件路径点击打开（openFile）

v1 未实现：语音转文字（麦克风按钮已隐藏）。

## 目录结构

```
vscode-plugin/
├── src/
│   ├── extension.ts      # 扩展入口：注册 WebviewViewProvider + 命令
│   ├── webview.ts        # WebviewViewProvider：加载产物 + JS↔宿主桥
│   ├── bridge.ts         # action 分发（对应 Java WebAppBridge）
│   ├── protocol.ts       # 纯逻辑：协议解析/映射/事件构建（可单测）
│   ├── state.ts          # 持久化（对应 Java WebAppSettingsState）
│   └── api/
│       ├── client.ts     # 后端 API 客户端（对应 Java WebAppApiClient）
│       └── sse.ts        # SSE 事件解析（对应 Java SseEventParser）
├── scripts/
│   ├── build-webview.js  # 前端单文件产物 → dist/media/index.html（注入 CSP + 桥脚本）
│   └── (run-tests)       # 测试入口见 package.json scripts
├── tests/                # node:test 单测（纯逻辑层）
└── media/webapp.svg      # 侧边栏图标
```

## 构建

前置：前端单文件产物（IDEA 插件同款构建）：

```bash
cd ../ai-llmops-web
npx vite build --config vite.agent-chat.config.ts
```

然后：

```bash
cd ../vscode-plugin
npm install
npm run build:webview   # 注入 CSP + vscode 桥脚本 → dist/media/index.html
npm run compile         # tsc → out/
npm test                # 单测（node:test，34 个用例）
```

## 运行（F5 调试）

1. 用 VS Code 打开 `vscode-plugin/` 目录
2. 按 `F5`（配置见 `.vscode/launch.json`，会打开 Extension Development Host）
3. 点击左侧活动栏的 WebApp 图标，或命令面板执行 `WebApp: 打开会话窗口`

后端地址在设置里配置：`webapp-chat.backendUrl`（默认 `http://localhost:5000`）。

## 打包 vsix

```bash
npm install -D @vscode/vsce
npm run package          # 产出 webapp-chat-0.1.0.vsix（项目根目录）
```

## 安装 vsix（正式使用）

```bash
code --install-extension webapp-chat-0.1.0.vsix
```

或 VS Code 菜单 **Extensions → ⋯ → Install from VSIX…** 选择该文件。

安装后：左侧活动栏出现 **WebApp** 图标，点击打开侧边栏；后端地址在
设置里配置 `webapp-chat.backendUrl`（默认 `http://localhost:5000`）与
`webapp-chat.defaultWebAppToken`。

## 把视图放到右侧边栏（Secondary Side Bar）

VS Code 默认把活动栏容器放在左侧，但**视图本身可以移到右侧辅助边栏**（像 IDEA 插件的右侧工具窗口）。
两种方式（任选其一，VS Code 会记住位置）：

1. 命令面板（`Ctrl+Shift+P`）执行 **`WebApp: 移到右侧边栏`**（扩展内置命令）
2. 手动：右键 WebApp 视图标题 → **Move View into Secondary Side Bar**，或把标题直接拖到右侧

> 说明：VS Code 没有 API 能强制指定视图初始位置，移动视图只能由用户操作（拖拽/右键）。
> 首次移动后位置会被记住；"WebApp: 移到右侧边栏"命令会先尝试调用内置命令，失败时提示手动操作。

## 桥协议（与 IDEA 插件一致）

- JS → 宿主：`window.agentChatHost({ request, onSuccess, onFailure })`
  - `request` = `JSON.stringify({ action, payload })`；`onSuccess` 收到 `{"ok":...}` JSON 字符串
- 宿主 → JS：`window.__agentChatEvent(JSON.stringify({ type, data }))`

全部 action / 事件名与 Java 侧逐字一致，前端 `AgentChatEmbed.vue` 无需任何改动。

## 已知差异

| 项 | IDEA 插件 | VS Code 版 |
|---|---|---|
| 语音输入 | Java 侧 javax.sound 录音 | v1 未实现（按钮隐藏） |
| 设置面板 | IntelliJ Settings | VS Code 原生设置（`webapp-chat.*`） |
| token 存储 | 明文 XML 持久化 | SecretStorage（更安全） |
| @ 提及文件 | Java 目录扫描 | `workspace.findFiles` |
