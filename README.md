# LLMOps 智能体平台

基于 **FastAPI + LangChain/LangGraph + Vue 3** 的 LLMOps 平台，覆盖 Agent 构建、编排、知识库、工具、记忆、发布与评测。

## 功能

- **Agent 运行时**：ReAct、Function Call、Orchestrator；Postgres Checkpoint 持久化、Redis Stream 事件队列、断点续跑与子任务编排。
- **RAG 知识库**：Dataset / Document / Segment 三级管理，BM25 + 语义检索 + RRF 融合 + Rerank 精排。
- **工作流与工具**：LangGraph 工作流、OpenAPI 工具接入、浏览器自动化、文件系统、PPT 生成与技能隔离执行。
- **模型与内容理解**：多供应商模型接入、本地 Embedding / Rerank、OCR、语音转写与合成、非结构化文档解析。
- **平台能力**：Web 应用发布、开放 API、API Key 管理、运营分析、飞书 Webhook、GitHub OAuth。
- **工程化**：MCP Client / Server、OpenTelemetry 链路与用量指标、JSON / YAML 评测数据集和阈值门禁。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | Python 3.12 · FastAPI · Uvicorn · SQLAlchemy 2（async） |
| 数据与任务 | PostgreSQL 15 · Redis · Celery · Alembic |
| 向量与检索 | Weaviate · Chroma · sentence-transformers · LTP |
| Agent / LLM | LangChain · LangGraph · 多供应商模型适配 |
| 前端 | Vue 3 · TypeScript · Vite · Pinia · Vue Router · Arco Design |
| 可观测与集成 | OpenTelemetry · LangSmith · MCP |
| 部署 | Docker · Docker Compose · Jenkins |

## 安装与使用

### 环境要求

- Python 3.12
- Node.js `^20.19.0 || >=22.12.0`，Yarn 4.13
- PostgreSQL 15、Redis、Weaviate；对象存储可使用 MinIO 或腾讯云 COS

### Docker Compose

```bash
cp jenkins/.env.example jenkins/.env
# 修改数据库、Redis、Weaviate、JWT、CONFIG_MASTER_KEY 等配置

docker compose -f jenkins/docker-compose.yaml up -d --build
```

默认 API 端口为 `5001`，Nginx 端口为 `80`。

### 本地开发

先启动 PostgreSQL、Redis 和 Weaviate，再执行：

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp deploy/.env.example .env
# 将 .env 中的 db / redis / weaviate 主机改为本地实际地址
# 本地联调使用 5000，与前端 Vite 代理保持一致

python scripts/bootstrap_db.py
uvicorn app.http.app:app --host 0.0.0.0 --port 5000 --reload
```

前端：

```bash
cd ai-llmops-web
corepack enable
yarn install
yarn dev
```

前端开发服务器默认使用 `5173`；生产构建执行 `yarn build`。

### 测试与评测

```bash
pytest

python scripts/eval_suite.py scripts/eval_cases.json \
  --base-url http://127.0.0.1:5000 \
  --output eval-report.json
```

评测配置、指标与阈值说明见 [internal/eval/runner.py](internal/eval/runner.py) 和 [scripts/eval_suite.py](scripts/eval_suite.py)。

## 目录

```text
.
├── app/                     FastAPI 入口与生命周期装配
├── internal/                业务实现与 Agent / RAG / 工具核心
│   └── migrations/          Alembic 迁移
├── ai-llmops-web/           Vue 3 前端
├── idea-plugin/             IDEA 插件
├── vscode-plugin/           VS Code 插件
├── tencentdb_agent_memory/  腾讯记忆 SDK（vendored）
├── scripts/                 数据库引导、评测与运维脚本
├── test/                    后端测试
├── docs/                    设计、迁移与接入文档
├── deploy/                  部署配置
├── jenkins/                  Compose、Nginx 与 CI 配置
├── Dockerfile               后端镜像
└── requirements.txt         Python 依赖
```

## 许可

本仓库原创代码采用 [CC0 1.0 Universal](LICENSE) 发布，可自由复制、修改、分发和商用。

第三方依赖、`tencentdb_agent_memory/` 等 vendored 内容及其自带资源保留各自许可，不在 CC0 覆盖范围内。
