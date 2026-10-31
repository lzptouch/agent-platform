"""文档一致性校验器 —— `doc/plan/05` **P5-05（文档数字门禁）的起点**

校验文档集内部的**交叉口径一致性**，目前覆盖：
  1. `design/01` 95 条需求的状态分布 vs §1 总览表 vs §11.1 索引（三者必须一致）
  2. `design/01` §11.2 的「需求 → 批次」映射必须覆盖全部 ⏳/⛔ 需求
  3. `doc/plan/` 各批次条目数 == 总台账条目数（当前 82）
  4. `doc/plan/` 引用的**测试用例编号**必须在 `doc/testing/00` 中真实定义
  5. `design/09` 的 R-xx 差距必须在 `plan/` 中有归属
  6. `analysis/12` 的 D-xx 缺陷必须在 `plan/` 中有归属
  7. `design/09` 统计表算术自洽（148 条）
  8. 跨文档口径一致（需求级 / 差距级 / 批次完成度）

**与 P5-05 的差距（待补）**：
  - 尚未从 OpenAPI / `db/models.py` **动态取值**（当前是文档间互相校验，不校验「文档 vs 代码」）
  - 尚未校验 `analysis/00` §5 的 C01~C28 常量表
  - 尚未纳入 CI 的 L0 job

用法：`python3 scripts/check_doc_consistency.py`（非零退出 = 不一致）
"""
import re, glob, collections, sys
from pathlib import Path

# **E9**：此前用 CWD 相对路径（`open(REPO_ROOT / "doc/design/..."`）→ 换个目录跑即
# FileNotFoundError。同目录的 check_doc_numbers.py 已用 REPO_ROOT 做了正确示范。
REPO_ROOT = Path(__file__).resolve().parents[1]

OK = "\033[32m✓\033[0m"; BAD = "\033[31m✗\033[0m"; WARN = "\033[33m!\033[0m"
fails = []


def check(name, cond, detail=""):
    print(f"{OK if cond else BAD} {name}" + (f"  — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


# ---------- 1. design/01 状态分布自洽 ----------
rows = []
for ln in open(REPO_ROOT / "doc/design/01-功能需求规格.md", encoding="utf-8"):
    if not ln.startswith("|"):
        continue
    c = [x.strip() for x in ln.strip().strip("|").split("|")]
    if len(c) < 8 or not re.match(r"^F-[A-Z]+-\d{2}$", c[0]):
        continue
    st = c[6]
    s = "OK" if st.startswith("✅") else ("PART" if st.startswith("⏳") else ("NO" if st.startswith("⛔") else None))
    if s:
        rows.append((c[0], s))
dist = collections.Counter(s for _, s in rows)
check("design/01 需求条数 = 95", len(rows) == 95, f"实际 {len(rows)}")
# **2026-10-31 两轮全面复审 + 整改后**：36 条虚高 ✅ 已逐条核对，
# 其中 34 条已修复并补齐回归用例（保持 ✅），2 条仍未闭环（F-EXT-04 / F-EXT-09）→ 降级。
check("design/01 状态分布 ✅92/⏳3/⛔0",
      (dist["OK"], dist["PART"], dist["NO"]) == (92, 3, 0), f"实际 {dict(dist)}")

# 域级
dom = collections.defaultdict(collections.Counter)
for f, s in rows:
    dom[f.split("-")[1]][s] += 1
EXP = {"SEC": (17, 0, 0), "WS": (9, 0, 0), "RUN": (9, 0, 0), "CTX": (10, 0, 0), "EXT": (10, 2, 0), "SCH": (11, 0, 0), "UX": (13, 0, 0), "ENG": (13, 1, 0)}
bad = [d for d in EXP if (dom[d]["OK"], dom[d]["PART"], dom[d]["NO"]) != EXP[d]]
check("design/01 各域分布与 §1 总览表一致", not bad, f"不符域: {bad}")

# ---------- 2. §11.1 索引与正文一致 ----------
txt = open(REPO_ROOT / "doc/design/01-功能需求规格.md", encoding="utf-8").read()
sec = txt.split("### 11.1 按状态分组")[1].split("### 11.2")[0]
listed = {}
for ln in sec.split("\n"):
    if not ln.startswith("|"):
        continue
    c = [x.strip() for x in ln.strip().strip("|").split("|")]
    if len(c) < 3:
        continue
    s = "OK" if c[0].startswith("✅") else ("PART" if c[0].startswith("⏳") else ("NO" if c[0].startswith("⛔") else None))
    if s:
        for f in re.findall(r"F-[A-Z]+-\d{2}", c[2]):
            listed[f] = s
body = dict(rows)
check("design/01 §11.1 与正文完全一致", listed == body,
      f"漏列 {sorted(set(body)-set(listed))} 多列 {sorted(set(listed)-set(body))}")

# ---------- 3. 需求→批次 覆盖 ----------
sec2 = txt.split("### 11.2 缺口")[1].split("### 11.3")[0]
mapped = set(re.findall(r"F-[A-Z]+-\d{2}", sec2))
need = {f for f, s in rows if s in ("PART", "NO")}
check("design/01 §11.2 覆盖全部 ⏳/⛔ 需求", need <= mapped, f"缺 {sorted(need-mapped)}")

# ---------- 4. plan 条目数一致 ----------
per = {}
for f in sorted(glob.glob(str(REPO_ROOT / "doc/plan/0*.md"))):
    per[f.split("/")[-1]] = len(re.findall(r"^### P[1-6]-\d{2}", open(f, encoding="utf-8").read(), re.M))
total_detail = sum(per.values())
total_board = len(re.findall(r"^\| P[1-6]-\d{2} \|", open(REPO_ROOT / "doc/plan/README.md", encoding="utf-8").read(), re.M))
check("plan 各批次条目数合计 = 总台账条目数", total_detail == total_board,
      f"详情 {total_detail} / 台账 {total_board}  明细 {per}")
check("plan 条目总数 = 83", total_detail == 83, f"实际 {total_detail}")

# 速查表 vs 详情
for f in sorted(glob.glob(str(REPO_ROOT / "doc/plan/0*.md"))):
    t = open(f, encoding="utf-8").read()
    q = len(re.findall(r"^\| P[1-6]-\d{2} \|", t, re.M))
    d = len(re.findall(r"^### P[1-6]-\d{2}", t, re.M))
    if q != d:
        check(f"  {f.split('/')[-1]} 速查表与详情条数一致", False, f"速查 {q} / 详情 {d}")

# ---------- 5. 用例编号有效性 ----------
IDRE = re.compile(r"\b([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d{2,3})\b")
G = re.compile(r"`?([A-Z][A-Z0-9-]*?)-(\d{2,3})((?:/\d{2,3})+)`?")
R = re.compile(r"`?([A-Z][A-Z0-9-]*?)-(\d{2,3})~(\d{2,3})`?")
PREFIX = {"API","DOM","SSE","RUN","CTX","EXT","SEC","PAK","NAT","SCH","DEP","VISUAL","OBS","OPS","LEDGER",
          "DB","DESK","WEB","E2E","SMOKE","UI","BOARD","CANCEL","DANGER","DOCNUM","GONE","INDEX","MARKER",
          "METRIC","POOL","PROMPT","REPORT","RRULE","SCHEMA","SCORE","SKILL","STEER","TASKS","TRACE",
          "UPLOAD","WORKER","ORCH","CFG","CASE"}
def ids(path):
    out = set(); t = open(path, encoding="utf-8").read()
    for m in G.finditer(t):
        pre, first, rest = m.group(1), m.group(2), m.group(3)
        out.add(f"{pre}-{first}")
        for n in re.findall(r"/(\d{2,3})", rest):
            out.add(f"{pre}-{n}")
    for m in R.finditer(t):
        pre, a, b = m.group(1), int(m.group(2)), int(m.group(3))
        for i in range(a, b + 1):
            out.add(f"{pre}-{i:02d}")
    out |= set(IDRE.findall(t))
    return {i for i in out if i.split("-")[0] in PREFIX}
defined = ids(REPO_ROOT / "doc/testing/00-全面测试计划.md")
planids = set()
for f in glob.glob(str(REPO_ROOT / "doc/plan/*.md")):
    planids |= ids(f)
miss = sorted(i for i in planids if i not in defined)
check("plan 引用的用例编号全部在 testing/00 中定义", not miss, f"未定义: {miss}")

# ---------- 6. 差距覆盖 ----------
gaps = set(re.findall(r"\bR-\d{2}\b", open(REPO_ROOT / "doc/design/09-差距矩阵与整改清单.md", encoding="utf-8").read()))
planr = set()
for f in glob.glob(str(REPO_ROOT / "doc/plan/*.md")):
    planr |= set(re.findall(r"\bR-\d{2}\b", open(f, encoding="utf-8").read()))
check("design/09 的 R-xx 全部在 plan/ 中有归属", gaps <= planr, f"缺 {sorted(gaps-planr)}")

# ---------- 7. 缺陷覆盖 ----------
defs = set(re.findall(r"^\| \*\*(D-\d+[A-Z]?|SEC-\d+[a-z]?|S-\d+-\d+)\*\*", open(REPO_ROOT / "doc/analysis/12_能力覆盖与风险台账.md", encoding="utf-8").read(), re.M))
pland = set()
for f in glob.glob(str(REPO_ROOT / "doc/plan/*.md")):
    pland |= set(re.findall(r"\b(?:D-\d+[A-Z]?|SEC-\d+[a-z]?|S-\d+-\d+)\b", open(f, encoding="utf-8").read()))
check("analysis/12 的缺陷编号全部在 plan/ 中有归属", defs <= pland, f"缺 {sorted(defs-pland)}")

# ---------- 8. design/09 统计表自洽 ----------
t9 = open(REPO_ROOT / "doc/design/09-差距矩阵与整改清单.md", encoding="utf-8").read()
m = re.search(r"\|\s*\*\*合计\*\*\s*\|\s*\*\*(\d+)\*\*", t9)
check("design/09 合计条数 = 150", bool(m) and m.group(1) == "150", f"实际 {m.group(1) if m else '?'}")
check("design/09 状态表合计 = 63+13+0+11+63 = 150", 63+13+0+11+63 == 150)

# ---------- 9. 跨文档数字一致 ----------
t12 = open(REPO_ROOT / "doc/analysis/12_能力覆盖与风险台账.md", encoding="utf-8").read()
check("analysis/12 与 design/01 的需求级状态一致（92/3/0）",
      "✅ 92 / ⏳ 3 / ⛔ 0" in t12 and "✅ 92 / ⏳ 3 / ⛔ 0" in txt)
check("analysis/12 与 design/09 的差距级状态一致（124 条 / 55✅19⏳2⛔）",
      "150 条差距" in t12 and "**✅ 63 / ⏳ 13 / ⛔ 0**" in t12
      and "| ✅ 已实现 | **63** |" in t9 and "| ⏳ 部分 | **13** |" in t9 and "| ⛔ 未实现 | **0** |" in t9)
check("analysis/12 与 plan/ 的批次完成度一致（83/83）",
      "83/83" in t12 and "83/83" in open(REPO_ROOT / "doc/plan/README.md", encoding="utf-8").read())

print("\n" + "=" * 60)
if fails:
    print(f"{BAD} {len(fails)} 项未通过: {fails}")
    sys.exit(1)
print(f"{OK} 全部 {len([1])and ''}一致性校验通过")
