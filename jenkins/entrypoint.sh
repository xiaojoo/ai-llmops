#!/bin/bash

# 1、启用错误检查
set -e

# -------------------------------
# 设置 Hugging Face 在线环境
# -------------------------------
export HF_HUB_OFFLINE=0
export TRANSFORMERS_OFFLINE=0
export HF_ENDPOINT="https://hf-mirror.com"

# -------------------------------
# 准备模型目录
# -------------------------------
BASE_DIR="$(pwd)/internal/core"
LTP_DIR="${BASE_DIR}/ltp"
EMB_DIR="${BASE_DIR}/embeddings/bge-small-zh"

mkdir -p "$LTP_DIR"
mkdir -p "$EMB_DIR"

# -------------------------------
# 载 LTP 模型（如果不存在）
# -------------------------------
if [ ! -f "${LTP_DIR}/config.json" ]; then
    echo "LTP model not found. Downloading..."
    python3 <<EOF
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="LTP/small",
    local_dir="${LTP_DIR}",
)
EOF
else
    echo "LTP model already exists, skipping download."
fi

# -------------------------------
# 下载 BGE Embedding 模型（如果不存在）
# -------------------------------
if [ ! -f "${EMB_DIR}/config.json" ]; then
    echo "Embedding model not found. Downloading..."
    python3 <<EOF
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="BAAI/bge-small-zh",
    local_dir="${EMB_DIR}",
)
EOF
else
    echo "Embedding model already exists, skipping download."
fi

# 2、判断是否启用的迁移数据同步，如果是则执行数据库引导
# T13⑲：FastAPI 迁移后 alembic 已 async 化，Flask CLI 不可用
# T13⑳：迁移链基线是 no-op 锚点（表结构由 create_all 建立），空库无法用
#       `alembic upgrade head` 从零建表 → 统一走 scripts/bootstrap_db.py
#       （缺表时 create_all 全量建表 + alembic_version stamp head，幂等）
if [[ "${MODE}" == "api" && "${MIGRATION_ENABLED}" == "true" ]]; then
    echo "Runnable migrations (bootstrap: create_all if needed + stamp head)"
    python scripts/bootstrap_db.py
fi

# 3、检测运行的模式(api/celery)，以执行不同的脚本
if [[ "${MODE}" == "celery" ]]; then
    # 4、运行Celery命令（T13⑲：celery app 已迁移至 internal/task/celery_app，含 worker_ready 装配）
    celery -A internal.task.celery_app worker -P ${CELERY_WORKER_CLASS:-threads} -c ${CELERY_WORKER_AMOUNT:-1} --loglevel INFO
else
  # 5、T13⑲：FastAPI 应用需 uvicorn（ASGI）——Flask run/gunicorn(WSGI) 无法服务 app.http.app:app
  uvicorn app.http.app:app \
    --host ${LLMOPS_BIND_ADDRESS:-0.0.0.0} \
    --port ${LLMOPS_PORT:-5001} \
    --workers ${SERVER_WORKER_AMOUNT:-1}
fi