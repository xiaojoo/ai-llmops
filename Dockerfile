# ============================================================
# Stage 1: 依赖构建层
# ============================================================
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# 接收外部代理，仅作用于本 stage，不污染最终镜像。
# NO_PROXY 排除 debian / 腾讯镜像：它们必须直连（走代理会又慢又 502）；
# 只有被墙域名（download.pytorch.org 等）才需要走代理。
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY=localhost,127.0.0.1,deb.debian.org,security.debian.org,mirrors.tencent.com,mirrors.cloud.tencent.com

ENV HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    http_proxy=${HTTP_PROXY} \
    https_proxy=${HTTPS_PROXY} \
    NO_PROXY=${NO_PROXY} \
    no_proxy=${NO_PROXY}

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    build-essential \
    libpq-dev \
    libportaudio2 \
    libportaudiocpp0 \
    portaudio19-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv \
    -i https://mirrors.tencent.com/pypi/simple \
    --trusted-host mirrors.tencent.com

COPY requirements.txt .

# 服务器无 NVIDIA GPU：强制安装 CPU 版 PyTorch（torch==2.13.0+cpu），
# 避免拉取 PyPI 默认 CUDA 版 torch 自带的 nvidia-*/triton 依赖（数 GB，纯浪费）。
# +cpu 轮子只在 download.pytorch.org/whl/cpu 上，故加为 extra-index；其余依赖仍走腾讯镜像。
RUN printf 'torch==2.13.0+cpu\n' > /build/torch-cpu.override

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system \
    --link-mode=copy \
    --index-strategy unsafe-best-match \
    --index-url https://mirrors.tencent.com/pypi/simple \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    --override /build/torch-cpu.override \
    --target=/build/deps \
    -r requirements.txt

# 修改 ltp 里的文件
RUN sed -i 's/use_auth_token/token/g' /build/deps/ltp/interface.py \
    && sed -i 's/use_auth_token/token/g' /build/deps/ltp/mixin.py \
    && sed -i 's/use_auth_token/token/g' /build/deps/ltp/legacy.py \
    && sed -i 's/use_auth_token/token/g' /build/deps/ltp/nerual.py

# 检查依赖冲突（pip check 不支持 --path，用 PYTHONPATH 绕过）
RUN PYTHONPATH=/build/deps pip check || true

# ============================================================
# Stage 2: Playwright 浏览器下载层
# ============================================================
FROM python:3.12-slim-bookworm AS browser-installer

# 接收外部代理，仅作用于本 stage，不污染最终镜像
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY=localhost,127.0.0.1,mirrors.tencent.com

ENV HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    http_proxy=${HTTP_PROXY} \
    https_proxy=${HTTPS_PROXY} \
    NO_PROXY=${NO_PROXY} \
    no_proxy=${NO_PROXY} \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 libpango-1.0-0 \
    libcairo2 libatspi2.0-0 libx11-6 libx11-xcb1 libxcb1 \
    libxext6 libxcursor1 libxi6 libxtst6 libxss1 \
    wget \
    && rm -rf /var/lib/apt/lists/*

# pip 走国内源，NO_PROXY 确保不走代理
RUN pip install --no-cache-dir playwright \
    -i https://mirrors.tencent.com/pypi/simple \
    --trusted-host mirrors.tencent.com

# 官方标准写法，代理由上方 ENV 全局接管
RUN playwright install chromium


# ============================================================
# Stage 3: 最终运行镜像（无任何代理变量）
# ============================================================
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    PYTHONPATH=/llmops/deps \
    PATH="/llmops/deps/bin:${PATH}" \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    NLTK_DATA=/llmops/internal/core/unstructured/nltk_data

WORKDIR /llmops

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    postgresql-client \
    libportaudio2 \
    libportaudiocpp0 \
    curl \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libatspi2.0-0 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxext6 \
    libxcursor1 \
    libxi6 \
    libxtst6 \
    libxss1 \
    fonts-noto-cjk \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /build/deps /llmops/deps
COPY --from=browser-installer /ms-playwright /ms-playwright

COPY . .

COPY jenkins/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5001

ENTRYPOINT ["/bin/bash", "/entrypoint.sh"]