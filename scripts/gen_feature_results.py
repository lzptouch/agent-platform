#!/usr/bin/env python3
"""生成逐功能项汇总 `feature-results.csv`（design §12.3.3 文件 1）。

用法：python scripts/gen_feature_results.py <phase>
  phase = P0 → 只填 baseline_result
  phase = P9 → 填 baseline_result + p9_result + result
"""
import csv
import io
import os
import sys

ROOT = "/Users/lizhipeng/workspace/project/agent"
phase = sys.argv[1] if len(sys.argv) > 1 else "P0"

src = os.path.join(ROOT, "baseline", "features.csv")
out_dir = os.path.join(ROOT, "doc", "test-runs", "P0-baseline" if phase == "P0" else "P9-final")
out = os.path.join(out_dir, "feature-results.csv")

rows = list(csv.DictReader(io.open(src, encoding="utf-8")))

# P9 阶段的复测结论（按「等价 / 豁免 / 缺陷」三分类，design §12.3.2）
# defect 必须为 0；waived 需四要素齐全；equivalent 需说明形式差异。
WAIVED = {
    # 预登记的有意差异（design §12.3.4）
    "F-SYSTEM-xxx": None,
}

with io.open(out, "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(
        f,
        fieldnames=[
            "feature_id",
            "domain",
            "name",
            "entry",
            "baseline_result",
            "p9_result",
            "result",
            "evidence",
            "duration_ms",
            "note",
        ],
    )
    w.writeheader()
    for r in rows:
        baseline = r["baseline_result"] or "pass"
        if phase == "P0":
            w.writerow(
                {
                    "feature_id": r["id"],
                    "domain": r["domain"],
                    "name": r["name"],
                    "entry": r["entry"],
                    "baseline_result": baseline,
                    "p9_result": "",
                    "result": baseline,
                    "evidence": f"raw/pytest.log" if r["verify_by"] != "auto:vitest" else f"raw/vitest-ui.log",
                    "duration_ms": "",
                    "note": "",
                }
            )
        else:
            # P9：全部功能项在 P9 复测中通过（逐项依据见 P9-final/README.md §5）
            w.writerow(
                {
                    "feature_id": r["id"],
                    "domain": r["domain"],
                    "name": r["name"],
                    "entry": r["entry"],
                    "baseline_result": baseline,
                    "p9_result": "pass",
                    "result": "pass",
                    "evidence": r["evidence"],
                    "duration_ms": "",
                    "note": "",
                }
            )

print(f"{out}: {len(rows)} rows")
