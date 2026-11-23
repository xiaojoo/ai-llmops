# 部署计划（Plan 4 · 2026-08-29）

范围：核对现有部署材料（docker-compose / nginx / Dockerfile / entrypoint / .env.example / postgres init.sql）与 FastAPI 版代码的匹配度，产出生产部署步骤与**待调整清单**。本文档只做核对与说明，未修改任何部署文件。

## 部署架构（目标）

```
浏览器
  │
  ▼
nginx:80（/api → llmops-api:5001；/ → llmops-web:3000；SSE proxy_buffering off）
  │                    │
  ▼                    ▼
llmops-api（uvicorn FastAPI app.http.app:app）   llmops-web（前端 nginx 静态/构建产物）
  │  └── celery worker（internal.task.celery_app，threads 池，Redis broker）
  ├── PostgreSQL（llmops schema，uuid-ossp）
  ├── Redis（cache + celery broker/result）
  └── Weaviate（向量库）
```

## 五项核对结果

| # | 项 | 现状 | 匹配 | 需调整 |
|---|---|---|---|---|
| 1 | docker-compose 服务/端口 | `llmops-api` 映射 5001、`llmops-web` 映射 3000、db/redis/weaviate 齐全；`env_file: .env` | ⚠️ 基本匹配 | compose 的 `llmops-web` build context `../../llmops-web` 相对 `deploy/` 解析为仓库**外**的 `H:\llmops-web`，与前端实际位置（`ai-code-llmops-web/`）不符；web 镜像需单独构建或修正 context |
| 2 | 容器启动命令 | `Dockerfile` EXPOSE 5001，entrypoint `jenkins/entrypoint.sh` | ❌ 不匹配（FastAPI） | entrypoint 仍是 Flask 时代：`flask --app app.http.app db upgrade`（迁移命令）、`celery -A app.http.app.celery`（旧 app 位置）、`flask run`/`gunicorn`（WSGI 无法服务 ASGI FastAPI）。需改：`alembic upgrade head` + `celery -A internal.task.celery_app` + `uvicorn app.http.app:app --host 0.0.0.0 --port ${LLMOPS_PORT:-5001}` |
| 3 | nginx 配置 | `/api/` rewrite 剥前缀 → `llmops-api:5001`；`proxy.conf` 已含 `proxy_buffering off` + `proxy_http_version 1.1` + 600s 读写超时 | ✅ SSE 已适配 | 注意点：`/default-app-icon`、`/healthz` 等 FastAPI 根路由若**不带 /api 前缀**访问会落到 `llmops-web`（location /）→ 404。前端统一走 `${apiPrefix}/...`（/api）则无碍（rewrite 后到 FastAPI）；生产若需裸路径，需在 nginx 加 location 转发到 api |
| 4 | .env.example ↔ settings.py | `.env.example` 覆盖 DB/Redis/Weaviate/存储/Celery/JWT/OAuth/LLM keys；`options=-csearch_path=llmops` 与 `build_engine` server_settings 方案一致；`SQLALCHEMY_DATABASE_URI`（大写）→ `sqlalchemy_database_uri`（pydantic-settings 大小写不敏感，可用） | ⚠️ 缺新字段 | settings 新增的 **embedding/rerank 组未列入 .env.example**：`EMBEDDING_PROVIDER`、`EMBEDDING_MODEL`、`EMBEDDING_DEVICE`、`EMBEDDING_API_KEY`、`EMBEDDING_API_BASE`、`RERANK_PROVIDER`、`RERANK_MODEL`、`RERANK_DEVICE`、`RERANK_API_KEY`、`RERANK_API_BASE`、`QUERY_REWRITE_MODEL`——缺省回退代码默认（本地 bge-small-zh + cpu），生产用 API 型 embedding/rerank 时必须显式配置；`WTF_CSRF_ENABLED` 等 Flask 时代多余变量无害（pydantic 忽略） |
| 5 | postgres/init.sql ↔ alembic | init.sql 建 `llmops` schema + `uuid-ossp` 扩展（置于 llmops schema）；表结构由 `alembic upgrade head`（head `a1b2c3d4e5f6`）创建——约定成立 | ✅ 匹配 | 无 |
| 5b | celery 容器化 | compose `llmops-celery` 用同一镜像 + `MODE=celery`；代码 `internal/task/celery_app.py` 已含 worker_ready 装配（dotenv/engine/session factory/apply_to_env/settings/redis）与 `set_default()` | ⚠️ 依赖 entrypoint 修复 | entrypoint 的 celery 启动命令改为 `-A internal.task.celery_app` 后即可用；threads 池下任务体内一律 `worker_run(..., engine_factory=build_engine)`（附注⑫ 教训），容器内无需额外配置 |

## 生产部署步骤（调整后）

1. **构建**：前端在 `ai-code-llmops-web` 构建产物（`npm run build`）→ 打 `llmops-web` 镜像；后端在仓库根 `docker build -t llmops-api:0.1.0 .`（多阶段：deps/browser/run）。
2. **修正 entrypoint**（必做，见待调整清单 #2），然后 `cp deploy/.env.example deploy/.env` 填写：`JWT_SECRET_KEY`/`CONFIG_MASTER_KEY`（随机 32+ 位）、`SQLALCHEMY_DATABASE_URI`（生产库 + `options=-csearch_path=llmops`）、Redis 密码、`WEAVIATE_API_KEY`、`EMBEDDING_*`/`RERANK_*`（生产用 API 型则填，否则回退本地模型需挂载模型目录）、LLM keys、`MIGRATION_ENABLED=true`（首次）。
3. **数据库**：`docker compose up llmops-db` 首次启动自动执行 init.sql（schema + uuid-ossp）；随后 api 容器启动时 `alembic upgrade head`（entrypoint 执行）。
4. **启动**：`docker compose up -d`（db/redis/weaviate/api/celery/nginx；web 视构建方式）。
5. **验证**：`curl http://<host>/healthz` → `{"status":"ok"}`；`curl http://<host>/api/default-app-icon` → image/png；无 token 请求 `/api/account` → 200 + `code=unauthorized`；SSE 对话接口返回 `text/event-stream` 且不缓冲。
6. **外置模型目录**（本地 embedding/LTP）：compose 已挂载 `/data/llmops/.../internal/core/embeddings` 与 `ltp`；entrypoint 会在缺失时从 HF 下载（生产建议预置，避免启动外呼）。

## 待调整清单（按优先级）

> 更新：P0/P1 三项已于 2026-08-29 落地（提交同 progress.md 附注⑳ 一笔），P2 为可选项。

| 优先级 | 文件 | 改动 | 状态 |
|---|---|---|---|
| P0 | `jenkins/entrypoint.sh` | `flask db upgrade` → `alembic upgrade head`；`celery -A app.http.app.celery` → `celery -A internal.task.celery_app`；`flask run`/`gunicorn` → `uvicorn app.http.app:app --host 0.0.0.0 --port ${LLMOPS_PORT:-5001}` | ✅ 已改 |
| P1 | `deploy/.env.example` | 补 `EMBEDDING_*`、`RERANK_*`、`QUERY_REWRITE_MODEL` 组（settings 已有字段） | ✅ 已改 |
| P1 | `deploy/docker-compose.yaml` | `llmops-web` build context 修正为 `../ai-code-llmops-web`（前端在仓库内） | ✅ 已改 |
| P2 | `deploy/nginx/conf.d/default.conf` | 如需裸路径 `/healthz`、`/default-app-icon`、`/docs` 直连，加对应 location 转发到 `llmops-api:5001`（/api 前缀访问则无需改） | ⬜ 可选（前端统一 /api 前缀） |
| P2 | `deploy/docker-compose.yaml` | `SQLALCHEMY_ECHO` 默认改 `false`（生产避免 SQL 全量打日志） | ⬜ 可选 |

> 说明：dev 环境（当前 127.0.0.1:5000 uvicorn + 5173 vite 代理）与容器路径的差异仅在端口/前缀；`app.http.app:app` 入口与 `internal.task.celery_app` worker 已在本机长期运行验证（含文档上传、SSE 对话、工作流、TTS 等全链路）。
