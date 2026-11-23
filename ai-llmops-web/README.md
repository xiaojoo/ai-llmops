# ai-llmops-web — LLMOps 平台前端

基于 **Vue 3 + TypeScript + Vite** 的 LLMOps 智能体平台 Web 端，与后端 FastAPI 服务（`../README.md`）配套使用，提供智能体应用管理、RAG 知识库、工作流编排、工具市场、开放平台、运营分析等完整控制台能力。

## 技术栈

| 类别 | 技术 |
| --- | --- |
| 框架 | Vue 3.5 · TypeScript · Vite |
| 状态管理 | Pinia 3 |
| 路由 | Vue Router 4 |
| UI 组件库 | Arco Design Vue（按需引入） |
| 可视化 | ECharts 6 + vue-echarts（数据分析）· Vue Flow + dagre（工作流编排） |
| Markdown | markdown-it · dompurify · github-markdown-css · highlight.js |
| 列表优化 | vue-virtual-scroller（虚拟滚动） |
| 请求层 | Axios 封装 + SSE 流式（`src/utils/http/`） |
| 样式 | Tailwind CSS |
| 工程化 | Yarn 4（Corepack）· ESLint 9 · Prettier · Husky + lint-staged · Vitest |

## 目录结构

```
ai-llmops-web
├── src/
│   ├── main.ts / App.vue          # 应用入口
│   ├── config/                    # API 前缀、业务状态码、智能体事件类型（QueueEvent）
│   ├── router/                    # 路由定义（routes.ts 集中管理页面路由）
│   ├── stores/                    # Pinia store（account / credential）
│   ├── services/                  # 按领域划分的后端 API 封装
│   │   ├── ai.ts                  #   AI 对话（SSE 流式）、Prompt 优化、建议问题
│   │   ├── app.ts                 #   智能体应用
│   │   ├── conversation.ts        #   会话
│   │   ├── dataset.ts             #   数据集 / 文档 / 分段
│   │   ├── workflow.ts            #   工作流
│   │   ├── skill.ts               #   技能
│   │   ├── api-key.ts / api-tools.ts  #   OpenAPI / API Key / API 工具
│   │   ├── chroma.ts / chroma-vector.ts / weaviate-vector.ts  # 向量库管理
│   │   ├── system-config.ts       #   系统设置
│   │   └── ...                    #   account / analysis / audio / auth / builtin-app / builtin-tool / oauth / upload-file / web-app 等
│   ├── hooks/                     # 组合式函数（use-ai / use-app / use-conversation / use-dataset 等）
│   ├── utils/
│   │   └── http/                  # 请求封装：request（Axios）、stream（SSE）、xhrUpload（上传）、auth、error
│   ├── models/                    # TypeScript 类型定义
│   ├── types/                     # 全局类型声明
│   └── views/                     # 页面视图
│       ├── auth/                  #   登录、GitHub OAuth 授权回调
│       ├── space/                 #   应用空间：应用列表/详情/发布/分析、工具、工作流、数据集、技能
│       ├── store/                 #   应用商店：应用 / 工具市场
│       ├── openapi/               #   开放平台：索引、API Keys
│       ├── settings/              #   系统设置
│       ├── chroma/ weaviate/      #   向量库管理
│       ├── web-apps/              #   Web 应用（Token 免登录对话）
│       ├── pages/                 #   首页
│       └── errors/ layouts/       #   404、布局组件
├── docker/                        # 部署：docker-compose.yaml、nginx.conf
├── Dockerfile                     # 多阶段构建（node 构建 → nginx 静态服务）
├── Jenkinsfile                    # 前端 CI/CD 流水线
├── vite.config.ts                 # Vite 配置（代理、按需引入、chunk 拆分）
└── package.json
```

## 快速开始

### 环境要求

- Node.js ≥ 20.19（Yarn 4 通过 Corepack 管理）
- 后端服务已启动（默认 `http://localhost:5000`，参见仓库根 README）

### 安装与开发

```bash
yarn            # 安装依赖（registry 已配置为 npmmirror）

yarn dev        # 启动开发服务器（Vite，默认 http://localhost:5173）
```

开发模式下 `/api` 前缀的请求由 Vite 代理到后端 `http://localhost:5000`，并自动去掉 `/api` 前缀（见 `vite.config.ts`）。

### 构建与预览

```bash
yarn build      # 类型检查 + 生产构建（产物在 dist/，并输出 bundle 分析 dist/stats.html）
yarn preview    # 本地预览构建产物
```

### 测试与代码规范

```bash
yarn test:unit  # Vitest 单元测试
yarn lint       # ESLint 修复
yarn format     # Prettier 格式化
```

## 环境配置

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `VITE_API_PREFIX` | `/api` | 生产构建时的 API 请求前缀（Dockerfile 中设为 `/api`） |
| API 业务前缀 | `/api`（`src/config/index.ts`） | 所有接口统一走该前缀 |

> 前端与后端通过**统一响应契约**通信：`{ code, message, data }`，业务状态码见 `src/config/index.ts`（`success` / `fail` / `unauthorized` / `validate_error` 等）；智能体对话通过 **SSE 流式事件**推送（`agent_thought` / `agent_message` / `agent_action` / `ask_user` / `dataset_retrieval` / `agent_end` 等，见 `QueueEvent`）。

## 页面与路由

路由全部集中在 `src/router/routes.ts`：

| 路径 | 页面 |
| --- | --- |
| `/` | 首页 |
| `/space/apps` | 应用空间：智能体应用列表 / 详情 / 发布 / 运营分析 |
| `/space/datasets` | 知识库：数据集 → 文档 → 分段管理 |
| `/space/workflows` | 工作流编排 |
| `/space/tools` | 工具管理 |
| `/space/skills` | 技能管理 |
| `/store/apps`、`/store/tools` | 应用 / 工具市场 |
| `/openapi`、`/openapi/api-keys` | 开放平台：接口索引、API Key 管理 |
| `/settings` | 系统设置 |
| `/chroma`、`/weaviate` | 向量库管理 |
| `/web-apps/:token` | 已发布 Web 应用（免登录对话） |
| `/auth/login`、`/auth/authorize/:provider_name` | 登录、OAuth 授权回调 |

## 构建与部署

### Docker

`Dockerfile` 采用多阶段构建：`node:24-alpine` 安装依赖（Yarn 4 + Corepack）并执行 `yarn build`，产物由 `nginx:alpine` 静态托管（SPA 路由 `try_files` 回退到 `index.html`，静态资源缓存 1 年）。

```bash
docker build -t llmops-web .
```

### Docker Compose

`docker/docker-compose.yaml` 将前端容器映射到宿主机 `3000:80`，并接入 `jenkins_default` 外部网络与后端互通：

```bash
IMAGE_NAME=llmops-web IMAGE_TAG=latest docker compose -f docker/docker-compose.yaml up -d
```

### Jenkins

`Jenkinsfile` 流水线：Checkout → 构建 Docker 镜像（`llmops-web:0.0.${BUILD_NUMBER}`）→ Compose 部署 → 清理镜像。

## 相关文档

- 后端项目说明：仓库根 `README.md`
- 后端接口契约与 SSE 事件定义：`src/config/index.ts`、`src/utils/http/`
