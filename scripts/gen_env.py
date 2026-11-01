#!/usr/bin/env python3
"""生成 P0/P9 的 `environment.json` 与 `commands.txt`。"""
import io
import json
import os
import platform
import subprocess
from datetime import datetime, timezone

ROOT = "/Users/lizhipeng/workspace/project/agent"
RUNS = os.path.join(ROOT, "tests", "docs", "test-runs")


def sh(cmd: str) -> str:
    try:
        out = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=ROOT)
        return (out.stdout or out.stderr).strip().splitlines()[0]
    except Exception:
        return "unknown"


def collect() -> dict:
    return {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": "<人工填写>",
        "git_dirty": "true（改造进行中，未提交）",
        "os": {
            "platform": platform.system().lower(),
            "version": platform.mac_ver()[0],
            "arch": platform.machine(),
        },
        "node": sh("node -v"),
        "npm": sh("npm -v"),
        # **旧 Python 后端已退场**（design/16 §11.10 · P8-04）→ 记录最后版本备查
        "python": "已退场（P8-04）；P0/P9 回归时为 " + sh("python3 -V"),
        "electron": sh(
            "node -e \"console.log(require('./apps/desktop/node_modules/electron/package.json').version)\""
        ),
        "zod": sh(
            "node -e \"console.log(require('./apps/server/node_modules/zod/package.json').version)\""
        ),
        "fastify": sh(
            "node -e \"console.log(require('./apps/server/node_modules/fastify/package.json').version)\""
        ),
        "better_sqlite3": sh(
            "node -e \"console.log(require('./apps/server/node_modules/better-sqlite3/package.json').version)\""
        ),
        "data_snapshot": {
            "app_db": "测试会话临时目录（tests/unit/server/setup.ts）",
            "milvus_db": "3.5MB（改造后丢弃，Q4）",
            "pdf_count": 0,
        },
        "env_files": [".env（键名脱敏，未读取值）"],
        "external_apis": {
            "DASHSCOPE_API_KEY": "unset",
            "BOCHA_API_KEY": "unset",
            "SERPER_API_KEY": "unset",
            "GAODE_API_KEY": "unset",
            "OPENAI_API_KEY": "unset",
        },
    }


COMMANDS_P0 = """# P0 · 改造前全量基线测试复现命令（**历史记录**）
#
# ⚠️ **已不可复现**：旧 Python 后端（`backend/`）已按 design/16 §11.10 · P8-04
#    **退场并删除** → 下列命令所依赖的 `backend/.venv` 与 `backend/app` 均已不存在。
#    本文件保留**当时的执行方式**备查；**实际结果归档**见同目录 `raw/`。
#
# 每条命令可独立复制执行（工作目录：仓库根）

# ---------- B-1 后端单元/集成（pytest 695 例） ----------
cd backend
.venv/bin/python -m pytest tests/ -q --tb=short -p no:cacheprovider \\
  --timeout=90 --timeout-method=thread \\
  --json-report --json-report-file=../tests/docs/test-runs/P0-baseline/raw/pytest-report.json
cd ..

# ---------- B-2 前端单测（vitest 102 例） ----------
cd apps/ui
npx vitest run --reporter=verbose
cd ..

# ---------- B-3 桌面壳单测（vitest 60 例） ----------
cd apps/desktop
npx vitest run --reporter=verbose
cd ..

# ---------- B-5 接口冒烟（35 端点 / 38 断言） ----------
# 启动后端
cd backend
AGENT_DATA_DIR=/tmp/agent-pybase \\
  SKILLS_DIR=$(pwd)/../skills \\
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 18100
# 另开一个终端
node tests/scripts/ui/smoke.mjs http://127.0.0.1:18100
cd ..

# ---------- B-6 契约导出（98 路径 / 126 操作 + 22 表 DDL） ----------
cd backend
.venv/bin/python -c "
from app.main import app
import json
spec = app.openapi()
json.dump(spec, open('../contract/openapi.json','w'), ensure_ascii=False, indent=2, sort_keys=True)
print('paths', len(spec['paths']))
"
cd ..

# ---------- B-7 环境与结果归档 ----------
python3 scripts/gen_env.py
python3 scripts/gen_results.py \\
  tests/docs/test-runs/P0-baseline/raw/pytest-report.json \\
  tests/docs/test-runs/P0-baseline/results.csv P0
"""

COMMANDS_P9 = """# P9 · 改造后全量回归复现命令
# 每条命令可独立复制执行（工作目录：仓库根）

# ---------- R-1 TS 后端单测（vitest 56 例） ----------
cd apps/server
npx vitest run --reporter=verbose
cd ..

# ---------- R-2 前端单测（vitest 102 例） ----------
cd apps/ui
npx vitest run --reporter=verbose
cd ..

# ---------- R-3 桌面壳单测（vitest 62 例） ----------
cd apps/desktop
npx vitest run --reporter=verbose
cd ..

# ---------- R-4 旧 Python 后端回归（pytest 695 例） ----------
# ⚠️ **历史记录**：旧 Python 后端已按 design/16 §11.10 · P8-04 退场（`backend/` 已删）。
#    当时的执行方式（现已不可复现，结果归档见 raw/pytest-report.json）：
#      cd backend
#      .venv/bin/python -m pytest tests/ -q --timeout=90 --timeout-method=thread \
#        --json-report --json-report-file=../tests/docs/test-runs/P9-final/raw/pytest-report.json

# ---------- R-5 双 ABI 原生模块（Node 137 + Electron 130） ----------
node scripts/rebuild-native.mjs

# ---------- R-6 接口冒烟（35 端点 / 37 断言，TS 后端） ----------
cd apps/server
npm run build
AGENT_DATA_DIR=/tmp/agent-p9 \
  AGENT_DESKTOP=1 \
  AGENT_DESKTOP_TOKEN=p9token \
  AGENT_DESKTOP_BOOTSTRAP_NONCE=p9nonce \
  node dist/main.js > /tmp/agent-p9.log 2>&1 &
# 另开一个终端（端口取自握手行 AGENT_DESKTOP_READY）
PORT=$(grep -o '"port":[0-9]*' /tmp/agent-p9.log | head -1 | cut -d: -f2)
AGENT_DESKTOP_TOKEN=p9token node ../../../tests/scripts/ui/smoke.mjs "http://127.0.0.1:$PORT"
cd ..

# ---------- R-7 桌面端集成（Electron 壳 → TS sidecar） ----------
cd apps/desktop
npx electron .
cd ..

# ---------- R-8 打包 + 打包态自检 ----------
node scripts/ui/build-frontend.mjs
node scripts/build-desktop.mjs --platform mac --arch arm64
node tests/scripts/verify-desktop-package.mjs

# ---------- R-6 契约闸门（98 路径 / 126 操作零差异） ----------
cd apps/server
npx vitest run tests/contract.test.ts
cd ..

# ---------- 逐用例结果 CSV ----------
python3 scripts/gen_results.py \\
  tests/docs/test-runs/P9-final/raw/pytest-report.json \\
  tests/docs/test-runs/P9-final/results.csv P9
"""

for phase, commands in (("P0-baseline", COMMANDS_P0), ("P9-final", COMMANDS_P9)):
    d = os.path.join(RUNS, phase)
    os.makedirs(os.path.join(d, "raw"), exist_ok=True)
    env = collect()
    env["phase"] = phase
    with io.open(os.path.join(d, "environment.json"), "w", encoding="utf-8") as f:
        json.dump(env, f, ensure_ascii=False, indent=2)
    with io.open(os.path.join(d, "commands.txt"), "w", encoding="utf-8") as f:
        f.write(commands)
    print(f"{phase}: environment.json + commands.txt written")
