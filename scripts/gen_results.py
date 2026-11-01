#!/usr/bin/env python3
"""从 pytest JSON 报告生成逐用例 `results.csv`（design/16 §12.4.3 字段）。

用法：python scripts/gen_results.py <pytest-report.json> <out.csv> <phase>
"""
import csv
import io
import json
import sys

src, out, phase = sys.argv[1], sys.argv[2], sys.argv[3]
data = json.load(open(src, encoding="utf-8"))

rows = []
for test in data.get("tests", []):
    outcome = test.get("outcome", "unknown")
    result = {
        "passed": "pass",
        "failed": "fail",
        "skipped": "skip",
        "error": "fail",
    }.get(outcome, "known_fail")
    call = (test.get("call") or {})
    cr = call.get("crash") or {}
    if cr.get("wasxfail"):
        result = "known_fail"
    longrepr = call.get("longrepr") or cr.get("longrepr") or ""
    rows.append(
        {
            "case_id": test.get("nodeid", ""),
            "layer": "L2",
            "suite": "unit",
            "name": test.get("nodeid", "").split("::")[-1],
            "expected": "用例断言全部通过",
            "actual": "通过" if result == "pass" else ("跳过" if result == "skip" else "失败"),
            "result": result,
            "duration_ms": int((call.get("duration") or 0) * 1000),
            "evidence": f"raw/{phase}-pytest.log",
            "feature_id": "",
            "note": "" if result == "pass" else str(longrepr)[:400],
        }
    )

with io.open(out, "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(
        f,
        fieldnames=[
            "case_id",
            "layer",
            "suite",
            "name",
            "expected",
            "actual",
            "result",
            "duration_ms",
            "evidence",
            "feature_id",
            "note",
        ],
    )
    w.writeheader()
    w.writerows(rows)

from collections import Counter

print(f"{out}: {len(rows)} rows", Counter(r["result"] for r in rows))
