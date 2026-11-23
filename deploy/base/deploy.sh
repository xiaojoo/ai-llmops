#!/usr/bin/env bash
# ═════════════════════════════════════════════════════════════════════════
# deploy/base 基础环境一键部署脚本
#
# 部署内容：PostgreSQL + Redis + Weaviate + MinIO + 腾讯记忆三件套
#           (memory-core / memory-hub / memory-proxy)
#
# 用法：
#   ./deploy.sh                 # 等价于 ./deploy.sh up
#   ./deploy.sh up              # 一键拉起（含配置生成、等待就绪、init-admin）
#   ./deploy.sh stop            # 停止容器（保留数据卷）
#   ./deploy.sh restart         # 重启容器
#   ./deploy.sh down            # 停止并删除容器（保留数据卷）
#   ./deploy.sh purge           # 停止并删除容器 + 数据卷（彻底清理，需确认）
#   ./deploy.sh status          # 查看容器状态
#   ./deploy.sh logs [服务名]   # 跟踪日志
#
# 首次使用：cp .env.example .env 并填写必填项（见 .env.example 注释）。
# ═════════════════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ENV_FILE="$SCRIPT_DIR/.env"
ENV_TEMPLATE="$SCRIPT_DIR/.env.example"
RUNTIME_DIR="$SCRIPT_DIR/.runtime"
ADMIN_KEY_FILE="$SCRIPT_DIR/.admin-key"

# 容器名（与 docker-compose.yaml 保持一致）
CONTAINERS=(db redis weaviate minio memory-core memory-hub memory-proxy)

# 必填项（保持 REPLACE_ME 或为空会拒绝启动，避免半截拉起）
REQUIRED_VARS=(
  MEMORY_LLM_BASE_URL MEMORY_LLM_API_KEY MEMORY_LLM_MODEL
  PROXY_UPSTREAM_URL PROXY_UPSTREAM_API_KEY PROXY_UPSTREAM_MODEL
)

# ── 输出工具 ─────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YLW=$'\033[33m'; C_BLU=$'\033[34m'; C_RST=$'\033[0m'
else
  C_RED=""; C_GRN=""; C_YLW=""; C_BLU=""; C_RST=""
fi
info() { echo "${C_BLU}[$(date +%H:%M:%S)]${C_RST} $*"; }
ok()   { echo "${C_GRN}[ok]${C_RST} $*"; }
warn() { echo "${C_YLW}[warn]${C_RST} $*" >&2; }
die()  { echo "${C_RED}[error]${C_RST} $*" >&2; exit 1; }

# ── 环境准备 ─────────────────────────────────────────────────────────────
check_docker() {
  command -v docker >/dev/null 2>&1 || die "找不到 docker 命令，请先安装 Docker。"
  docker compose version >/dev/null 2>&1 \
    || die "docker compose 插件不可用（需 Docker Compose v2）。"
}

ensure_env() {
  if [[ ! -f "$ENV_FILE" ]]; then
    cp "$ENV_TEMPLATE" "$ENV_FILE"
    warn "已从 .env.example 生成 $ENV_FILE —— 请先编辑填写必填项后重跑："
    warn "  MEMORY_LLM_BASE_URL / MEMORY_LLM_API_KEY / MEMORY_LLM_MODEL"
    warn "  PROXY_UPSTREAM_URL / PROXY_UPSTREAM_API_KEY / PROXY_UPSTREAM_MODEL"
    exit 1
  fi
}

load_env() {
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
}

check_required() {
  local missing=() var val
  for var in "${REQUIRED_VARS[@]}"; do
    val="${!var:-}"
    if [[ -z "$val" || "$val" == "REPLACE_ME" ]]; then
      missing+=("$var")
    fi
  done
  if (( ${#missing[@]} > 0 )); then
    echo "${C_RED}[error]${C_RST} .env 中以下必填参数未设置或仍为 REPLACE_ME：" >&2
    for var in "${missing[@]}"; do echo "  - $var" >&2; done
    echo "" >&2
    echo "  编辑 $ENV_FILE 后重试。" >&2
    exit 1
  fi
}

# 探测宿主机 LAN IP（供 Panel "客户端接入地址"卡片展示；探测不到回落 localhost）
detect_host_ip() {
  local ip=""
  if command -v hostname >/dev/null 2>&1; then
    ip=$(hostname -I 2>/dev/null | tr ' ' '\n' \
      | awk '/^[0-9]+\./ && $0 !~ /^127\./ && $0 !~ /^169\.254\./' | head -n1)
    [[ -n "$ip" ]] && { echo "$ip"; return; }
  fi
  if command -v ip >/dev/null 2>&1; then
    ip=$(ip -4 route get 1 2>/dev/null | awk '/src/ {for (i=1;i<=NF;i++) if ($i=="src") print $(i+1); exit}')
    [[ -n "$ip" ]] && { echo "$ip"; return; }
  fi
  echo "localhost"
}

# ── 生成腾讯记忆配置文件（镜像不认环境变量，必须挂配置）──────────────────
generate_configs() {
  mkdir -p "$RUNTIME_DIR"

  # 1) memory-core gateway 配置（standalone + skill 最小配置，逻辑同官方脚本）
  info "生成 memory-core 配置 → $RUNTIME_DIR/tdai-gateway.yaml"
  cat > "$RUNTIME_DIR/tdai-gateway.yaml" <<YAML
# 由 deploy.sh 自动生成 —— 每次启动覆盖，请不要手动改。
deployMode: standalone
stateBackend: local

server:
  port: 8420
  host: 0.0.0.0

data:
  baseDir: /data/tdai-memory

llm:
  baseUrl: "${MEMORY_LLM_BASE_URL}"
  apiKey: "${MEMORY_LLM_API_KEY}"
  model: "${MEMORY_LLM_MODEL}"
  maxTokens: 32000
  timeoutMs: 300000

memory:
  promptMode: ${MEMORY_PROMPT_MODE:-chat}
  capture: { enabled: true }
  extraction:
    enabled: true
    enableDedup: true
    maxMemoriesPerSession: 20
  persona:
    triggerEveryN: 50
    maxScenes: 15
  pipeline:
    everyNConversations: 5
    enableWarmup: true
    l1IdleTimeoutSeconds: 600
    l2DelayAfterL1Seconds: 90
    l2MinIntervalSeconds: 900
    l2MaxIntervalSeconds: 3600
  recall:
    enabled: true
    maxResults: 5
    scoreThreshold: 0.3
    strategy: hybrid
    timeoutMs: 5000
  storeBackend: sqlite
  embedding:
    provider: none

skill:
  enabled: true
  routing:
    mode: bm25
    searchTopK: 20
  extraction:
    enabled: true
    maxIterations: 16
    queue:
      backend: local
      keyPrefix: tdai
      resultTtlSeconds: 86400
      lockTtlMs: 600000
      maxRetries: 2
      retryBackoffsMs: [5000, 15000]
  resources:
    maxResourceSizeBytes: 5000000
YAML

  # 2) proxy 配置（从 PROXY_FULL_STACK 计算三大能力开关）
  if [[ "${PROXY_FULL_STACK:-0}" == "1" ]]; then
    PROXY_ENABLE_AUTH=1
    PROXY_ENABLE_TDAI=1
    PROXY_ENABLE_SESSION_INIT=1
  fi
  PROXY_ENABLE_AUTH="${PROXY_ENABLE_AUTH:-0}"
  PROXY_ENABLE_TDAI="${PROXY_ENABLE_TDAI:-0}"
  PROXY_ENABLE_SESSION_INIT="${PROXY_ENABLE_SESSION_INIT:-0}"
  if [[ "$PROXY_ENABLE_SESSION_INIT" == "1" && "$PROXY_ENABLE_AUTH" != "1" ]]; then
    warn "PROXY_ENABLE_SESSION_INIT=1 需要 auth；自动打开 PROXY_ENABLE_AUTH"
    PROXY_ENABLE_AUTH=1
  fi

  bool() { [[ "$1" == "1" ]] && echo "true" || echo "false"; }

  # hub/proxy 的 gateway key 默认 "local"（与官方脚本一致；memory-core 才允许空=关闭 Bearer gate）
  GW_KEY="${MEMORY_CORE_GATEWAY_API_KEY:-local}"

  info "生成 proxy 配置 → $RUNTIME_DIR/proxy-config.yaml  (auth=$(bool "$PROXY_ENABLE_AUTH") session-init=$(bool "$PROXY_ENABLE_SESSION_INIT") tdai=$(bool "$PROXY_ENABLE_TDAI"))"
  cat > "$RUNTIME_DIR/proxy-config.yaml" <<YAML
# 由 deploy.sh 自动生成 —— 每次启动覆盖，请不要手动改。
server:
  host: 0.0.0.0
  port: 8096
  forwardTimeoutMs: 600000

upstream:
  url: "${PROXY_UPSTREAM_URL}"
  apiKey: "${PROXY_UPSTREAM_API_KEY}"

log:
  file: ""
  level: info
  backend: console

tdai:
  enabled: $(bool "$PROXY_ENABLE_TDAI")
  endpoint: "http://memory-core:8420"
  apiKey: "${GW_KEY}"
  serviceId: default
  memory:
    enabled: true
    inject: true
    writeL0: true
    recallL1: true
    injectL2L3: true

skill:
  endpoint: "http://memory-core:8420"
  serviceToken: "${GW_KEY}"

auth:
  enabled: $(bool "$PROXY_ENABLE_AUTH")
  url: "http://memory-core:8420"
  timeoutMs: 5000

sessionInit:
  enabled: $(bool "$PROXY_ENABLE_SESSION_INIT")
  maxRetries: 3
  injectAgentContext: true
  injectTaskContext: true
  headerAutoSelect:
    enabled: true
    teamHeader: "x-team-id"
    agentHeader: "x-agent-id"
    taskHeader: "x-task-id"
    onMismatch: "form"

costGuard:
  enabled: false

injection:
  enabled: true
  injectors:
    - skill
    - knowledge
    - tdai-memory

redis:
  enabled: false
YAML
}

# ── 等待容器 running ─────────────────────────────────────────────────────
wait_running() {
  local timeout="${1:-180}" waited=0 st
  info "等待全部容器运行（最长 ${timeout}s）..."
  while (( waited < timeout )); do
    local all_up=1
    for c in "${CONTAINERS[@]}"; do
      st="$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || echo missing)"
      if [[ "$st" != "running" ]]; then all_up=0; break; fi
    done
    if (( all_up == 1 )); then
      ok "全部容器已运行"
      return 0
    fi
    sleep 3
    waited=$((waited + 3))
  done
  warn "等待超时，当前容器状态："
  docker compose ps || true
  return 1
}

# ── 端口冒烟检查 ─────────────────────────────────────────────────────────
smoke_check() {
  local label="$1" port="$2"
  if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
    exec 3>&- 2>/dev/null || true
    ok "  $label 可连 → 127.0.0.1:$port"
  else
    warn "  $label 端口 $port 未就绪"
  fi
}

# ── memory-core admin 用户初始化 ─────────────────────────────────────────
generate_user_key() {
  local raw
  if command -v openssl >/dev/null 2>&1; then
    raw=$(openssl rand -base64 48 | LC_ALL=C tr -dc 'A-Za-z0-9' | head -c 32)
  else
    raw=$(head -c 256 /dev/urandom | LC_ALL=C tr -dc 'A-Za-z0-9' | head -c 32)
  fi
  echo "sk-mem-${raw}"
}

init_admin() {
  command -v curl >/dev/null 2>&1 || { warn "未找到 curl，跳过 init-admin（可在容器起来后手动初始化）"; return 0; }
  local port="${MEMORY_CORE_PORT:-8420}"
  local username="${MEMORY_CORE_ADMIN_USERNAME:-admin}"
  local gw="${MEMORY_CORE_GATEWAY_API_KEY-}"
  local key="" code auth=()

  if [[ -s "$ADMIN_KEY_FILE" ]]; then
    key="$(cat "$ADMIN_KEY_FILE")"
  else
    key="$(generate_user_key)"
  fi
  [[ -n "$gw" ]] && auth=(-H "Authorization: Bearer $gw")

  info "初始化 admin user（username=${username}）..."

  # memory-core 刚启动时 API 尚未就绪，重试最多 5 次（3s 间隔），
  # 直到拿到明确结果（200/409）或连接成功后的其他 HTTP 状态
  local attempt=0 code="000"
  while (( attempt < 5 )); do
    code="$(curl -sS --max-time 10 -o /dev/null -w "%{http_code}" \
      -X POST -H "Content-Type: application/json" \
      -H "x-tdai-service-id: default" \
      "${auth[@]}" \
      -d "$(printf '{"username":"%s","user_key":"%s"}' "$username" "$key")" \
      "http://127.0.0.1:${port}/v3/internal/meta/user/init-admin" 2>/dev/null || echo "000")"
    if [[ "$code" == "000" || "$code" == "502" || "$code" == "503" ]]; then
      attempt=$((attempt + 1))
      [[ $attempt -lt 5 ]] && { info "  memory-core 尚未就绪（HTTP=${code}），3s 后重试（${attempt}/5）..."; sleep 3; }
    else
      break
    fi
  done

  case "$code" in
    200)
      (umask 077; printf '%s' "$key" > "$ADMIN_KEY_FILE")
      ok "admin user 已创建，user_key 已保存到 $ADMIN_KEY_FILE（脱敏：${key:0:11}****${key: -4}）"
      ;;
    409)
      if [[ -s "$ADMIN_KEY_FILE" ]]; then
        ok "admin user 已存在（复用 $ADMIN_KEY_FILE 中的 key）"
      else
        warn "admin user 已存在但 $ADMIN_KEY_FILE 缺失，无法恢复 user_key；"
        warn "  如需重建：./deploy.sh purge 后重新 ./deploy.sh up"
      fi
      ;;
    *)
      warn "init-admin 返回 HTTP=${code}（非 200/409，可忽略或稍后手动检查 memory-core 日志）"
      ;;
  esac
}

# ── 服务地址表 ───────────────────────────────────────────────────────────
print_endpoints() {
  echo ""
  echo "  ┌─────────────────────────────────────────────────────────┐"
  echo "  │ 基础环境服务地址                                        │"
  echo "  ├─────────────────────────────────────────────────────────┤"
  printf "  │ PostgreSQL   %-40s│\n" "localhost:${POSTGRES_PORT:-5432} (${POSTGRES_USER:-postgres}/${POSTGRES_DB:-llmdb})"
  printf "  │ Redis        %-40s│\n" "localhost:${REDIS_PORT:-6379}"
  printf "  │ Weaviate     %-40s│\n" "localhost:${WEAVIATE_HTTP_PORT:-8080} (gRPC ${WEAVIATE_GRPC_PORT:-50051})"
  printf "  │ MinIO S3     %-40s│\n" "localhost:${MINIO_API_PORT:-9000}"
  printf "  │ MinIO 控制台 %-40s│\n" "localhost:${MINIO_CONSOLE_PORT:-9001} (${MINIO_ROOT_USER:-minioadmin})"
  printf "  │ 记忆 Core    %-40s│\n" "localhost:${MEMORY_CORE_PORT:-8420}/"
  printf "  │ 记忆 Panel   %-40s│\n" "localhost:${PANEL_PORT:-8125}/"
  printf "  │ 知识服务     %-40s│\n" "localhost:${KNOWLEDGE_PORT:-8424}/v3/"
  printf "  │ 记忆 Proxy   %-40s│\n" "localhost:${PROXY_PORT:-8096}/"
  echo "  └─────────────────────────────────────────────────────────┘"
  echo ""
  echo "  应用侧对接（把 llmops 应用环境变量指向本基础环境）："
  echo "    SQLALCHEMY_DATABASE_URI=postgresql://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD:-123456}@db:5432/${POSTGRES_DB:-llmdb}?client_encoding=utf8&options=-csearch_path=llmops"
  echo "    REDIS_HOST=redis / REDIS_PASSWORD=${REDIS_PASSWORD:-123456}"
  echo "    WEAVIATE_HTTP_HOST=weaviate / WEAVIATE_GRPC_HOST=weaviate / WEAVIATE_API_KEY=${WEAVIATE_API_KEY:-change-me-weaviate-key}"
  echo "    TENCENT_MEMORY_ENDPOINT=http://localhost:${MEMORY_CORE_PORT:-8420}"
  echo "    容器内访问：http://memory-core:8420 / http://memory-hub:8125 / http://memory-proxy:8096（网络 base-net）"
  echo ""
  echo "  日志：  docker logs -f memory-core | memory-hub | memory-proxy | db | redis | weaviate | minio"
  echo "  停止：  ./deploy.sh stop    彻底清理：./deploy.sh purge"
}

# ── 子命令实现 ───────────────────────────────────────────────────────────
cmd_up() {
  check_docker
  ensure_env
  load_env
  check_required

  # Panel 接入地址：未显式设置时自动探测宿主机 IP
  if [[ -z "${MEMORY_HUB_PROXY_PUBLIC_URL+x}" || -z "${MEMORY_HUB_PROXY_PUBLIC_URL}" ]]; then
    _host_ip="$(detect_host_ip)"
    MEMORY_HUB_PROXY_PUBLIC_URL="http://${_host_ip}:${PROXY_PORT:-8096}"
    export MEMORY_HUB_PROXY_PUBLIC_URL
    info "自动探测宿主机地址: MEMORY_HUB_PROXY_PUBLIC_URL=$MEMORY_HUB_PROXY_PUBLIC_URL"
    info "  (如需覆盖，在 .env 里显式设 MEMORY_HUB_PROXY_PUBLIC_URL=http://<your-ip>:${PROXY_PORT:-8096})"
  fi

  generate_configs

  info "拉起基础环境（docker compose up -d）..."
  docker compose up -d

  wait_running 180 || {
    warn "部分容器未就绪，查看日志：docker compose logs --tail=50 <服务名>"
    exit 1
  }

  # 端口冒烟
  info "端口冒烟检查："
  smoke_check "PostgreSQL" "${POSTGRES_PORT:-5432}"
  smoke_check "Redis"      "${REDIS_PORT:-6379}"
  smoke_check "Weaviate"   "${WEAVIATE_HTTP_PORT:-8080}"
  smoke_check "MinIO"      "${MINIO_API_PORT:-9000}"
  smoke_check "记忆 Core"  "${MEMORY_CORE_PORT:-8420}"
  smoke_check "记忆 Panel" "${PANEL_PORT:-8125}"
  smoke_check "知识服务"   "${KNOWLEDGE_PORT:-8424}"
  smoke_check "记忆 Proxy" "${PROXY_PORT:-8096}"

  init_admin
  print_endpoints
  ok "基础环境部署完成 ✅"
}

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
}

# ── 入口 ─────────────────────────────────────────────────────────────────
case "${1:-up}" in
  up)
    cmd_up
    ;;
  stop)
    check_docker
    docker compose stop
    ok "已停止（数据卷保留）"
    ;;
  restart)
    check_docker
    docker compose restart
    ;;
  down)
    check_docker
    docker compose down
    ok "已停止并删除容器（数据卷保留）"
    ;;
  gen-configs)
    # 只重新生成腾讯记忆配置文件（.runtime/），不操作容器
    ensure_env
    load_env
    check_required
    generate_configs
    ok "配置已生成到 $RUNTIME_DIR/"
    ;;
  purge)
    check_docker
    read -r -p "将删除全部容器 + 数据卷（含记忆数据），确认? [y/N] " ans
    [[ "$ans" =~ ^[yY] ]] || die "已取消"
    docker compose down -v
    rm -rf "$RUNTIME_DIR"
    rm -f "$ADMIN_KEY_FILE"
    ok "已彻底清理"
    ;;
  status|ps)
    check_docker
    docker compose ps
    ;;
  logs)
    check_docker
    shift
    docker compose logs -f --tail=100 "$@"
    ;;
  *)
    usage
    die "未知子命令: ${1:-}"
    ;;
esac
