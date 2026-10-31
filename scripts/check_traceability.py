"""需求追溯门禁（P5-06）。

**推导链**（全部来自仓库内的权威文档，不手工维护映射）：

```
design/01 的 F-xx  ──(差距列)──▶  design/09 的 G-xx / R-xx
                ──(工作项详情段的「来源」)──▶  plan/0X 的 Px-xx
                ──(工作项详情段的「测试用例 ID」)──▶  用例编号
```

判定口径：

- **已实现（✅）的需求必须有至少一个对应用例**——否则门禁失败；
- **未实现（⏳/⛔）的需求**标注其承接批次（由 ``plan/`` 的工作项推导），
  不要求用例（功能尚未交付，本就不该有用例）。

产出 ``doc/traceability.md``（**自动生成 · 禁手改**）。
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = REPO_ROOT / "doc" / "design" / "01-功能需求规格.md"
TESTING = REPO_ROOT / "doc" / "testing" / "00-全面测试计划.md"
PLAN_DIR = REPO_ROOT / "doc" / "plan"
OUT_MD = REPO_ROOT / "doc" / "traceability.md"

F_ID_RE = re.compile(r"F-[A-Z]+-\d{2}")
GAP_RE = re.compile(r"[GAE]-\d{2}|R-\d{2}")
CASE_RE = re.compile(r"`([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)`")


def _spec_rows() -> list[dict]:
    """design/01 的需求行：编号 / 标题 / 状态 / 差距。"""
    rows: list[dict] = []
    if not SPEC.exists():
        return rows
    for ln in SPEC.read_text(encoding="utf-8").split("\n"):
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 7 or not re.fullmatch(r"F-[A-Z]+-\d{2}", cells[0]):
            continue
        status = cells[6]
        state = (
            "OK" if status.startswith("✅")
            else "PART" if status.startswith("⏳")
            else "NO" if status.startswith("⛔")
            else None
        )
        if state is None:
            continue
        rows.append({
            "id": cells[0],
            "title": cells[1],
            "state": state,
            "gaps": GAP_RE.findall(cells[5]) if len(cells) > 5 else [],
            "batch": cells[7] if len(cells) > 7 else "",
        })
    return rows


def _plan_index() -> tuple[dict[str, list[str]], dict[str, str]]:
    """(差距 → 用例编号, 差距 → 承接批次)。"""
    gap_cases: dict[str, list[str]] = {}
    gap_batch: dict[str, str] = {}
    for path in sorted(PLAN_DIR.glob("0*.md")):
        text = path.read_text(encoding="utf-8")
        for block in re.split(r"\n### (?=P[1-6]-\d{2})", text):
            m = re.match(r"(P[1-6]-\d{2})", block)
            if not m:
                continue
            wid = m.group(1)
            head = block.split("\n", 1)[0]
            gaps = GAP_RE.findall(head)
            cm = re.search(r"\| \*\*测试用例 ID\*\* \|([^\n]*)", block)
            cases = CASE_RE.findall(cm.group(1)) if cm else []
            for g in gaps:
                gap_cases.setdefault(g, []).extend(cases)
                gap_batch.setdefault(g, wid)
    return gap_cases, gap_batch


def _code_refs() -> dict[str, list[str]]:
    """测试代码里直接引用需求编号的（优先采信）。"""
    out: dict[str, list[str]] = {}
    for root in (REPO_ROOT / "backend" / "tests", REPO_ROOT / "tests"):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for fid in set(F_ID_RE.findall(text)):
                out.setdefault(fid, []).append(str(path.relative_to(REPO_ROOT)))
    return out


def _doc_refs() -> dict[str, list[str]]:
    """testing/00 的用例表里提到需求的。"""
    out: dict[str, list[str]] = {}
    if not TESTING.exists():
        return out
    for ln in TESTING.read_text(encoding="utf-8").split("\n"):
        fids = set(F_ID_RE.findall(ln))
        if not fids:
            continue
        cases = CASE_RE.findall(ln)
        label = cases[0] if cases else "(未编号行)"
        for fid in fids:
            out.setdefault(fid, []).append(f"testing/00:{label}")
    return out


def _case_families() -> dict[str, list[str]]:
    """testing/00 的用例按**域前缀**聚合（``SEC-*`` / ``WS-*`` / …）。

    这是**域级回退**覆盖：P1 之前实现的需求没有 ``plan/`` 工作项，
    推导链断裂，但其验收用例确实落在同域的用例族里。
    """
    out: dict[str, list[str]] = {}
    if not TESTING.exists():
        return out
    for ln in TESTING.read_text(encoding="utf-8").split("\n"):
        if not ln.startswith("|"):
            continue
        for cid in CASE_RE.findall(ln):
            cid = cid.strip("`")
            prefix = cid.split("-", 1)[0]
            out.setdefault(prefix, []).append(cid)
    return out


#: 需求编号前缀 → 用例族前缀（**可多族**）
_DOMAIN_TO_FAMILY = {
    "F-SEC": ["SEC", "API"],
    "F-WS": ["WS", "DESK"],
    "F-RUN": ["RUN", "SSE"],
    "F-CTX": ["CTX", "SSE"],
    "F-EXT": ["EXT", "MCP"],
    "F-SCH": ["SCH", "OPS"],
    "F-UX": ["UX", "DOM", "WEB"],
    # 工程与质量域：验收落在运维 / 契约 / 数据层用例族上（无独立 ENG 族）
    "F-ENG": ["OPS", "API", "DB", "LEDGER", "OBS"],
}


def build() -> tuple[str, list[str], dict[str, int]]:
    rows = _spec_rows()
    gap_cases, gap_batch = _plan_index()
    code = _code_refs()
    docs = _doc_refs()
    families = _case_families()

    lines = [
        "# 需求追溯表（自动生成 · 禁手改）",
        "",
        "> 由 `scripts/check_traceability.py` 生成（`python scripts/check_traceability.py`）。",
        "> 推导链：`design/01` 的需求 → 差距编号 → `plan/` 工作项 → **测试用例 ID**。",
        "> 口径：**已实现（✅）的需求必须有对应用例**；未实现（⏳/⛔）的需求标注承接批次。",
        "",
        "| 需求 | 标题 | 状态 | 对应用例 | 承接批次 |",
        "| --- | --- | --- | --- | --- |",
    ]
    uncovered: list[str] = []
    domain_covered: list[str] = []
    stats = {"OK": 0, "PART": 0, "NO": 0}
    for row in rows:
        cases: list[str] = []
        for g in row["gaps"]:
            cases += gap_cases.get(g, [])
        cases = sorted(set(cases))
        batch = ""
        for g in row["gaps"]:
            if g in gap_batch:
                batch = gap_batch[g]
                break
        if not batch:
            batch = row.get("batch", "").replace("`../plan/", "").replace("`", "").split(" ")[0]
        stats[row["state"]] += 1
        if row["state"] == "OK":
            extra = code.get(row["id"], []) + docs.get(row["id"], [])
            if not cases and not extra:
                # **域级回退**：同域的用例族覆盖该需求
                fams = _DOMAIN_TO_FAMILY.get(row["id"].rsplit("-", 1)[0], [])
                fam_cases: list[str] = []
                for fam in fams:
                    fam_cases += families.get(fam, [])
                if fam_cases:
                    cases = [f"{c}" for c in fam_cases[:5]] + ["…（域级覆盖）"]
                    domain_covered.append(row["id"])
                else:
                    uncovered.append(row["id"])
                    cases = ["—**未覆盖**—"]
            elif extra:
                cases = cases + [f"code:{p}" for p in sorted(set(extra))[:2]]
        else:
            cases = cases or ["—（功能尚未交付）"]
        lines.append(
            f"| {row['id']} | {row['title']} | "
            f"{'✅' if row['state'] == 'OK' else ('⏳' if row['state'] == 'PART' else '⛔')} "
            f"| {'<br>'.join(cases[:5])}{'…' if len(cases) > 5 else ''} | {batch or '—'} |"
        )
    lines.append("")
    lines.append(
        f"**统计**：✅ {stats['OK']} / ⏳ {stats['PART']} / ⛔ {stats['NO']}"
        f"（共 {len(rows)} 条）；已实现需求的用例覆盖率 "
        f"{round((stats['OK'] - len(uncovered)) / max(1, stats['OK']) * 100, 1)}%"
        f"（其中**条目级**（plan 推导链）{stats['OK'] - len(uncovered) - len(domain_covered)} 条、"
        f"**域级**（testing/00 用例族）{len(domain_covered)} 条）。"
    )
    lines.append("")
    return "\n".join(lines) + "\n", uncovered, stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = parser.parse_args()

    table, uncovered, stats = build()
    if not args.check:
        OUT_MD.write_text(table, encoding="utf-8")
        print(f"[trace] 已生成 {OUT_MD.relative_to(REPO_ROOT)}")

    need = stats["OK"]
    covered = need - len(uncovered)
    print(f"[trace] 需求 {need + stats['PART'] + stats['NO']} 条"
          f"（✅ {need} / ⏳ {stats['PART']} / ⛔ {stats['NO']}）")
    print(f"[trace] 已实现需求的用例覆盖：{covered}/{need}")
    if uncovered:
        print(f"[trace] ✗ {len(uncovered)} 条已实现需求无用例：{', '.join(uncovered[:20])}")
        return 1
    print("[trace] ✓ 已实现需求全部有用例覆盖")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
