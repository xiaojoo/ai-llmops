#!/usr/bin/env bash
# ═════════════════════════════════════════════════════════════════════════
# jenkins 腾讯记忆四件套部署脚本（memory-core / memory-hub / memory-proxy / minio）
# 附加于 llmops 应用栈之上，不自建 db/redis/weaviate。
#
# 用法：
#   ./deploy-memory.sh                 # 等价于 ./deploy-memory.sh up
#   ./deploy-memory.sh up              # 一键拉起（配置生成 + 等待就绪）
#   ./deploy-memory.sh gen-configs     # 只重新生成 .runtime/ 配置
#   ./deploy-memory.sh stop | down     # 停止 / 停止并删除容器（数据卷保留）
#   ./deploy-memory.sh purge           # 删除容器 + 数据卷 + 配置文件（彻底清理）
#   ./deploy-memory.sh status | logs   # 状态 / 日志
#
# 首次使用：cp memory.env.example memory.env 并填写必填项（LLM 两组 + minio 口令）。
# ═════════════════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ENV_FILE="$SCRIPT_DIR/memory.env"
RUNTIME_DIR="$SCRIPT_DIR/.runtime"
ADMIN_KEY_FILE="$SCRIPT_DIR/.memory-admin-key"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.memory.yaml"

# 四件套容器名（与 compose 保持一致）
CONTAINERS=(memory-core memory-hub memory-proxy minio)

# 必填项
REQUIRED_VARS=(MEMORY_LLM_BASE_URL MEMORY_LLM_API_KEY MEMORY_LLM_MODEL
               PROXY_UPSTREAM_URL PROXY_UPSTREAM_API_KEY PROXY_UPSTREAM_MODEL
               MINIO_ROOT_PASSWORD)

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

ensure_env() {
  if [[ ! -f "$ENV_FILE" ]]; then
    die "缺少 $ENV_FILE —— 请先：cp memory.env.example memory.env 并填写必填项"
  fi
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  local missing=() var
  for var in "${REQUIRED_VARS[@]}"; do
    local val="${!var:-}"
    if [[ -z "$val" || "$val" == "REPLACE_ME" ]]; then
      missing+=("$var")
    fi
  done
  if (( ${#missing[@]} > 0 )); then
    die "memory.env 中以下必填项未设置或仍为 REPLACE_ME：${missing[*]}"
  fi
}

check_docker() {
  command -v docker >/dev/null 2>&1 || die "找不到 docker 命令。"
  docker compose version >/dev/null 2>&1 || die "docker compose 插件不可用（需 v2）。"
}

# 清理同名旧容器尸体（存储重建等历史遗留，无法 start 的 Exited 容器）
cleanup_stale() {
  local c
  for c in "${CONTAINERS[@]}"; do
    if docker ps -a --format '{{.Names}}' | grep -qx "$c"; then
      local st
      st="$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || echo gone)"
      if [[ "$st" != "running" ]]; then
        warn "移除旧容器 $c（状态 $st，无法复用）"
        docker rm -f "$c" >/dev/null 2>&1 || true
      fi
    fi
  done
}

# ── 生成腾讯记忆配置文件（镜像不认环境变量，必须挂配置）──────────────────
generate_configs() {
  mkdir -p "$RUNTIME_DIR"

  info "生成 memory-core 配置 → $RUNTIME_DIR/tdai-gateway.yaml"
  cat > "$RUNTIME_DIR/tdai-gateway.yaml" <<YAML
# 由 deploy-memory.sh 自动生成 —— 每次启动覆盖，请不要手动改。
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

  # proxy 能力开关（从 PROXY_FULL_STACK 计算）
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
  GW_KEY="${MEMORY_CORE_GATEWAY_API_KEY:-local}"

  info "生成 proxy 配置 → $RUNTIME_DIR/proxy-config.yaml  (auth=$(bool "$PROXY_ENABLE_AUTH") session-init=$(bool "$PROXY_ENABLE_SESSION_INIT") tdai=$(bool "$PROXY_ENABLE_TDAI"))"
  cat > "$RUNTIME_DIR/proxy-config.yaml" <<YAML
# 由 deploy-memory.sh 自动生成 —— 每次启动覆盖，请不要手动改。
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
  local timeout="${1:-120}" waited=0 st all_up
  info "等待全部容器运行（最长 ${timeout}s）..."
  while (( waited < timeout )); do
    all_up=1
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
  warn "等待超时，当前状态："
  docker compose -f "$COMPOSE_FILE" ps || true
  return 1
}

print_endpoints() {
  echo ""
  echo "  腾讯记忆服务地址："
  echo "    记忆 Core   http://localhost:${MEMORY_CORE_PORT:-8420}/"
  echo "    记忆 Panel  http://localhost:${PANEL_PORT:-8125}/"
  echo "    知识服务    http://localhost:${KNOWLEDGE_PORT:-8424}/v3/"
  echo "    记忆 Proxy  http://localhost:${PROXY_PORT:-8096}/"
  echo "    MinIO       http://localhost:${MINIO_API_PORT:-9000}/  控制台 :${MINIO_CONSOLE_PORT:-9001}"
  echo ""
  echo "  应用侧对接（jenkins/.env 追加）："
  echo "    TENCENT_MEMORY_ENDPOINT=http://localhost:${MEMORY_CORE_PORT:-8420}"
  echo "  日志：docker logs -f memory-core | memory-hub | memory-proxy | minio"
}

cmd_up() {
  check_docker
  ensure_env
  cleanup_stale
  generate_configs

  info "拉取镜像（如需）..."
  docker pull "${MEMORY_CORE_IMAGE:-agentmemory/memory-core:latest}" >/dev/null 2>&1 || true
  docker pull "${MEMORY_HUB_IMAGE:-agentmemory/memory-hub:latest}" >/dev/null 2>&1 || true
  docker pull "${PROXY_IMAGE:-agentmemory/memory-proxy:latest}" >/dev/null 2>&1 || true
  docker pull minio/minio:latest >/dev/null 2>&1 || true

  info "拉起腾讯记忆四件套..."
  docker compose -f "$COMPOSE_FILE" up -d

  wait_running 120 || { warn "部分容器未就绪：docker compose -f $COMPOSE_FILE logs --tail=50 <服务名>"; exit 1; }
  print_endpoints
  ok "腾讯记忆四件套部署完成 ✅"
}

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
}

case "${1:-up}" in
  up)
    cmd_up
    ;;
  gen-configs)
    ensure_env
    generate_configs
    ok "配置已生成到 $RUNTIME_DIR/"
    ;;
  stop)
    check_docker
    docker compose -f "$COMPOSE_FILE" stop
    ;;
  down)
    check_docker
    docker compose -f "$COMPOSE_FILE" down
    ;;
  purge)
    check_docker
    read -r -p "将删除四件套容器 + 数据卷（含记忆数据），确认? [y/N] " ans
    [[ "$ans" =~ ^[yY] ]] || die "已取消"
    docker compose -f "$COMPOSE_FILE" down -v
    rm -rf "$RUNTIME_DIR"
    rm -f "$ADMIN_KEY_FILE"
    ok "已彻底清理"
    ;;
  status|ps)
    check_docker
    docker compose -f "$COMPOSE_FILE" ps
    ;;
  logs)
    check_docker
    shift
    docker compose -f "$COMPOSE_FILE" logs -f --tail=100 "$@"
    ;;
  *)
    usage
    die "未知子命令: ${1:-}"
    ;;
esac
