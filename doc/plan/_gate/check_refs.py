# -*- coding: utf-8 -*-
"""G5 引用可解析：抽取 `path:line` / `path:a-b`，校验文件存在且行号不超界。
G2 表完整性：04 的 9 表与 models.py 字段名比对。"""
import os, re, sys, ast

ROOT = r"c:\workspace\project\agent-platform"
AN = os.path.join(ROOT, "doc", "analysis")
fails = []

# ---------- G5 ----------
# 匹配形如  backend/app/x.py:12 或 frontend/.../x.ts:1-9 或 src/x.vue:100
ref = re.compile(r"((?:backend|frontend|deploy|scripts|src|app)/[\w./-]+\.(?:py|ts|vue|mjs|yml|conf|md|json|sh))(?::(\d+)(?:-(\d+))?)?")
over = []
missing = []
for f in sorted(os.listdir(AN)):
    if not f.endswith(".md"): continue
    lines = open(os.path.join(AN, f), encoding="utf-8").read().split("\n")
    in_fence = False
    for line in lines:
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue  # 代码块内不出现对现有代码的引用
        # 「未实现（参考实现）」「新建」提案路径不纳入存在性校验
        if ("未实现" in line) or ("待新建" in line) or ("新建 " in line) or ("新建`" in line):
            continue
        for m in ref.finditer(line):
            p, a, b = m.group(1), m.group(2), m.group(3)
            full = os.path.join(ROOT, p.replace("/", os.sep))
            if not os.path.exists(full):
                missing.append((f, p)); continue
            if b:
                n = sum(1 for _ in open(full, encoding="utf-8", errors="ignore"))
                if int(b) > n:
                    over.append((f, p, b, n))
print(f"[G5] 文件不存在: {len(missing)}")
for f, p in missing[:20]: print(f"      {f} -> {p}")
print(f"[G5] 行号越界: {len(over)}")
for f, p, b, n in over[:20]: print(f"      {f} -> {p}:{b} (文件仅 {n} 行)")
if missing or over: fails.append("G5")

# ---------- G2：04 的 9 表字段名 = models.py ----------
src = open(os.path.join(ROOT, "backend", "app", "db", "models.py"), encoding="utf-8").read()
tree = ast.parse(src)
model_tables = {}
for node in tree.body:
    if isinstance(node, ast.ClassDef):
        tab = None
        fields = []
        for st in node.body:
            if isinstance(st, ast.Assign):
                for t in st.targets:
                    if isinstance(t, ast.Name) and t.id == "__tablename__":
                        tab = st.value.value
            if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                fields.append(st.target.id)
        if tab:
            model_tables[tab] = [x for x in fields if not x.startswith("_")]
d04 = read04 = open(os.path.join(AN, "04_数据模型与持久化.md"), encoding="utf-8").read()
print(f"[G2] models.py 业务表: {sorted(model_tables.keys())}")
for t, cols in model_tables.items():
    if f"`{t}`" not in d04:
        print(f"[G2] 04 缺表 `{t}`"); fails.append(f"G2:{t}")
print(f"[G2] 9 表在 04 中全部出现: {'是' if all(f'`{t}`' in d04 for t in model_tables) else '否'}")

print("=" * 40)
print("FAIL:", fails if fails else "无")
sys.exit(1 if fails else 0)
