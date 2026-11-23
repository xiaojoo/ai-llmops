# deploy/base — 基础环境一键部署

一键部署 LLMOps 后端所需的基础设施：**PostgreSQL + Redis + Weaviate + MinIO + 腾讯记忆三件套**（memory-core / memory-hub / memory-proxy）。

## 服务清单

| 服务 | 镜像 | 宿主机端口 | 用途 |
|---|---|---|---|
| `db` | postgres:18-alpine | 5432 | 业务数据库（`postgres`/`llmdb`，含 `llmops` schema） |
| `redis` | redis:7-alpine | 6379 | 缓存 + Celery broker（requirepass 默认 `123456`） |
| `weaviate` | semitechnologies/weaviate:1.28.4 | 8080 / 50051 | 向量数据库（API Key 鉴权） |
| `minio` | minio/minio | 9000 / 9001 | 对象存储 S3 + 管理控制台 |
| `memory-core` | agentmemory/memory-core | 8420 | 腾讯记忆内核（应用 `TENCENT_MEMORY_ENDPOINT` 指向这里） |
| `memory-hub` | agentmemory/memory-hub | 8125 / 8424 | 记忆管理面板 (Panel) + 知识服务 (Knowledge) |
| `memory-proxy` | agentmemory/memory-proxy | 8096 | LLM 转发代理（coding agent 的 API 入口） |

## 快速开始

```bash
cd deploy/base

# 1. 生成配置并填写必填项（LLM 两组参数；其余可保持默认）
cp .env.example .env
#    编辑 .env：MEMORY_LLM_BASE_URL / MEMORY_LLM_API_KEY / MEMORY_LLM_MODEL
#              PROXY_UPSTREAM_URL / PROXY_UPSTREAM_API_KEY / PROXY_UPSTREAM_MODEL
#              （两组可以填相同的 DeepSeek/任意 OpenAI 兼容端点）

# 2. 一键拉起
./deploy.sh up
```

`deploy.sh up` 会自动完成：

1. 检查 docker / docker compose v2
2. `.env` 不存在时从模板复制并提示（必填项仍为 `REPLACE_ME` 会拒绝启动）
3. 从 `.env` 生成腾讯记忆配置：`.runtime/tdai-gateway.yaml`（memory-core）、`.runtime/proxy-config.yaml`（proxy）——镜像不认环境变量，必须挂配置
4. `docker compose up -d` 拉起全部容器，等待 running + 端口冒烟
5. 自动初始化 memory-core admin 用户，随机 `sk-mem-*` user_key 保存到 `.admin-key`（权限 0600）
6. 打印服务地址表与应用侧对接环境变量

## 子命令

```bash
./deploy.sh              # = up
./deploy.sh stop         # 停止容器（数据卷保留）
./deploy.sh restart      # 重启
./deploy.sh down         # 停止并删除容器（数据卷保留）
./deploy.sh purge        # 删除容器 + 数据卷 + .runtime/.admin-key（彻底清理，需确认）
./deploy.sh status       # 容器状态
./deploy.sh logs [服务]  # 跟踪日志（如 ./deploy.sh logs memory-core）
```

## 端到端部署流程（新服务器完整时序）

从零到应用可用的完整时序（以服务器 IP `172.20.70.38` 为例；各步骤细节见对应章节）。

### 阶段 0：前置检查

- 服务器：Docker + Compose v2、bash、curl；开发机可直连服务器各端口
- 目录结构（`base` 与 `postgres` **必须同级**，compose 用相对路径 `../postgres/init.sql`）：

  ```
  /data/llmops/
  ├── base/            # deploy/base（.env.example / deploy.sh / docker-compose.yaml / README.md）
  └── postgres/        # deploy/postgres/init.sql
  ```

### 阶段 1：部署基础环境（首次拉镜像较久）

```bash
cd /data/llmops/base
cp .env.example .env
vi .env               # 必填：MEMORY_LLM_* / PROXY_UPSTREAM_* 两组 LLM（可相同）
sudo ./deploy.sh up
```

预期：7 容器 running、9 端口冒烟全 `[ok]`、`[ok] admin user 已创建 ... .admin-key`。

### 阶段 2：应用侧对齐

```bash
# 应用仓库 deploy/ 下（compose 已默认对接 base-net，db/redis/weaviate 已注释）
cp .env.example .env
vi .env
#   必填：JWT_SECRET_KEY / CONFIG_MASTER_KEY（随机 32+ 位）
#   WEAVIATE_API_KEY 填 base/.env 里的同一个值（不一致 → 启动报 401）
#   host 已是 db/redis/weaviate，勿改回 llmops-*
```

### 阶段 3：部署应用（自动引导数据库）

- **方式 A — 容器部署**：`cd deploy && sudo docker compose up -d --build`
  （entrypoint 在 `MIGRATION_ENABLED=true` 时自动执行 `scripts/bootstrap_db.py`：空库建表 + stamp head）
- **方式 B — 本地开发直连**：见"本地开发直连服务器基础环境"章节，首次手动跑一次 `python scripts/bootstrap_db.py` 再启动

### 阶段 4：配置腾讯记忆（/settings 页面，走 DB 不走环境变量）

1. 登录应用 → 系统设置 → 记忆系统
2. `MEMORY_PROVIDER=tencent`
3. `TENCENT_MEMORY_ENDPOINT=http://172.20.70.38:8420`
4. `TENCENT_MEMORY_API_KEY` = `cat /data/llmops/base/.admin-key`（整串 `sk-mem-...`）
5. `TENCENT_MEMORY_SERVICE_ID=default`
6. 点"测试连通"，通过后保存

### 阶段 5：验证

```bash
# 基础环境
sudo docker compose -f /data/llmops/base/docker-compose.yaml ps
curl -s -X POST http://172.20.70.38:8420/v3/meta/auth/verify \
  -H 'Content-Type: application/json' -d '{"user_key":"<.admin-key 内容>"}'

# 应用（无 system_config 报错、无 401 即正常）
curl -s http://172.20.70.38:5001/docs | head -c 200
sudo docker compose logs --tail=50 llmops-api
```

> 端口速查：DB 5432 / Redis 6379 / Weaviate 8080+50051 / MinIO 9000+9001 / 记忆 Core 8420、Panel 8125、知识 8424、Proxy 8096 / 应用 API 5001 / 前端 3000 / Nginx 80

## 与应用（llmops-api）对接

本基础环境与应用侧 `deploy/docker-compose.yaml` 里的 `llmops-db / llmops-redis / llmops-weaviate` 服务**功能相同但服务名不同**，二者不要同时运行（会端口冲突）。二选一：

- **用本基础环境**：启动应用时注释掉 `deploy/docker-compose.yaml` 中的 `llmops-db / llmops-redis / llmops-weaviate` 三个服务，并把应用环境变量指向本环境（服务在同一 Docker 网络 `base-net` 时用服务名直连）：

  ```
  SQLALCHEMY_DATABASE_URI=postgresql://postgres:123456@db:5432/llmdb?client_encoding=utf8&options=-csearch_path=llmops
  REDIS_HOST=redis
  REDIS_PASSWORD=123456
  WEAVIATE_HTTP_HOST=weaviate
  WEAVIATE_GRPC_HOST=weaviate
  WEAVIATE_API_KEY=<与 .env 相同>
  TENCENT_MEMORY_ENDPOINT=http://memory-core:8420
  ```

- **只用本环境做联调**：应用跑在宿主机时直接用 `localhost` 端口（5432 / 6379 / 8080 / 8420）。

> 若应用容器与基础环境不在同一 compose 项目，需把应用容器加入 `base-net` 网络：
> `docker network connect base-net <应用容器名>`，或应用 compose 声明
> `networks: { default: { name: base-net, external: true } }`。

### 数据库引导（重要，新库必读）

**迁移链是断的，空库不能靠 `alembic upgrade head` 从零建表**：迁移链基线 `273f811b2cf4` 是 no-op 锚点（当年表结构由应用启动时 `create_all` 建立），后续迁移都假设表已存在，空库跑会在 `add message.is_archived` 处报 `relation "message" does not exist`。

正确引导流程（幂等，可重复执行）：

```bash
# 在应用仓库根目录执行（容器内由 entrypoint 自动调用，无需手动）
python scripts/bootstrap_db.py
```

脚本做什么：`system_config` 表不存在（空库）→ 全量 `create_all` 建表（29 张，`llmops` schema）→ `alembic_version` stamp 到 head。已有库全部跳过。

- 容器部署：`jenkins/entrypoint.sh` 在 `MIGRATION_ENABLED=true` 时已自动调用本脚本（无需干预）
- 本地开发直连服务器库：跑一次本脚本即可，之后 uvicorn 启动不再报 `system_config does not exist`

### 应用侧 `.env` 对齐清单（对接 base 环境时）

| 应用 .env 项 | 必须等于 | 说明 |
|---|---|---|
| `SQLALCHEMY_DATABASE_URI` | `postgresql://postgres:123456@db:5432/llmdb?...` | host 用 `db`（容器内）或服务器 IP（本机直连）；账号密码与 base `POSTGRES_*` 一致 |
| `REDIS_HOST` / `REDIS_PASSWORD` | `redis` / `123456` | 密码与 base `REDIS_PASSWORD` 一致 |
| `WEAVIATE_HOST` / `WEAVIATE_GRPC_HOST` | `weaviate`（或服务器 IP） | |
| `WEAVIATE_API_KEY` | **与 base `.env` 的 `WEAVIATE_API_KEY` 完全相同** | 不一致 → 应用启动报 `401 invalid api key` |
| `TENCENT_MEMORY_*` | 见"腾讯记忆说明" | 走 /settings 页面（DB），不走环境变量 |

## 本地开发直连服务器基础环境（Windows 开发机）

```bash
# 1. 本地应用 .env 指向服务器（示例服务器 IP 172.20.70.38）
SQLALCHEMY_DATABASE_URI=postgresql://postgres:123456@172.20.70.38:5432/llmdb?client_encoding=utf8&options=-csearch_path=llmops
REDIS_HOST=172.20.70.38
REDIS_PASSWORD=123456
WEAVIATE_HOST=172.20.70.38
WEAVIATE_GRPC_HOST=172.20.70.38
WEAVIATE_API_KEY=change-me-weaviate-key   # 必须与服务器 base/.env 一致

# 2. 首次：引导服务器库建表（幂等）
python scripts/bootstrap_db.py

# 3. 启动
uvicorn app.http.app:app --host 0.0.0.0 --port 5000
```

## 腾讯记忆说明

- 应用侧只需 `memory-core`（三件套里的内核）：登录应用 → 系统设置 → 记忆系统 → `MEMORY_PROVIDER=tencent`、`TENCENT_MEMORY_ENDPOINT` 填 `http://<主机>:8420`、`TENCENT_MEMORY_API_KEY` 填 `.admin-key` 文件内容、`TENCENT_MEMORY_SERVICE_ID=default`。
- `.admin-key` 位置：`deploy/base/.admin-key`（由 `deploy.sh up` 自动生成，权限 0600）。
  **查看 User Key**（Panel 登录 / 应用 `TENCENT_MEMORY_API_KEY` 都用它；`MEMORY_CORE_GATEWAY_API_KEY` 留空时 Panel 的 User Key 就填这个文件内容）：

  ```bash
  sudo cat /data/llmops/base/.admin-key
  ```
- `memory-hub`（Panel 8125 + 知识服务 8424）与 `memory-proxy`（8096）是完整体验组件，可分别通过 `docker stop memory-hub memory-proxy` 关掉，不影响应用接入。
- `MEMORY_CORE_GATEWAY_API_KEY` 保持留空（官方注明 proxy 源码兼容性问题，非空会导致 proxy 的 auth 失败；hub/proxy 内部自动用默认值 `local`）。
- 数据卷：`tdai-memory-core-data`（记忆数据）、`tdai-panel-data`（知识数据），`purge` 会一并删除。

## MinIO 说明

- 默认账号 `minioadmin/minioadmin`（控制台 http://localhost:9001），生产务必在 `.env` 改强密码。
- ⚠️ 当前应用 `STORAGE_PROVIDER=miniio` 模式走的是 **mall-third-party** 的 HTTP 接口（`MINIO_API_URL=http://localhost:88/api`），不是直连 MinIO S3。本环境提供标准 MinIO S3 服务作为对象存储底座；若应用要直连 S3，需调整存储实现或用 mall 服务指向本 MinIO（`MINIO_API_URL` 填 MinIO 地址）。

## 常见问题

- **`docker compose up` 拉镜像失败**：腾讯内网可把 `.env` 里三个 `*_IMAGE` 换成 `mirrors.tencent.com` 私仓，并先 `docker login mirrors.tencent.com`。
- **memory-core 起来但 Panel 打不开**：检查 `.env` 里 `KNOWLEDGE_PUBLIC_BASE_URL` 是否含 `/v3`。
- **proxy 转发 401**：`PROXY_UPSTREAM_API_KEY` 无效或 `PROXY_UPSTREAM_URL` 不匹配，看 `docker logs memory-proxy`。
- **应用启动报 `relation "system_config" does not exist`**：新库未引导建表，跑 `python scripts/bootstrap_db.py`（或等容器 entrypoint 自动执行）。
- **应用启动报 Weaviate `401 invalid api key`**：应用 `.env` 的 `WEAVIATE_API_KEY` 与 base `.env` 不一致，对齐后重启应用。
- **`postgres:18` 起不来报 `data in unused mount/volume`**：PG18+ 镜像要求挂载父目录 `/var/lib/postgresql`（本 compose 已正确挂载）；若手改回旧写法 `/var/lib/postgresql/data` 会拒绝启动。
- **容器内访问宿主机服务（Ollama 等）**：用 `http://host.docker.internal:<port>`（memory-hub/proxy 已加 host-gateway 映射）。
