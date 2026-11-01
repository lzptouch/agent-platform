#!/usr/bin/env python3
"""文档路径门禁：**当前实现**文档不得引用**已删除**的实现路径。

**为什么需要（2026-11-01）**：单运行时改造删除了 `backend/`（Python）与 `frontend/`
（已迁入 `apps/`），Web / Docker 形态也一并退场。文档里残留的旧路径会让
「按文档找代码」的人**找不到文件**，也会让读者以为旧实现还在。

**豁免**：🕘 **历史归档**文档（审计报告 / 整改计划 / 实现交付记录）**保留**旧路径
—— 它们记录的是「当时的事实」，改写等于篡改历史。

用法：python3 scripts/check_doc_paths.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "doc"

#: 🕘 历史归档文档 —— 豁免
HISTORICAL = {
    "analysis/18_全面代码审计报告.md",
    "analysis/19_二次全面审计报告.md",
    "plan/07-全面代码审计整改计划.md",
    "plan/08-二次全面审计整改计划.md",
    "design/08-实现交付记录.md",
    "analysis/13_桌面端现状盘点与需求论证.md",
    # design/16 是**方案**：正文记录「改造前基线」与「删除清单」→ 有意保留旧路径
    "design/16-桌面一体化改造方案与实施计划.md",
}

#: 已删除的实现路径（不得出现在「当前实现」文档里）
DEAD_PATTERNS: list[tuple[str, str]] = [
    (r"\bbackend/app/", "旧 Python 后端目录（已迁至 apps/server/src/）"),
    (r"\bbackend/tests/", "旧 Python 测试目录（已迁至 apps/server/tests/）"),
    (r"\bbackend/\.venv", "旧 Python 虚拟环境（已退场）"),
    (r"\bbackend/Dockerfile", "旧 Docker 构建文件（形态已退场）"),
    (r"\bbackend/requirements", "旧 Python 依赖清单（已退场）"),
    (r"\bbackend/pyproject\.toml", "旧 Python 工程配置（已退场）"),
    (r"\bfrontend/desktop/src", "旧桌面壳源码目录（已迁至 apps/desktop/src/）"),
    (r"\bfrontend/web/vue-element-plus", "旧前端工程目录（已迁至 apps/ui/）"),
    (r"\bfrontend/scripts/build-frontend", "旧前端构建脚本（已迁至 scripts/ui/）"),
    (r"\bdocker-compose\.yml\b", "Docker Compose（形态已退场）"),
    (r"\bmilvus-lite\b", "Milvus Lite（向量层已改为进程内 SQLite）"),
    (r"\bapp\.main:app\b", "FastAPI 应用入口（后端已改 TypeScript）"),
]

#: 允许出现的「说明性」上下文（横幅里的对照表、状态说明）
ALLOW_CONTEXT = re.compile(
    r"(状态横幅|已退场|已迁至|已迁到|迁至|迁到|改造前|改造后|对照|→|退场|历史|"
    r"原 `|原目录|原路径|此前|原先|曾经|不再|已删除|删除|已替换|已改为|改为|"
    r"基线代码|2026-11-01|2026-10|维持|无 milvus|零外部依赖|删除项|删除清单)"
)


def main() -> int:
    problems: list[str] = []
    checked = 0

    for path in sorted(DOCS.rglob("*.md")):
        rel = path.relative_to(DOCS).as_posix()
        if rel in HISTORICAL:
            continue
        # P9 的报告是「改造后」的记录，允许提及旧路径
        if rel.startswith("test-runs/"):
            continue
        text = path.read_text(encoding="utf-8")
        checked += 1
        for lineno, line in enumerate(text.split("\n"), start=1):
            if ALLOW_CONTEXT.search(line):
                continue
            for pattern, why in DEAD_PATTERNS:
                if re.search(pattern, line):
                    problems.append(
                        f"{rel}:{lineno}  {why}\n        {line.strip()[:140]}"
                    )

    if problems:
        print("❌ 当前实现文档引用了**已删除**的实现路径：\n")
        for p in problems:
            print(f"  {p}")
        print(f"\n共 {len(problems)} 处（已扫描 {checked} 个文档）")
        print(
            "\n提示：若这是**有意**的对照说明，请在同一行加上「已退场 / 已迁至 / 改造前」等词；"
            "\n      若属历史归档文档，请加入 scripts/check_doc_paths.py 的 HISTORICAL 集合。"
        )
        return 1

    print(f"✅ 当前实现文档未引用已删除的实现路径（已扫描 {checked} 个文档）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
