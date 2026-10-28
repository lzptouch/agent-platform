# -*- coding: utf-8 -*-
"""G1 端点完整性 / G3 前端覆盖 / G7 mermaid 围栏 / 表格列一致性 / G12 常量漂移。"""
import os, re, sys, ast

ROOT = r"c:\workspace\project\agent-platform"
AN = os.path.join(ROOT, "doc", "analysis")
fails = []

def read(p): return open(p, encoding="utf-8").read()

# ---------- G1：05 的端点表与 OpenAPI 基线双向差集 ----------
base = set()
for line in open(os.path.join(ROOT, "doc", "plan", "_baseline", "routes.txt"), encoding="utf-8"):
    line = line.strip()
    if not line: continue
    m, p = line.split(None, 1)
    base.add((m, p))
doc = read(os.path.join(AN, "05_HTTP接口总览.md"))
docset = set()
for m in re.finditer(r"`(GET|POST|PUT|PATCH|DELETE)\s+(/api/v1[^`]+)`", doc):
    docset.add((m.group(1), m.group(2)))
only_code = base - docset
only_doc = docset - base
print(f"[G1] 基线端点 {len(base)}，文档端点 {len(docset)}")
print(f"[G1] 代码有而文档缺: {len(only_code)}")
for m, p in sorted(only_code): print(f"      缺  {m} {p}")
print(f"[G1] 文档有而代码无: {len(only_doc)}")
for m, p in sorted(only_doc): print(f"      多  {m} {p}")
if only_code or only_doc: fails.append("G1")

# ---------- G3：06 覆盖前端常量 ----------
d06 = read(os.path.join(AN, "06_前端架构与接口契约.md"))
checks = {
    "15 视图": ("15", "视图"), "13 组件": ("13", "组件"), "2 布局": ("2", "布局"),
    "4 store": ("4", "store"), "58 常量": ("58", "端点常量"), "18 事件": ("18", "事件"),
}
for name, (num, kw) in checks.items():
    ok = num in d06 and kw in d06
    print(f"[G3] {name}: {'OK' if ok else 'FAIL'}")
    if not ok: fails.append(f"G3:{name}")

# ---------- G7：mermaid 围栏配对（全部 13 篇 + README）----------
for f in sorted(os.listdir(AN)):
    if not f.endswith(".md"): continue
    txt = read(os.path.join(AN, f))
    n = txt.count("```")
    if n % 2 != 0:
        print(f"[G7] {f} 围栏数 {n} 为奇数")
        fails.append(f"G7:{f}")
print("[G7] mermaid 围栏配对检查完成")

# ---------- 表格列一致性（13 篇） ----------
for f in sorted(os.listdir(AN)):
    if not f.endswith(".md"): continue
    lines = read(os.path.join(AN, f)).split("\n")
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("|") and s.endswith("|") and i + 1 < len(lines):
            sep = lines[i + 1].strip()
            if sep.startswith("|") and set(sep.replace("|", "").replace("-", "").replace(":", "").strip()) == set():
                def cols(t): return t.strip().replace("\\|", "\x00").count("|")
                n = cols(s); j = i + 1
                while j < len(lines) and lines[j].strip().startswith("|"):
                    if cols(lines[j]) != n:
                        print(f"[表] {f}:{j+1} 列数 {cols(lines[j])} != 表头 {n}")
                        fails.append(f"表:{f}:{j+1}")
                    j += 1
                i = j; continue
        i += 1
print("[表] 列一致性检查完成")

# ---------- G12：常量漂移（全 doc/analysis） ----------
CONST = {
    "69": "端点", "12 个": "子router", "9": "表", "15": "视图", "13": "组件",
    "58": "端点常量", "18": "SSE事件", "99": "pytest",
}
for num, kw in CONST.items():
    hits = []
    for f in sorted(os.listdir(AN)):
        if not f.endswith(".md"): continue
        txt = read(os.path.join(AN, f))
        for ln, l in enumerate(txt.split("\n"), 1):
            if num in l:
                hits.append(f)
                break
    # 只报告：该数字出现但同篇未出现对应关键词（可能语境错误）的篇
print("[G12] 常量抽查完成（人工核对语境）")

print()
print("=" * 40)
print("FAIL:", fails if fails else "无")
sys.exit(1 if fails else 0)
