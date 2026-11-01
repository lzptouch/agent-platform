"""端到端结果汇总入口（P5-01 · 产出 `report.json` + `index.md` + `junit.xml` + `classify.json`）。

实现下沉到 ``tests/common/report.py`` 与 ``tests/common/classify.py``（可被 CI 直接 import）。

用法：
    python3 scripts/collect_test_report.py
    python3 scripts/collect_test_report.py --layer desktop

**改造要点（design/16 §11.10 · P8-04）**：旧 Python 后端退场 →
``pytest-backend`` 层改为 **TS 后端 vitest**；E2E 层改用**独立 venv**
（``.venv-e2e/``，仅 pytest + playwright）。

产物：``tests/report/runs/<runId>-<commit>-<platform>-<arch>/``
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tests"))

from common.report import (  # noqa: E402
    LayerResult,
    archive_legacy_reports,
    build_classify_for,
    build_report,
    write_report,
)

RUNS_ROOT = REPO_ROOT / "tests" / "report" / "runs"

#: 层定义（对应 ``doc/testing/00`` §11.1 的 L0~L5）
#:
#: **改造要点（design/16 §11.10 · P8-04）**：旧 Python 后端（`backend/`）退场：
#: - ``pytest-backend`` → ``server-unit``（**TS 后端 vitest**）
#: - ``web-e2e`` → **删除**（Web 形态不存在）
#: - ``native-layer`` → **删除**（测的是 Python 执行器内部；等价能力已进
#:   `apps/server/tests/domain.test.ts` 的沙箱用例）
#: - ``deploy-layer`` → **删除**（Docker 形态不存在）
#: - E2E 层统一用**独立 venv**（``.venv-e2e/``），不依赖 `backend/requirements-dev.txt`
E2E_PY = str(
    REPO_ROOT
    / (".venv-e2e/bin/python" if os.name != "nt" else ".venv-e2e/Scripts/python.exe")
)

LAYERS: list[dict] = [
    {
        "id": "server-unit", "title": "TS 后端契约与单元", "runtime": "node",
        "command": ["npx", "vitest", "run", "--reporter=verbose"],
        "cwd": "apps/server",
    },
    {
        "id": "ui-unit", "title": "前端单测", "runtime": "node",
        "command": ["npx", "vitest", "run", "--reporter=verbose"],
        "cwd": "apps/ui",
    },
    {
        "id": "shell-unit", "title": "桌面壳单测", "runtime": "node",
        "command": ["npx", "vitest", "run", "--reporter=verbose"],
        "cwd": "apps/desktop",
    },
    {
        "id": "desktop-e2e", "title": "桌面端到端", "runtime": "desktop",
        "command": [E2E_PY, "-m", "pytest", "tests/desktop", "-q"],
        "cwd": ".",
    },
    {
        "id": "packaged-e2e", "title": "打包态端到端", "runtime": "packaged",
        "command": [E2E_PY, "-m", "pytest", "tests/packaged", "-q"],
        "cwd": ".",
    },
    {
        "id": "visual-layer", "title": "视觉基线", "runtime": "visual",
        "command": [E2E_PY, "-m", "pytest", "tests/visual", "-q"],
        "cwd": ".",
    },
]

_PASSED_RE = re.compile(r"(\d+) passed")
_FAILED_RE = re.compile(r"(\d+) failed")
_SKIPPED_RE = re.compile(r"(\d+) skipped")
_FAILED_ID_RE = re.compile(r"^FAILED\s+(\S+)", re.M)


def _run_layer(layer: dict) -> LayerResult:
    started = time.monotonic()
    # **每层用独立数据库**——共用开发库会造成**跨层干扰**
    # （一层的用例改动数据后，另一层的断言就可能失败）。
    db_path = REPO_ROOT / "tests" / ".layer_dbs" / f"layer-{layer['id']}.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(db_path) + suffix)
        if candidate.exists():
            candidate.unlink()
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite:///{db_path}"

    proc = subprocess.run(
        layer["command"],
        cwd=str(REPO_ROOT / layer.get("cwd", ".")),
        capture_output=True, text=True, timeout=3600,
        env=env,
    )
    out = (proc.stdout or "") + (proc.stderr or "")

    def _count(pattern: re.Pattern) -> int:
        m = pattern.search(out)
        return int(m.group(1)) if m else 0

    passed = _count(_PASSED_RE)
    failed = _count(_FAILED_RE)
    skipped = _count(_SKIPPED_RE)
    failed_ids = _FAILED_ID_RE.findall(out)
    failed_cases = [
        {
            "id": cid,
            "title": cid,
            "errorCode": "E_ASSERT_MISMATCH",
            "message": _first_failure_line(out, cid),
            "firstFailingStep": "assert",
            "evidence": [f"logs/{layer['id']}.log"],
            "suspect": _suspect_of(layer["runtime"]),
            "attempts": 1,
        }
        for cid in failed_ids
    ]
    return LayerResult(
        id=layer["id"],
        title=layer["title"],
        command=layer["command"],
        exit_code=proc.returncode,
        total=passed + failed + skipped,
        passed=passed,
        failed=failed,
        skipped=skipped,
        duration_ms=int((time.monotonic() - started) * 1000),
        runtime=layer["runtime"],
        failed_cases=failed_cases,
        stdout_tail=out.splitlines()[-25:],
    )


def _first_failure_line(out: str, case_id: str) -> str:
    for ln in out.splitlines():
        if case_id in ln and ("AssertionError" in ln or "Error" in ln or "assert" in ln):
            return ln.strip()[:300]
    return case_id


def _suspect_of(runtime: str) -> str:
    """失败可疑层（与 `tests/common/classify.py` 的归类口径对齐）。

    **改造要点（design/16 §11.10 · P8-04）**：`backend` → `server`
    （TS 后端）；`web` 层已删除。
    """
    return {
        "node": "server",
        "server": "server",
        "desktop": "shell",
        "packaged": "packaging",
        "visual": "frontend",
    }.get(runtime, "unknown")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layer", action="append", help="只跑指定层（可重复）")
    parser.add_argument("--no-archive", action="store_true", help="不归档旧的裸 report-*.md")
    args = parser.parse_args()

    layers_spec = LAYERS
    if args.layer:
        wanted = set(args.layer)
        layers_spec = [l for l in LAYERS if l["id"] in wanted]
        if not layers_spec:
            print(f"未知层: {args.layer}（可选: {[l['id'] for l in LAYERS]}）")
            return 2

    if not args.no_archive:
        archived = archive_legacy_reports(REPO_ROOT)
        if archived:
            print(f"[collect] 已归档 {archived} 个旧裸 report-*.md → tests/report/archive/")

    started_at = datetime.now(timezone.utc).isoformat()
    results: list[LayerResult] = []
    for layer in layers_spec:
        print(f"[collect] {layer['id']} …", flush=True)
        res = _run_layer(layer)
        results.append(res)
        print(
            f"[collect] {layer['id']}: passed={res.passed} failed={res.failed} "
            f"skipped={res.skipped}",
            flush=True,
        )

    report = build_report(results, runtime=results[0].runtime if results else "web",
                          started_at=started_at)
    classify = build_classify_for(report)

    import platform as _platform

    out_dir = RUNS_ROOT / (
        f"{report['runId']}-{report['env']['gitCommit']}-"
        f"{_platform.system().lower()}-{_platform.machine().lower()}"
    )
    write_report(report, out_dir, classify=classify)

    print(f"\n[collect] 工件目录：{out_dir}")
    print(
        f"[collect] 合计 {report['summary']['total']}"
        f"（passed {report['summary']['passed']} / failed {report['summary']['failed']}"
        f" / skipped {report['summary']['skipped']}）"
    )
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
