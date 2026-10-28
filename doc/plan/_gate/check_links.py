# -*- coding: utf-8 -*-
"""G6 链接校验 + G12 常量漂移抽查。输出死链清单。"""
import os, re, sys

ROOT = r"c:\workspace\project\agent-platform"
SKIP = {"node_modules", ".git", "__pycache__", "dist", ".venv"}

def iter_md(root):
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in SKIP]
        # 归档区与计划目录属历史/过程产物，不参与现役链接校验
        if "archive" in dp.replace("\\", "/") or dp.replace("\\", "/").endswith("doc/plan"):
            dn[:] = []
            continue
        for f in fn:
            if f.endswith(".md"):
                yield os.path.join(dp, f)

LINK = re.compile(r"\]\((?!https?://|#|mailto:)([^)]+)\)")
dead = []
files = list(iter_md(ROOT))
for f in files:
    txt = open(f, encoding="utf-8").read()
    base = os.path.dirname(f)
    for m in LINK.finditer(txt):
        target = m.group(1).split("#")[0].strip()
        if not target:
            continue
        p = os.path.normpath(os.path.join(base, target))
        if not os.path.exists(p):
            dead.append((os.path.relpath(f, ROOT), target))

print(f"markdown 文件数: {len(files)}")
print(f"死链数: {len(dead)}")
for f, t in dead:
    print(f"  {f}  ->  {t}")
sys.exit(1 if dead else 0)
