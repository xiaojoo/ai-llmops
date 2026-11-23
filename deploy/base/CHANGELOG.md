# deploy/base 变更记录（CHANGELOG）

部署配置每次改动在此登记：**现象 → 根因 → 改动 → 服务器操作 → 验证**。

---

## 2026-09-03

### 1. 修复 `.env` CRLF 换行符 → `source .env` 报 `$'\r': command not found`

- **现象**：服务器上执行 `./deploy.sh up`，脚本 `load_env()` 里 `source .env` 时报错：
  ```
  /data/llmops-api/base/.env: line 12: $'\r': command not found
  ```
- **根因**：`deploy/base/.env.example` 在 Windows 检出时被 git `core.autocrlf=true` 转成了
  CRLF（仓库内存储为 LF，工作区为 CRLF）。服务器上 `cp .env.example .env` 后，`.env` 每行
  末尾都残留 `\r`；`.env` 第 12 行为空行，只剩一个 `\r`，bash 把 `\r` 当命令执行而报错。
  （另注意：`deploy.sh` 是 bash 脚本，用 `sh deploy.sh up` 执行会报
  `Bad substitution` / `Syntax error: "("`，须用 `./deploy.sh` 或 `bash deploy.sh`。）
- **改动（仓库）**：
  - `deploy/base/.env.example`：由 CRLF 转为 LF（git 中仍为 LF，与存储一致）。
  - 新增根目录 `.gitattributes`：`*.sh` / `*.env.example` / `deploy.env` 强制 `eol=lf`，
    防止今后 Windows 检出/复制再次引入 CRLF。
- **服务器修复命令**：
  ```bash
  cd /data/llmops-api/base
  for f in .env .env.example deploy.sh docker-compose.yaml; do
    [ -f "$f" ] && sed -i 's/\r$//' "$f"
  done
  bash ./deploy.sh up
  ```
- **验证**：
  ```bash
  grep -c $'\r' .env .env.example deploy.sh docker-compose.yaml   # 全部输出 0
  ```

### 2. 修复 Weaviate 无限重启 → `No private IP address found, and explicit IP not provided`

- **现象**：`weaviate` 容器每约 60s 崩溃重启一次，日志：
  ```
  {"action":"memberlist_init", ...,"hostname":"node1",...,
   "error":"Failed to get final advertise address: No private IP address found, and explicit IP not provided",
   "msg":"memberlist not created"}
  {"action":"startup", ...,"error":"create member list: ...","msg":"could not init cluster state"}
  ```
- **根因**：compose 里给 weaviate 配了 `CLUSTER_HOSTNAME: 'node1'`（疑似照抄 Weaviate
  官方 dev 脚本）。Weaviate 会以 `CLUSTER_HOSTNAME` 作为自己的节点名，启动
  memberlist/gossip 时按该名字做 DNS 解析来取自身的私有 advertise IP；
  容器内没有任何记录能把 `node1` 解析成容器 IP → 找不到私有 IP → 集群状态初始化失败退出。
  本部署是**单节点**，根本不需要 `CLUSTER_HOSTNAME`。
  参考：https://forum.weaviate.io/t/weaviate-cluster-deployment-on-docker-swarm-docker-compose-fails-due-to-node-address-resolution/5822/2
- **改动（仓库）**：`deploy/base/docker-compose.yaml` 删除 weaviate 的
  `CLUSTER_HOSTNAME: 'node1'` 一行，并加注释说明（单节点勿配；多节点集群才需要且该名字必须可解析）。
- **服务器修复命令**：
  ```bash
  cd /data/llmops-api/base
  sed -i "/CLUSTER_HOSTNAME/d" docker-compose.yaml
  docker compose up -d --force-recreate weaviate
  sleep 12
  docker compose logs --tail=30 weaviate
  ```
- **验证**：日志出现 `Serving weaviate at http://[::]:8080` 且不再刷 memberlist 报错；
  再确认就绪接口：
  ```bash
  curl -s http://127.0.0.1:8080/v1/.well-known/ready     # 期望 200（401 则加 -H "Authorization: Bearer <WEAVIATE_API_KEY>"）
  ```

### 本次涉及文件

| 文件 | 改动 |
|---|---|
| `deploy/base/.env.example` | CRLF → LF |
| `.gitattributes`（新增，仓库根） | 部署相关文件强制 LF |
| `deploy/base/docker-compose.yaml` | weaviate 删除 `CLUSTER_HOSTNAME: 'node1'`（含注释说明） |
