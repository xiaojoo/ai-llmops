# 设计：让 VS Code / IDEA 插件读取「本地工作区」的方案

> 状态：设计方案（未实施）
> 目标：在**远端部署**（后端在独立服务器，与 IDE 不同机）下，让 `vscode-plugin` 与 `idea-plugin` 两个插件的 Agent 能读取**用户本地打开的工作区**。
> 硬约束：**`/web_apps/{token}/chat` 接口不改**（仍只发 `project_root` + `file_ids`），沿用 Web 同一套接口。

---

## 1. 根因回顾（为什么现在读到的是服务器工作区）

Agent（LLM + `fs_*`/`shell_run` 工具）运行在**远端 FastAPI 进程**内，它的「工作区」是**服务器上 `project_root` 指向的那个目录**。

- 插件把**本地**路径（如 `C:\...\test`）作为 `project_root` 传给后端。
- 后端 `internal/core/tools/workspace_tools.py:192` 的 `build_workspace_tools(project_root)` 第一步就是：
  ```python
  workspace = Path(project_root).resolve()
  if not workspace.is_dir():
      return []        # 服务器上不存在该路径 → 返回空
  ```
- 返回空后，`chat_runner.run` 不再注入「按本地工作区绑定」的工具；Agent 退而使用**应用配置里自带的 filesystem 工具包**，其绑定的是服务器默认工作区 `storage/agent-workspace`（`internal/core/tools/builtin_tools/providers/filesystem/security/policy.py:83` `default_workspace()`）。
- 因此它列出了 `index.html / styles.css / tech_website.html / tech_website_design.md`——正好都在 `H:\ai-code-llmops\storage\agent-workspace`。

**核心事实：远端进程无法通过一个路径字符串访问客户端的本地磁盘。** 本地开发一切正常，只是那时后端与 IDE 同机、路径真实存在。

### 现有链路里已经能「读到本地」的两处（但都不是 Agent 的工具工作区）

| 能力 | 客户端数据源 | 用途 |
|---|---|---|
| `listWorkspaces` | `vscode.workspace.workspaceFolders` / IDEA `ProjectManager` | 显示工作区下拉、选 `project_root` |
| `listProjectFiles` | `vscode.workspace.findFiles` / IDEA 目录扫描 | `@` 提及文件，发送时**逐文件上传** |

这两处证明：**插件的确能枚举本地文件**，只是 Agent 的文件/命令工具不在客户端执行。

---

## 2. 约束与判定

- 不改 `chat` 接口（`project_root`、`mode`、`file_ids` 字段已存在，语义保留）。
- 两个插件行为一致。
- 远端场景下，唯一能让服务器 Agent「看到本地文件」的方法：**把本地文件变成服务器上真实存在的目录**，或**把工具执行搬到本地**。

两种架构对比如下，详细设计见 §3 / §4。

| 维度 | 方案 A：同步到服务器 | 方案 B：插件本地执行工具 |
|---|---|---|
| 谁读/写文件 | 服务器上的同步副本 | 插件用真实本地路径 |
| `chat` 接口 | **不改** | 要新增「工具调用」双向通道，改动 SSE 约定 |
| 新增后端 | 1 个批量上传/解包工作区的**附加**端点 | 大改 Agent 工具分发 + SSE 消息类型 |
| 写回本地 | 纯读可行；写回需另做同步回传（阶段 2） | 天然可读可写 |
| 改动体量 | 小 | 大 |
| 与 Web 前端一致性 | 复用同一上传通道思路 | 与 Web 前端（后端持有文件）行为不一致 |

---

## 3. 方案 A：同步本地工作区到服务器（推荐）

### 3.1 核心思想

插件在发送 agent 消息前，把当前本地工作区**同步**成服务器上一个真实目录，拿到该目录在服务器的**绝对路径**，然后把它当作 `project_root` 传进现有 `chat` 接口。后端 `build_workspace_tools(project_root)` 在服务器上能 `is_dir()` 通过，于是注入「绑定该目录」的 `fs_*` + `shell_run` 工具。

请求方向大致如下：

```
[插件] 枚举本地目录 → 打包(哈希去重) → 上传 → 服务器解包到 storage/tmp/workspaces/{account}/{hash}/
        ↓ 返回服务器绝对路径 workspace_path
[插件] 发送 chat：{ mode:"agent", project_root: workspace_path, file_ids:[...] }   ← 现有接口，零改动
[后端] chat_runner.run:  build_workspace_tools(workspace_path) → is_dir 成立 → 注入工具
```

### 3.2 新增端点（附加，不破坏现有接口）

建议名：`POST /web_apps/workspace`（或挂在 `upload-files` 下 `POST /upload-files/workspace`）。

- 请求：`multipart/form-data`，字段 `file`（单个 `.zip`/`.tar.gz` 包），可选字段 `workspace_hash`（内容哈希，用于去重）、`name`。
- 鉴权：`Authorization: Bearer <token>`，归属当前账号。
- 行为：
  1. 校验包格式与大小上限（防止解包炸弹——限制压缩比、总解包体积、文件数、单文件大小）。
  2. 解包到受控根下：`{settings.project_root}/storage/tmp/workspaces/{account_id}/{workspace_hash}/`。
  3. 用 `PathGuard`/目录穿越校验，确保解包不逃逸该根（复用 `filesystem/security/path_guard.py` 的思路）。
  4. 已存在且哈希匹配 → 直接返回现有路径（幂等）。
- 响应（沿用 `{code,message,data}` 包壳）：
  ```json
  {
    "code": "success",
    "data": {
      "workspace_path": "/data/app/storage/tmp/workspaces/<account>/<hash>",
      "workspace_hash": "<hash>",
      "file_count": 123,
      "total_bytes": 456789
    }
  }
  ```

> 说明：这里**不是**走现有 `/upload-files/file`——那个是存对象存储（COS/MinIO）并按 `id` 引用，**不能**生成一个 `fs_*` 工具可浏览的目录树。所以需要一个「解包成目录」的附加端点。它只是**新增**，不改任何现有端点。

### 3.3 后端落地改动点

| 文件 | 改动 |
|---|---|
| `internal/handler/`（新增 workspace handler） | 处理上传、解包、哈希去重、返回服务器路径；含解包安全校验 |
| `internal/service/web_app_service.py` | `prepare_web_app_chat` 中 `project_root` 校验可改为「必须在受控工作区根下」——可选加固，防客户端传任意服务器路径 |
| `internal/core/tools/workspace_tools.py` | **零改动**（`project_root` 语义不变，只是值现在真实存在于服务器） |
| 清理策略 | `storage/tmp/workspaces/` 按账号+哈希做 TTL/LRU 清理（如 7 天未用即删）；解包时校验总字节 |

### 3.4 插件侧改动点

**VS Code（`vscode-plugin/src/`）**
- `api/client.ts`：新增 `syncWorkspace(zipBuffer, hash, authToken): {workspace_path,...}`，调用新端点。
- `bridge.ts` `handleSend`：在 `mode==='agent'` 分支，先把 `projectRoot` 对应目录打包/上传，拿到服务器 `workspace_path`，再替换待发送的 `project_root`。可缓存 `hash→workspace_path`（局部缓存 + `workspace_hash` 去重，避免每次重传）。
- `scripts/`：本地打包逻辑（选 `archiver` 或系统 `tar`）；按 `.gitignore`/`.idea/.git/venv/node_modules/dist` 等排除，控制体积。
- 聊天对象：`AgentChatEmbed.vue` 无需改前端，仍传 `projectRoot`（插件内在替换）。

**IDEA（`idea-plugin/src/main/java/com/webapp/plugin/`）**
- `api/WebAppApiClient.java`：新增 `syncWorkspace(...)`，逻辑与 VS Code 侧一致。
- `bridge/WebAppBridge.java` `handleSend`（约 L781 `projectRoot` 处）：agent 模式先同步再替换 `project_root`。
- 本地打包含提示（调用 `Archive` 或系统 `tar`），排除规则同上。

### 3.5 边界与注意

- **必须切到 Agent 模式**：`chat_runner.py:226` 只在 `mode==='agent' and project_root` 时注入工作区工具。默认 `composerMode='chat'`（`AgentChatEmbed.vue:83`），所以用户须用 Agent 模式（前端已有「检测到操作意图提示切换」`ensureModeBeforeSend`）。若保持 Chat，Agent 仍走应用自带 filesystem（服务器默认目录）。
- **写入**：Agent 的修改发生在服务器副本上，**不会**自动反映到本地。纯「读/分析/生成」场景可用；若需 Agent 改本地文件，见阶段 2（同步回传）。
- **体积**：大型仓库全量上传开销大。建议：按需、按目录、哈希去重 + 排除构建产物；或仅上传 `project_root` 内 `listProjectFiles` 能列出的那批（受 `MAX_MENTION_FILES` 约束）。
- **权限/安全**：不要让客户端传任意服务器路径当 `project_root`；由服务器在受控根下生成并返回路径，客户端只透传。

### 3.6 阶段 2（可选）：写回本地

Agent 在服务器副本上改动后，把改动文件列表/TTL 快照传回插件，插件按相对路径写回本地。需要新增「拉取工作区差异」端点与插件端冲突处理。此阶段复杂度较高，建议先只做「读」。

---

## 4. 方案 B：工具在插件本地执行

### 4.1 核心思想

让 `fs_*`/`shell_run` 工具**在插件进程里对真实本地路径执行**，后端只负责 LLM 推理。聊天接口本身字段不变，但需要在「工具调用」与 SSE 事件上建立一条双向通道：

```
LLM 决定调用 fs_read → 后端产出「待本地执行工具调用」事件 → 插件收到 → 本地执行 →
    插件把结果回传 → 后端把 observation 交给 LLM → 继续推理
```

### 4.2 改动点

- **SSE 事件类型**：新增一类「本地工具调用」事件（携带 `tool_name`/`args`/`tool_call_id`），替换/旁路现有的后端工具执行。
- **回传通道**：新增一个接口或复用 `send`/`choice` 的调用风格，插件把工具执行结果（含 stdout 等）回传后端。
- **插件本地执行器**：VS Code 用 Node `fs`/`child_process`；IDEA 用 `java.nio`/`ProcessBuilder`。需复用后端相同的白名单/路径守卫逻辑（`workspace_tools.py` 的 `PathGuard`、`SHELL_ALLOWLIST`），否则安全语义不一致。
- `chat_runner.py`：工具分发处改为「本地工具」透传，不再在服务器注入 `fs_*`。

### 4.3 代价

- 改动 Agent 工具分发架构 + SSE 消息协议，是**结构性**改动，风险高于方案 A。
- 需要把后端安全逻辑（白名单、路径守卫、回收站、审计）在两端各实现一遍保持一致。
- 与 Web 前端行为分裂：Web 端 Agent 在服务器持文件，插件端在本地持文件，代码差异大、测试面广。

### 4.4 优点

- 天然**可读可写**本地真实路径，无需上传/同步副本，最符合「IDE 智能体」直觉。
- 无需服务器磁盘同步与清理。

---

## 5. 结论与建议

- **推荐方案 A**：改动最小、完全满足「不改 `chat` 接口、沿用 Web 同一套接口」的约束；仅新增一个「工作区解包」附加端点。纯读场景即可收敛本次问题。
- 方案 B 在「需要 Agent 直接改本地文件」且能接受较大协议改动时再考虑；若未来要「本地执行」是长期方向，建议单独立项。

## 6. 待确认问题

1. 本次只做**读取/分析**，还是也要**Agent 写回本地文件**？（决定是否做阶段 2）
2. 工作区同步的**体积上限**与**排除规则**（`.git`/`.idea`/`venv`/`node_modules`/`dist`...）？
3. 同步副本的**清理策略**（TTL 建议值）？
4. 是否接受「解包成目录」这一**新增**端点（不影响任何现有接口）？
