#!/usr/bin/env bash
# =====================================================================
# 后端容器启动入口
#
# 职责：
#   1. 暴露面校验：HOST 非回环 + 未配置 AGENT_API_KEY → 拒绝启动（fail fast）
#   2. 保证运行时数据目录存在（挂载 named volume 后仍需兜底 mkdir）
#   3. 数据库迁移（**单点**：只在 entrypoint 执行；用数据卷锁文件避免多副本并发迁移）
#   4. 可选：首次启动时自动执行 RAG 入库（RUN_INGEST=true；失败即 exit 1）
#   5. exec 交给 CMD（uvicorn），保证容器 PID 1 收到信号可优雅退出
#
# 退出码：1 = 前置校验失败 / 迁移失败 / 入库失败（容器退出，由 restart 策略重试）
# =====================================================================
set -euo pipefail

echo "[entrypoint] agent Backend starting..."
echo "[entrypoint] python: $(python -V 2>&1) | workdir: $(pwd) | UTC now: $(date -u '+%Y-%m-%d %H:%M:%S')"

# ---------- 1. 暴露面校验（非回环 HOST 必须有鉴权）----------
# 背景：后端具备执行 shell 命令的能力（Skill / 代码执行链路）。
#       HOST=0.0.0.0 且未配 AGENT_API_KEY ⇒ /api/v1/** 对所有能访问该端口的人开放。
#       本容器不能改 backend/app/main.py，故在此处 fail fast
#       （与仓库整改计划 doc/plan/08 W7-05② / W10-01 对齐）。
HOST_BIND="${HOST:-0.0.0.0}"
PUBLISHED_BIND="${HOST_HTTP_BIND:-}"   # 宿主发布端口的绑定地址（compose 注入）
API_KEY="${AGENT_API_KEY:-}"

is_loopback() {
    case "$1" in
        127.0.0.1|localhost|::1|"") return 0 ;;
        127.*) return 0 ;;
        *) return 1 ;;
    esac
}

if ! is_loopback "$HOST_BIND" && [ -z "$API_KEY" ]; then
    if [ -n "$PUBLISHED_BIND" ] && is_loopback "$PUBLISHED_BIND"; then
        # 仅回环发布 ⇒ 外部够不到 API ⇒ 放行（但必须告警）
        echo "[entrypoint] ⚠ HOST=${HOST_BIND} 未配置 AGENT_API_KEY；宿主仅回环发布（HOST_HTTP_BIND=${PUBLISHED_BIND}）→ 外部不可达，放行" >&2
    elif [ "${AGENT_ALLOW_INSECURE:-0}" = "1" ]; then
        # 逃生开关（仓库整改计划 R-2D 规定）：强制放行 + 醒目告警
        echo "[entrypoint] ⚠⚠ HOST=${HOST_BIND} 未配置 AGENT_API_KEY 且 AGENT_ALLOW_INSECURE=1 → 强制放行（仅限内网 / 临时排查）" >&2
    else
        cat >&2 <<'EOF'
[entrypoint] ✗ 拒绝启动：HOST 非回环但未配置 AGENT_API_KEY
  症状：HOST=0.0.0.0（对外可达）且 AGENT_API_KEY 为空
        → /api/v1/** 对所有能访问该端口的人开放，且后端具备执行 shell 命令的能力。
  修复（二选一）：
    1) 开启鉴权：在 backend/.env 里设置 AGENT_API_KEY=<随机长串>，
       客户端请求需带 X-API-Key 头或 Authorization: Bearer。
    2) 收回暴露面：宿主发布端口绑回环（HOST_HTTP_BIND=127.0.0.1），
       或后端 HOST 改回 127.0.0.1（仅本机直连）。
  逃生开关（不推荐）：AGENT_ALLOW_INSECURE=1 —— 强制放行并打印告警。
EOF
        exit 1
    fi
fi

# ---------- 2. 运行时目录 ----------
for d in outputs uploads browser_data pdf logs research; do
    mkdir -p "/app/data/${d}"
done

# ---------- 3. 数据库迁移（单点执行）----------
# 迁移只在 entrypoint 触发一次（数据卷里的锁文件做幂等标记），
# 避免「每个 uvicorn 实例 / 每个副本」都在启动时抢 DDL 锁。
# 注意：app/main.py 的 lifespan 仍会调用 scripts.migrate —— alembic 已是 head → 空操作。
MIGRATE_LOCK="/app/data/.migrate.lock"
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    if [ -f "$MIGRATE_LOCK" ]; then
        echo "[entrypoint] 迁移已执行过（${MIGRATE_LOCK}），跳过"
    else
        echo "[entrypoint] 执行数据库迁移（单点）..."
        python -m scripts.migrate
        : > "$MIGRATE_LOCK"
    fi
else
    echo "[entrypoint] RUN_MIGRATIONS=false，跳过迁移"
fi

# ---------- 4. 可选：RAG 入库（失败即退出，避免「容器 healthy 但 RAG 为空」）----------
if [ "${RUN_INGEST:-false}" = "true" ]; then
    echo "[entrypoint] RUN_INGEST=true，开始 RAG 入库..."
    if ! python -m scripts.ingest_data; then
        printf 'failed\n' > /app/data/logs/ingest.status 2>/dev/null || true
        echo "[entrypoint] ✗ RAG 入库失败 —— 容器不再启动（RAG 链路会是空的）" >&2
        echo "[entrypoint]   排查：docker compose logs backend；修复后 docker compose up -d backend" >&2
        exit 1
    fi
    printf 'ok\n' > /app/data/logs/ingest.status 2>/dev/null || true
    echo "[entrypoint] RAG 入库完成"
fi

# ---------- 5. 打印关键配置（脱敏） ----------
echo "[entrypoint] MILVUS_DB_PATH=${MILVUS_DB_PATH:-data/milvus.db}"
echo "[entrypoint] RESEARCH_OUTPUT_DIR=${RESEARCH_OUTPUT_DIR:-data/research}"
echo "[entrypoint] HOST=${HOST_BIND} PORT=${PORT:-8000} | API key configured: $([ -n "${API_KEY:-}" ] && echo yes || echo no)"

exec "$@"
