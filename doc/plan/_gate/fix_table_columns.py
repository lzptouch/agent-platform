"""修正 markdown 表格的列数一致性：表头与分隔行按数据行的列数对齐。

用法：python doc/plan/_gate/fix_table_columns.py [文件...]
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

STATUS_HEADER = "状态（2026-10-28 按当前代码复核）"


def cells(line: str) -> list[str]:
    r"""拆一行的单元格（**不拆转义竖线** ``\|``）。"""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    out: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            buf.append("|")      # 转义竖线 → 内容的一部分
            i += 2
            continue
        if ch == "|":
            out.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    out.append("".join(buf).strip())
    return out


def fix(path: Path) -> int:
    lines = io.open(path, encoding="utf-8").read().split("\n")
    out: list[str] = []
    i = 0
    fixed = 0
    while i < len(lines):
        line = lines[i]
        # 找表格：当前行是表头，下一行是分隔行
        if (
            line.strip().startswith("|")
            and i + 1 < len(lines)
            and re.match(r"^\|[\s\-:|]+\|$", lines[i + 1].strip())
        ):
            header = cells(line)
            sep = cells(lines[i + 1])
            # 收集数据行
            j = i + 2
            data: list[str] = []
            while j < len(lines) and lines[j].strip().startswith("|"):
                data.append(lines[j])
                j += 1
            widths = [len(cells(d)) for d in data] or [len(header)]
            target = max(widths)
            if len(header) > target:
                # 表头多列（此前误加的状态列）→ 去掉多余尾部
                header = header[:target]
                fixed += 1
            elif target > len(header):
                # 表头缺列 → 补状态列
                header = header + [STATUS_HEADER] * (target - len(header))
                fixed += 1
            if len(sep) != target:
                sep = ["---"] * target
                fixed += 1
            out.append("| " + " | ".join(header) + " |")
            out.append("| " + " | ".join(sep) + " |")
            out.extend(data)
            i = j
            continue
        out.append(line)
        i += 1
    if fixed:
        io.open(path, "w", encoding="utf-8").write("\n".join(out))
    return fixed


def main() -> int:
    targets = [Path(a) for a in sys.argv[1:]]
    if not targets:
        targets = [
            p for d in ("analysis", "design", "plan", "knowledge")
            for p in (ROOT / "doc" / d).glob("*.md")
        ]
        targets.append(ROOT / "doc" / "README.md")
    total = 0
    for p in targets:
        if not p.is_file():
            continue
        n = fix(p)
        if n:
            print("fixed", p.relative_to(ROOT), n)
            total += n
    print("total fixes:", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
