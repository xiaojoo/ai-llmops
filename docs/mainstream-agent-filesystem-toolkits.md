# 主流 Agent 产品/框架的"文件系统工具包"实现调研

> 调研方法：基于**一手来源**（官方文档、官方源码仓库、规范/man page），每条关键论断附来源 URL。
> 三个分析维度：**接线**（workspace 根目录如何配置/挂载）、**加固**（路径穿越、符号链接、TOCTOU、大小/类型限制、删除保护）、**隔离**（按用户/会话分目录、OS 级沙箱、容器、人工审批）。

<!-- 目录占位：写完填充 -->

## 0. 结论速览（TL;DR）

<!-- 写完填充 -->

---

## 1. LangChain FileManagementToolkit

<!-- 待子代理 A 结果 -->

---

## 2. OpenAI Code Interpreter / Advanced Data Analysis

<!-- 待子代理 A 结果 -->

---

## 3. Anthropic Claude Code 与官方 filesystem MCP server

<!-- 待子代理 B 结果 -->

---

## 4. MCP filesystem 参考服务器（modelcontextprotocol/servers）

<!-- 待子代理 C 结果 -->

---

## 5. OpenHands（原 OpenDevin）

<!-- 待子代理 D 结果 -->

---

## 6. 国内常见平台：Dify / Coze / n8n / FastGPT

<!-- 待子代理 D 结果 -->

---

## 7. 云端 code-interpreter 沙箱：E2B / Daytona

<!-- 待子代理 C 结果 -->

---

## 8. 底层加固技术与已知漏洞模式

### 8.1 openat/dirfd 与 TOCTOU

- **原理**：`openat(2)` 以目录文件描述符 `dirfd` 为锚点解析相对路径（不再依赖进程当前工作目录），路径解析从该目录开始；配合 `O_NOFOLLOW`（拒绝解析末尾符号链接）、`O_CLOEXEC`（exec 时自动关闭 fd），并可借助 `openat2(2)` 的 `RESOLVE_BENEATH` / `RESOLVE_NO_SYMLINKS` 把解析限制在锚点目录之下。
- **解决的问题**：消除"先 lstat/access 检查、再 open 使用"之间的 check-then-use 竞态（TOCTOU）——检查与打开是原子的一次路径解析，攻击者无法在两步之间把路径组件替换成指向敏感位置的符号链接。
- **局限**：仅靠 openat 不能防御路径中间每一级组件的替换（需要 `RESOLVE_BENEATH` 级别的逐级约束）；它保护的是路径解析而非文件内容本身。
- 来源：https://man7.org/linux/man-pages/man2/openat.2.html

### 8.2 符号链接与路径穿越（CWE）

- **CWE-59 符号链接不当解析**：程序基于路径中的符号链接做决策但未正确解析，导致实际访问的文件与预期不同（攻击者预置链接指向敏感目标）；典型场景是 `/tmp` 下的不可信文件名。https://cwe.mitre.org/data/definitions/59.html
- **CWE-367 TOCTOU**：资源在"检查"与"使用"之间被外部改变（典型即符号链接被替换），使检查结果失效。https://cwe.mitre.org/data/definitions/367.html

### 8.3 Landlock / seccomp / gVisor / Firecracker / chroot / 低权限用户

| 技术 | 原理 | 解决的威胁 | 局限 | 来源 |
|---|---|---|---|---|
| **Landlock** | 非特权 LSM（Linux 5.13+），进程用 `landlock_create_ruleset(2)` 等以文件层级（如"某目录只读、其外不可写"）自我限制访问，无需 root | agent 运行期文件访问越权 | 需与 seccomp/容器组合构成纵深防御 | https://docs.kernel.org/userspace-api/landlock.html |
| **seccomp / seccomp-bpf** | 通过 `prctl(PR_SET_SECCOMP)` / `seccomp(2)` 安装 BPF 过滤器，按系统调用号与参数白/黑名单拦截 | 即使进程被攻破也不能调用危险 syscall（execve、直接 open 敏感路径） | 只过滤系统调用层面，无法理解路径字符串语义，需与 Landlock 等配合 | https://man7.org/linux/man-pages/man2/seccomp.2.html |
| **gVisor** | `runsc` 用户态内核拦截 guest 应用全部系统调用并按宿主安全策略重新实现 | 宿主内核攻击面暴露 | 性能开销与部分兼容性问题 | https://gvisor.dev/docs/architecture_guide/ |
| **Firecracker** | 基于 KVM 的轻量 microVM（最小设备模型、毫秒级启动），每租户独立 VM 边界；AWS Lambda/Fargate 使用 | 多租户强隔离 | 仍是完整 VM 边界，需镜像与启动管理 | https://firecracker-microvm.github.io/ |
| **chroot(2)** | 把进程根目录改为指定目录 | 仅便利性/最小隔离 | man7 明确警示：**不是安全边界**，root 可轻易逃逸（保留 fd、`chroot(".")` 技巧） | https://man7.org/linux/man-pages/man2/chroot.2.html |
| **低权限用户 / user namespace / rootless 容器** | 守护进程与容器以非 root 运行（Docker `USER` 指令）；rootless 让整个守护进程以非特权用户 + user namespace 运行 | 缩小提权后的影响面 | 依赖内核 user namespace 支持，部分挂载/网络/资源限制功能受限 | https://docs.docker.com/engine/security/rootless/ ；https://docs.docker.com/engine/install/linux-postinstall/#manage-docker-as-a-non-root-user |

### 8.4 zip-slip 与 LLM 生成路径漏洞模式

- **zip-slip**：解压工具未校验压缩包 entry 的文件名，entry 含 `../` 或绝对路径时解压路径拼接后落到目标目录之外，可覆盖任意可写文件；Snyk Security Research 于 2018 年首次系统披露，影响数千个库。同类模式：tar 解压路径穿越、压缩包内**符号链接 entry**（解压时沿链接写出目标目录之外）。来源：https://snyk.io/research/zip-slip-vulnerability （现已跳转至 https://security.snyk.io/research/zip-slip-vulnerability ）
- **LLM 生成路径风险（对 agent 工具的意义）**：模型生成的路径/文件名或工具参数可能被**提示注入**操纵，使文件工具把内容写到敏感位置（如 `~/.ssh/authorized_keys`、`~/.bashrc`）或删除任意文件——对应 OWASP LLM Top 10 的 **LLM01 Prompt Injection** 与 **LLM06 Excessive Agency**（过度授权/工具滥用）；缓解方向即 8.1 的锚点 + 拒绝 `..` + 最小工具权限。来源：https://llmtop10.com/ ；官方仓库 https://github.com/GenAI-Security-Project/GenAI-LLM-Top10

---

## 9. 模式总结：接线 / 加固 / 隔离 checklist

<!-- 写完填充 -->

---

## 10. 对本仓库（ai-code-llmops）的启示

> 仓库事实（已核实，见文件内链接）：
> - 内置文件工具在 API 进程内直接执行（FastAPI + LangChain `@tool`），无子进程/容器沙箱。
> - 根目录：`WORKSPACE_ROOT = os.environ.get("FILESYSTEM_WORKSPACE", "/workspace")`（`internal/core/tools/builtin_tools/entities/filesystem_entity.py`）；当前 `FILESYSTEM_WORKSPACE` 未配置，compose 中也没有对应挂载。
> - 全部操作经 `safe_resolve()`（`internal/core/tools/builtin_tools/utils/filesystem_helper.py`）：`os.path.realpath` 规范化 + 前缀校验（`target != workspace and not target.startswith(workspace + os.sep)`），越界抛 `FilesystemError`。
> - 已有限制：读文件单次上限 `MAX_READ_CHARS = 50_000`；`delete_path` 禁止删除工作区根目录本身、非空目录需 `recursive=True`；`write_file` 自动建父目录。
> - 未做：写入大小/配额、审计日志、回收站、按租户/会话分目录、OS 级沙箱。
> - 已有对象存储：`internal/service/minio_service.py`（MinioService，走 mall-third-party HTTP 上传接口）、`internal/service/cos_service.py`（CosService，COS/MinIO 可切换）。

<!-- 写完填充 -->
