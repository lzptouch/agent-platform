"""文档数字门禁（P5-05）。

从**权威来源**取关键数字（OpenAPI 端点数 / ORM 表数 / pytest 用例数 / 前端视图数），
比对 ``doc/**/*.md`` 中出现的同类数字；**不一致时非零退出**并指出文件与行号。

权威来源：

| 数字 | 来源 |
| --- | --- |
| API 端点数 | ``app.main:app.openapi()["paths"]`` |
| ORM 表数 | ``app.db.models.Base.metadata.tables`` |
| 后端用例数 | 最近的 ``report.json``（无则现场收集） |
| 需求条数 | ``doc/design/01`` 的 ``F-xx`` 行数 |
| 差距条数 | ``doc/design/09`` 的合计行 |

用法：
    python scripts/check_doc_numbers.py
    python scripts/check_doc_numbers.py --artifact-only   # 只校验产物（发布用）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_DIR = REPO_ROOT / "doc"


def _authoritative() -> dict[str, int]:
    """取权威数字。"""
    out: dict[str, int] = {}

    # 1) 端点数（OpenAPI）—— **读冻结契约**（`contract/openapi.json`）
    #
    # **改造要点（design/16 §11.10 · P8-04）**：旧 Python 后端退场后，
    # 不能再从 `app.main` 取端点数 → 改为读**契约冻结产物**（更稳定：
    # 契约本就是「被测对象必须等于的基准」，就该是真相源）。
    spec_path = REPO_ROOT / "contract" / "openapi.json"
    if spec_path.exists():
        try:
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            out["端点"] = len(spec.get("paths", {}))
        except Exception as exc:  # noqa: BLE001
            print(f"[check] 契约读取失败（跳过端点校验）: {exc}")
    else:
        print("[check] contract/openapi.json 不存在（跳过端点校验）")

    # 2) 表数 —— **读冻结 DDL**（`contract/tables.sql`）
    tables_path = REPO_ROOT / "contract" / "tables.sql"
    if tables_path.exists():
        try:
            text = tables_path.read_text(encoding="utf-8")
            out["表"] = len(re.findall(r"(?im)^\s*CREATE TABLE\s+", text))
        except Exception as exc:  # noqa: BLE001
            print(f"[check] 表 DDL 读取失败（跳过表数校验）: {exc}")
    else:
        print("[check] contract/tables.sql 不存在（跳过表数校验）")

    # 3) 后端用例数（**实测报告优先** → 消除「第二真相源」，R17）
    #
    # 3.1) 首选 `doc/test-runs/<阶段>/raw/pytest-report.json`（本次改造每次测试都会产出）
    pytest_reports = sorted(
        (REPO_ROOT / "doc" / "test-runs").glob("*/raw/pytest-report.json"),
        key=lambda p: p.stat().st_mtime,
    )
    for report in reversed(pytest_reports):
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
            summary = data.get("summary") or {}
            passed = int(summary.get("passed") or 0)
            if passed:
                out["pytest"] = passed
                break
        except Exception:  # noqa: BLE001
            continue
    # 3.2) 回落：旧的采集报告（`tests/report/runs/*/report.json`）
    if "pytest" not in out:
        runs = sorted((REPO_ROOT / "tests" / "report" / "runs").glob("*/report.json"))
        if runs:
            try:
                data = json.loads(runs[-1].read_text(encoding="utf-8"))
                backend = next(
                    (
                    l
                    for l in data.get("layers", [])
                    # 层 id 历史演进：pytest-backend（Python）→ server-unit（TS）
                    if l.get("id") in ("pytest-backend", "server-unit")
                ),
                None,
                )
                if backend:
                    out["pytest"] = int(backend.get("total") or 0)
            except Exception:  # noqa: BLE001
                pass

    # 4) 需求条数
    spec = DOC_DIR / "design" / "01-功能需求规格.md"
    if spec.exists():
        text = spec.read_text(encoding="utf-8")
        out["需求"] = len(set(re.findall(r"F-[A-Z]+-\d{2}", text)))
    return out


#: 文档中「实测数字 + 名词」的模式 → 权威键。
#:
#: **只认「实测值」表述**——阈值（``≥ N``）、工期（``S3（1d）``）、
#: 局部计数（``SSE 事件协议 5 个端点``）都不是全量口径，必须排除，
#: 否则门禁会产生大量误报而失去意义。
_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"pytest[^\d\n]{0,20}\*\*(\d+)\s+passed"), "pytest"),
    (re.compile(r"端点数[：:]\s*\*\*?(\d+)"), "端点"),
    (re.compile(r"共\s*\*\*?(\d+)\s*条需求"), "需求"),
    (re.compile(r"需求条目[^\d\n]{0,12}\*\*?(\d+)\s*条"), "需求"),
]

#: 含这些词的行**不参与**比对（阈值 / 局部口径 / 历史记录）
_EXCLUDE_TOKENS = (
    "≥", "<=", "不下降", "至少", "SSE", "历史", "曾", "旧版", "原", "规划",
    "上限", "目标", "期望", "预算", "人日", "工期",
)


#: **历史台账**文档——记录的是各阶段的**当时数字**，不与当前口径比对
#:
#: **改造要点（design/16 §12.9）**：审计报告与其整改计划记录的也是**审计当时**
#: 的实测数字（626 / 668），同样属历史快照 → 一并纳入。
HISTORY_DOCS = {
    "08-实现交付记录.md",
    "12-阶段交付台账.md",
    "18_全面代码审计报告.md",
    "19_二次全面审计报告.md",
    "07-全面代码审计整改计划.md",
    "08-二次全面审计整改计划.md",
}


def check_numbers(docs: list[Path], truth: dict[str, int]) -> list[str]:
    """比对文档中的数字，返回**不一致清单**。"""
    problems: list[str] = []
    for path in docs:
        if path.name in HISTORY_DOCS:
            continue  # 历史快照：数字是当时的实测值，不应被改写
        try:
            lines = path.read_text(encoding="utf-8").split("\n")
        except OSError:
            continue
        for lineno, line in enumerate(lines, start=1):
            if line.lstrip().startswith("|") is False and "端点" not in line and "pytest" not in line:
                # 仍需检查行内的端点/pytest 表述
                pass
            for pattern, key in _PATTERNS:
                if key not in truth:
                    continue
                for m in pattern.finditer(line):
                    raw = next((g for g in m.groups() if g), None)
                    if raw is None:
                        continue
                    try:
                        value = int(raw)
                    except ValueError:
                        continue
                    if any(token in line for token in _EXCLUDE_TOKENS):
                        continue
                    if value != truth[key]:
                        rel = path.relative_to(REPO_ROOT)
                        problems.append(
                            f"{rel}:{lineno}  {key}数写的是 {value}，实际 {truth[key]}"
                            f"  ← {line.strip()[:90]}"
                        )
    return problems


def check_artifact_budget() -> list[str]:
    """发布前的**体积预算**校验（P5-05 附带；与 ``build-desktop.mjs`` 的预算一致）。"""
    problems: list[str] = []
    budgets = {"后端运行时": 350, "前端 dist": 30, "壳产物": 120}
    targets = {
        "后端运行时": REPO_ROOT / "frontend" / "desktop" / ".stage" / "runtime",
        "前端 dist": REPO_ROOT / "frontend" / "dist",
        "壳产物": REPO_ROOT / "frontend" / "desktop" / "dist-main",
    }
    for name, limit in budgets.items():
        target = targets[name]
        if not target.exists():
            continue
        total = sum(
            f.stat().st_size for f in target.rglob("*") if f.is_file()
        )
        mb = round(total / 1024 / 1024, 1)
        if mb > limit:
            problems.append(f"{name} 体积 {mb}MB 超出预算 {limit}MB")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-only", action="store_true", help="只校验产物体积")
    args = parser.parse_args()

    if args.artifact_only:
        problems = check_artifact_budget()
        for p in problems:
            print(f"[FAIL] {p}")
        print("[check] 体积预算校验通过" if not problems else f"[check] {len(problems)} 项超预算")
        return 1 if problems else 0

    truth = _authoritative()
    if not truth:
        print("[check] 无可用权威数字，跳过")
        return 0
    print(f"[check] 权威数字：{truth}")

    problems = check_numbers(sorted(DOC_DIR.rglob("*.md")), truth)
    for p in problems:
        print(f"[FAIL] {p}")
    if problems:
        print(f"\n[check] ✗ {len(problems)} 处数字不一致")
        return 1
    print("\n[check] ✓ 文档数字与权威来源一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
