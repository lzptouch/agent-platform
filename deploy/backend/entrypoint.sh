#!/usr/bin/env bash
# =====================================================================
# 后端容器启动入口
#
# 职责：
#   1. 保证运行时数据目录存在（挂载 named volume 后仍需兜底 mkdir）
#   2. 可选：首次启动时自动执行 RAG 入库（RUN_INGEST=true）
#   3. exec 交给 CMD（uvicorn），保证容器 PID 1 收到信号可优雅退出
# =====================================================================
set -euo pipefail

echo "[entrypoint] Agent Platform Backend starting..."
echo "[entrypoint] python: $(python -V 2>&1) | workdir: $(pwd) | UTC now: $(date -u '+%Y-%m-%d %H:%M:%S')"

# ---------- 运行时目录 ----------
for d in outputs uploads browser_data pdf logs research; do
    mkdir -p "/app/data/${d}"
done

# ---------- 可选：RAG 入库（需要 DASHSCOPE_API_KEY 与 backend/data/pdf 下的 PDF） ----------
if [ "${RUN_INGEST:-false}" = "true" ]; then
    echo "[entrypoint] RUN_INGEST=true，开始 RAG 入库..."
    python -m scripts.ingest_data || echo "[entrypoint] 入库失败（忽略），可稍后手动执行：docker compose exec backend python -m scripts.ingest_data"
fi

# ---------- 打印关键配置（脱敏） ----------
echo "[entrypoint] MILVUS_DB_PATH=${MILVUS_DB_PATH:-data/milvus.db}"
echo "[entrypoint] RESEARCH_OUTPUT_DIR=${RESEARCH_OUTPUT_DIR:-data/research}"
echo "[entrypoint] API key configured: $([ -n "${DASHSCOPE_API_KEY:-}" ] && echo yes || echo no)"

exec "$@"
