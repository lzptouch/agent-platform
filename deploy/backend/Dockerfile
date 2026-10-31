# =====================================================================
# agent · 后端镜像（FastAPI / Uvicorn）
#
# 构建上下文必须是仓库根目录（agent/）：
#   docker build -f deploy/backend/Dockerfile -t agent-backend:1.1.0 .
#
# 主要依赖（见 backend/requirements.txt）：
#   - Web：fastapi + uvicorn[standard]
#   - LLM：openai / anthropic SDK（DashScope、DeepSeek 兼容模式）
#   - MCP SDK：mcp[cli] + fastmcp
#   - 向量库：pymilvus + milvus-lite（Milvus Lite 本地文件库，无 torch）
#   - Web Research：chromadb + langchain-* + pymupdf
#   - 浏览器自动化：playwright + chromium（小红书 MCP Server 用，可用构建参数关闭）
# =====================================================================

FROM python:3.12-slim AS base

# ---------- 构建参数 ----------
ARG PIP_INDEX_URL=https://pypi.org/simple
# 可选：把 Debian 源替换为国内镜像（CI 环境直连 deb.debian.org 常出现
#   "Unable to connect to deb.debian.org:http" 导致构建失败）
#   用法：--build-arg APT_MIRROR=mirrors.ustc.edu.cn
ARG APT_MIRROR=
ARG INSTALL_PLAYWRIGHT=true
ARG TARGETARCH

# ---------- 运行时环境变量 ----------
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai \
    PLAYWRIGHT_BROWSERS_PATH=/home/app/.cache/ms-playwright

WORKDIR /app

# ---------- 非 root 账号 ----------
# **E2**：容器内 uid≠0 —— 后端具备执行 shell 命令的能力并挂载数据卷，
# 以 root 运行意味着「容器被突破 = 宿主机 root 级风险」。
# playwright 浏览器缓存落在该账号家目录（app 用户可写）。
RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --home-dir /home/app --create-home \
                --shell /usr/sbin/nologin app

# ---------- 系统依赖 ----------
# 1) Chromium 运行依赖（小红书 MCP Server / playwright）
# 2) cmake g++：编译 chromadb 等含 C 扩展的包
# 3) tzdata curl：时区与健康检查
RUN if [ -n "$APT_MIRROR" ]; then \
        sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
        sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list 2>/dev/null || true; \
    fi \
    && apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        tzdata \
        cmake \
        g++ \
        fonts-liberation \
        libasound2 \
        libatk-bridge2.0-0 \
        libatk1.0-0 \
        libatspi2.0-0 \
        libcups2 \
        libdbus-1-3 \
        libdrm2 \
        libgbm1 \
        libgtk-3-0 \
        libnspr4 \
        libnss3 \
        libwayland-client0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxkbcommon0 \
        libxrandr2 \
        xdg-utils \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && apt-get purge -y cmake g++ \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# ---------- Python 依赖（分层：requirements 变更才重建） ----------
# 只 COPY requirements（**不** COPY pyproject.toml —— 它声明了 pytest>=8，
# 进镜像会连带把测试框架装进生产环境）
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --upgrade pip -i "$PIP_INDEX_URL" \
    && pip install -r /app/requirements.txt -i "$PIP_INDEX_URL"

# Playwright 浏览器（体积较大、耗时较长，可用 --build-arg INSTALL_PLAYWRIGHT=false 跳过）
RUN if [ "$INSTALL_PLAYWRIGHT" = "true" ]; then \
        playwright install chromium ; \
        playwright install-deps chromium ; \
    else \
        echo "[skip] INSTALL_PLAYWRIGHT=$INSTALL_PLAYWRIGHT"; \
    fi

# ---------- 应用代码 ----------
COPY backend/app/      /app/app/
COPY backend/skills/   /app/skills/
# 只 COPY **运行时真正需要**的脚本（不复制 api_test.py / ui_smoke_test.py / conftest.py）：
#   __init__.py   → 让 `python -m scripts.xxx` 可用
#   migrate.py    → alembic 迁移（app/main.py 依赖）
#   ingest_data.py→ RAG 入库（entrypoint 调用）
COPY backend/scripts/__init__.py    /app/scripts/__init__.py
COPY backend/scripts/migrate.py     /app/scripts/migrate.py
COPY backend/scripts/ingest_data.py /app/scripts/ingest_data.py
# alembic.ini 必须一起复制：app/db/migrations/env.py 依赖它（fileConfig），
# 缺失 → 启动迁移 FileNotFoundError → 容器直接退出（实测：unhealthy 反复重启）
COPY backend/alembic.ini /app/alembic.ini
COPY deploy/backend/entrypoint.sh /app/entrypoint.sh

# ---------- 运行时目录骨架 ----------
# 真正的数据在容器内 /app/data 下，由 docker compose 的 named volume 挂载持久化：
#   data/milvus.db     → Milvus Lite 向量库（文件型数据库）
#   data/research/     → 深度研究任务记录 tasks.json + 报告
#   data/outputs|uploads|pdf|logs|browser_data → 产出 / 上传 / PDF / 日志 / 浏览器 Cookie
RUN chmod +x /app/entrypoint.sh \
    && mkdir -p /app/data/outputs /app/data/uploads /app/data/browser_data \
                /app/data/pdf /app/data/logs /app/data/research \
    && chown -R app:app /app

EXPOSE 8000

# 容器内健康检查（docker compose 的 healthcheck 也复用同一路径）
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=5 \
    CMD python -c "import urllib.request; raise SystemExit(0) if urllib.request.urlopen('http://127.0.0.1:${PORT:-8000}/api/v1/health', timeout=8).status == 200 else SystemExit(1)"

ENTRYPOINT ["/app/entrypoint.sh"]
# shell 形式：**遵守 $HOST / $PORT**（不再硬编码覆盖），与 HEALTHCHECK 同源。
# 此前硬编码 --port 8000 会覆盖 compose 的 PORT → 容器监听 8000 而健康检查探 $PORT
# → 改 PORT 后**永久 unhealthy**。
CMD uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"

# ---------- 运行身份：非 root ----------
USER app
