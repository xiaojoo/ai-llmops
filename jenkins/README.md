# jenkins 部署编排说明

本目录是 Jenkins 流水线（`Jenkinsfile` → `jenkins/docker-compose.yaml`）使用的自包含应用编排：
`llmops-api` / `llmops-celery` / `llmops-db` / `llmops-redis` / `llmops-weaviate` / `llmops-nginx`。

## nginx 说明（容器化，无需宿主机安装）

| 角色 | 容器 | 镜像 | 职责 |
|---|---|---|---|
| 80 网关 | `llmops-nginx` | `nginx:latest` | 对外单入口 `http://<host>/`：`/api/*` → `llmops-api:5001`（剥 `/api` 前缀），其余 → `llmops-web:3000` |
| 前端 | `llmops-web` | `nginx:alpine`（构建进 llmops-web 镜像） | SPA 静态页 + `/api` 反代（供 :3000 直连调试；内部监听 3000） |

- **镜像预拉（新服务器首次部署前）**：构建/启动前确保镜像可拉取：
  ```bash
  docker pull nginx:alpine nginx:latest
  # 若配置了本地镜像站（registry-mirrors），先把基础镜像推入：
  docker tag nginx:alpine 127.0.0.1:5000/library/nginx:alpine && docker push 127.0.0.1:5000/library/nginx:alpine
  docker tag nginx:latest 127.0.0.1:5000/library/nginx:latest && docker push 127.0.0.1:5000/library/nginx:latest
  ```
- **网关启动/随发布拉起**：Jenkinsfile 部署阶段会 `up ... llmops-nginx`（`restart: always`，重启后自动恢复）。手动启动：
  ```bash
  cd /var/lib/jenkins/workspace/llmops-api
  IMAGE_NAME=llmops-api IMAGE_TAG=<tag> docker compose -f jenkins/docker-compose.yaml up -d llmops-nginx
  ```

## 配置（全变量化，不写死密钥）

- 所有参数在 `jenkins/.env`（模板 `jenkins/.env.example`；`.env`/`memory.env` 已 gitignore，Jenkins checkout 不会清掉）。
- 改配置：编辑 `jenkins/.env` → `docker compose -f jenkins/docker-compose.yaml up -d llmops-api llmops-celery`（或重跑 Jenkins）。
- 手动跑 compose 需带镜像变量（Jenkins 会自动注入）：
  ```bash
  IMAGE_NAME=llmops-api IMAGE_TAG=0.0.x docker compose -f jenkins/docker-compose.yaml up -d llmops-api llmops-celery llmops-nginx
  ```

## 附加组件：腾讯记忆四件套

`deploy-memory.sh`（memory-core/hub/proxy + minio，配置 `memory.env`）——详见脚本头部注释。

## 新服务器首次部署（仅 Jenkins 一键）

前置准备（一次性）：
1. **docker 拉取链路**：国内服务器需保证能拉基础镜像。二选一：
   - 配 daemon 代理（推荐先配好，或见下一条镜像站方案），或
   - 起本地镜像站并预拉/预推基础镜像：`python:3.12-slim-bookworm` / `node:22-alpine` / `nginx:alpine` / `nginx:latest`（见上方"镜像预拉"命令）。
2. **Jenkins 全局变量**：`BUILD_PROXY` 指向可用代理（如 `http://<代理机IP>:7890`），供构建中 pytorch CPU 等境外下载使用；`NO_PROXY` 相关由 Jenkinsfile 处理。
3. **环境文件**：`cp jenkins/.env.example jenkins/.env` 并填写真实值（敏感项无默认值，缺失启动即失败）；如启用腾讯记忆再 `cp jenkins/memory.env.example jenkins/memory.env`。

部署步骤（顺序重要）：
1. 先跑 Jenkins **llmops-api** 任务：构建镜像 + `compose up llmops-api llmops-celery llmops-nginx`（顺带创建 `jenkins_default` 网络）。
2. 再跑 Jenkins **llmops-web** 任务：构建前端镜像（含 nginx 配置）并 `up llmops-web`（其 compose 使用 external 网络 `jenkins_default`，必须先有后端任务创建它）。

> 顺序只在**首次**（`jenkins_default` 网络尚不存在）时需要；网络创建后常驻，后续 llmops-web 可随时单独重跑。
> 例外：若有人执行过 `docker compose -f jenkins/docker-compose.yaml down`（INIT_DB=true 流程也会先 down）删掉了 `jenkins_default` 网络，则需先再跑一次后端任务重建网络。
3. 验证：
   ```bash
   curl -sI http://<新服务器IP>/ | head -1                 # 80 网关（llmops-nginx）
   curl -s http://<新服务器IP>/api/oauth/github | head -c 200   # 后端链路
   curl -s -o /dev/null -w "%{http_code}\n" http://<新服务器IP>:3000/   # 前端直连
   docker ps --format "{{.Names}} {{.Status}}" | grep -E "llmops-(api|celery|db|redis|weaviate|nginx|web)"
   ```
4. 页面入口统一为 `http://<新服务器IP>/`（80，llmops-nginx 网关）；`:3000` 仅供调试直连。

> ⚠️ 前端镜像的 nginx 配置在构建时 COPY 进镜像；80 网关 `llmops-nginx` 的配置由 compose 挂载 `jenkins/nginx/*`（随 git 拉取）。改仓库 nginx 配置后：push → Jenkins checkout → `docker restart llmops-nginx`（或重启 docker）即生效，无需重装。

## 常用命令

```bash
# 状态 / 日志
docker compose -f jenkins/docker-compose.yaml ps
docker logs -f llmops-api | llmops-celery | llmops-nginx | llmops-web

# 验证
curl -sI http://<host>/ | head -1                 # 80 网关
curl -s http://<host>/api/oauth/github | head -c 200   # 后端链路
```
