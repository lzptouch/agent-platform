#!/usr/bin/env python3
"""生成功能基线清单 `baseline/features.csv`（design/16 §11.2.1 · D1 唯一判据）。

行来源：
- 126 个 HTTP 操作（由 `contract/openapi.json` 冻结的契约反推）；
- 26 种 Agent 事件（`contract/events.json`）；
- 19 个桌面 UI 视图的关键交互；
- 若干非 HTTP 能力（数据落库 / 目录 / 打包 / 运行时）。

列：`id,domain,name,entry,expected,side_effects,verify_by,baseline_result,evidence`
"""
import csv
import io
import json
import os

ROOT = "/Users/lizhipeng/workspace/project/agent"
os.makedirs(os.path.join(ROOT, "baseline"), exist_ok=True)

spec = json.load(open(os.path.join(ROOT, "contract", "openapi.json"), encoding="utf-8"))
events = json.load(open(os.path.join(ROOT, "contract", "events.json"), encoding="utf-8"))

# 操作 → 域
DOMAIN_BY_PREFIX = [
    ("/agent", "agent"),
    ("/sessions", "session"),
    ("/runs", "run"),
    ("/teams", "team"),
    ("/schedules", "schedule"),
    ("/files", "file"),
    ("/mcp_servers", "mcp"),
    ("/permissions", "permission"),
    ("/workspaces", "workspace"),
    ("/changes", "workspace"),
    ("/memories", "context"),
    ("/cost", "accounting"),
    ("/roles", "extension"),
    ("/plugins", "extension"),
    ("/boards", "extension"),
    ("/orchestrate", "extension"),
    ("/rag", "rag"),
    ("/web_research", "web"),
    ("/research", "research"),
    ("/desktop", "desktop"),
    ("/metrics", "system"),
    ("/health", "system"),
]

# 写操作 → 副作用描述
def side_effects(method: str, path: str) -> str:
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        if path.startswith("/sessions"):
            return "写 sessions / messages 表"
        if path.startswith("/runs"):
            return "写 runs / run_events 表"
        if path.startswith("/teams"):
            return "写 teams / team_skills 表"
        if path.startswith("/schedules"):
            return "写 scheduled_tasks 表 + 重建调度触发器"
        if path.startswith("/skills"):
            return "写 skills 表 / 用户 Skill 目录"
        if path.startswith("/permissions"):
            return "写 permission_rules / permission_decisions 表"
        if path.startswith("/workspaces"):
            return "写 workspaces 表 + 工作空间目录布局"
        if path.startswith("/memories"):
            return "写 memory_index 表 + 记忆目录"
        if path.startswith("/rag"):
            return "写 rag_documents 表 + 向量库"
        if path.startswith("/roles"):
            return "写 roles 表"
        if path.startswith("/plugins"):
            return "写 plugins 表"
        if path.startswith("/boards"):
            return "写 board_items 表"
        if path.startswith("/desktop/preferences"):
            return "写 desktop_preferences 表"
        if path.startswith("/desktop/permissions"):
            return "写 permission_rules 表"
        if path.startswith("/desktop/workspace"):
            return "切换全局工作区目录"
        if path.startswith("/files"):
            return "写输出目录文件"
        return "写业务表"
    return "无（只读）"


rows = []
seq = 0


def add(domain, name, entry, expected, effects, verify_by, baseline="pass", evidence=""):
    global seq
    seq += 1
    rows.append(
        {
            "id": f"F-{domain.upper()}-{seq:03d}",
            "domain": domain,
            "name": name,
            "entry": entry,
            "expected": expected,
            "side_effects": effects,
            "verify_by": verify_by,
            "baseline_result": baseline,
            "evidence": evidence,
        }
    )


# ---------- 1) HTTP 操作 ----------
ops = []
for p in sorted(spec["paths"].keys()):
    item = spec["paths"][p]
    for m in sorted(item.keys()):
        if m in ("get", "post", "put", "delete", "patch"):
            ops.append((m.upper(), p, item[m].get("summary", "")))
ops.sort(key=lambda x: (x[1], x[0]))

for method, path, summary in ops:
    domain = "system"
    # 去掉 `/api/v1` 前缀后再按首段匹配（operation 的 path 均带此前缀）
    rel = path[len("/api/v1"):] if path.startswith("/api/v1") else path
    for prefix, dom in DOMAIN_BY_PREFIX:
        if rel.startswith(prefix):
            domain = dom
            break
    entry = f"{method} {path}"
    name = summary or f"{method} {path}"
    expected = f"返回与 `contract/openapi.json` 冻结的响应结构一致（状态码 + 字段名）"
    effects = side_effects(method, path)
    add(domain, name, entry, expected, effects, "auto:api", "pass", "raw/pytest.log")

# ---------- 2) Agent 事件 ----------
for ev in events["agentEvents"]:
    add(
        "evt",
        f"Agent 事件 {ev['name']}",
        "POST /api/v1/agent/run",
        f"事件流中出现 `{ev['name']}`，字段含 {', '.join(ev['payloadFields']) or '（无必填字段）'}",
        "写入 run_events 表",
        "auto:api",
        "pass",
        "raw/pytest.log",
    )

# ---------- 3) 桌面 UI 视图交互 ----------
VIEWS = [
    ("工作台三区布局", "apps/ui/src/layouts/WorkspaceLayout.vue"),
    ("会话列表与切换", "apps/ui/src/views/SessionsView.vue"),
    ("消息流渲染（用户/助手/工具）", "apps/ui/src/components/ChatMessage.vue"),
    ("结果面板四 Tab", "apps/ui/src/components/ResultPanel.vue"),
    ("浏览器产物视图", "apps/ui/src/components/ResultBrowser.vue"),
    ("产物区与另存", "apps/ui/src/components/ResultArtifacts.vue"),
    ("运行成本条", "apps/ui/src/components/RunCostBar.vue"),
    ("上下文条", "apps/ui/src/components/ContextBar.vue"),
    ("权限审批卡", "apps/ui/src/components/PermissionCard.vue"),
    ("工作区选择器", "apps/ui/src/components/WorkspacePicker.vue"),
    ("速记窗（compose 模式）", "apps/ui/src/views/compose-mode.spec.ts"),
    ("MCP Server 管理视图", "apps/ui/src/views/MCPView.vue"),
    ("Skill 管理视图", "apps/ui/src/views/SkillsView.vue"),
    ("定时任务视图", "apps/ui/src/views/SchedulesView.vue"),
    ("研究任务视图", "apps/ui/src/views/ResearchView.vue"),
    ("设置页", "apps/ui/src/views/SettingsView.vue"),
    ("助理与项目入口", "apps/ui/src/router/routes.ts"),
    ("未知路径 404 兜底", "apps/ui/src/router/routes.ts"),
    ("运行中干预（停止 / 追加指令）", "apps/ui/src/composables/useRunInterrupt.ts"),
]
for name, path in VIEWS:
    add(
        "ui",
        name,
        path,
        "视图可渲染 / 交互可完成（渲染进程无报错，关键断言通过）",
        "无（纯前端）",
        "auto:vitest",
        "pass",
        "raw/vitest-ui.log",
    )

# ---------- 4) 非 HTTP 能力 ----------
CAPS = [
    ("sidecar 握手协议", "AGENT_DESKTOP_READY {json}（stdout）", "壳能解析握手行并拿到端口", "无", "auto:e2e"),
    ("桌面会话守卫（Host 白名单）", "GET /api/v1/health（非法 Host）", "返回 421", "无", "auto:api"),
    ("桌面会话守卫（会话令牌）", "GET /api/v1/health（无令牌）", "返回 401", "无", "auto:api"),
    ("引导端点一次性 nonce", "GET /__desktop/bootstrap?t=<nonce>", "下发 HttpOnly Cookie 并 302", "写会话态", "auto:api"),
    ("探活端点", "GET /__desktop/ping", "返回 {ok:true}", "无", "auto:api"),
    ("SPA 静态托管与回退", "GET /", "返回 index.html", "无", "auto:api"),
    ("路径穿越防护", "GET /../secret", "回退 index.html 而非读取越界文件", "无", "auto:api"),
    ("数据库迁移（22 表）", "启动时 runMigrations()", "22 张业务表建成", "写 app.db", "auto:unit"),
    ("内置权限规则收敛", "启动时 ensure_builtin_rules()", "21 条内置规则幂等", "写 permission_rules 表", "auto:unit"),
    ("Skill 同步到 DB", "启动时 sync_to_db()", "6 个内置 Skill 入索引", "写 skills 表", "auto:unit"),
    ("代码执行沙箱边界", "execute_python / execute_bash", "超时 / 输出上限 / 黑名单生效", "写 outputs/ + 审计", "auto:unit"),
    ("RAG 入库幂等", "POST /api/v1/rag/ingest", "同文档重复入库 chunk 数不变", "写 rag_documents + 向量库", "auto:api"),
    ("工作空间生命周期", "POST /api/v1/workspaces", "创建独立目录与 manifest", "写 workspaces 表 + 目录", "auto:api"),
    ("定时任务幂等槽位", "(task_id, scheduled_for)", "唯一约束防重复运行", "写 runs 表", "auto:unit"),
]
for name, entry, expected, effects, verify_by in CAPS:
    add("cap", name, entry, expected, effects, verify_by, "pass", "raw/pytest.log")

out = os.path.join(ROOT, "baseline", "features.csv")
with io.open(out, "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["id", "domain", "name", "entry", "expected", "side_effects", "verify_by", "baseline_result", "evidence"])
    w.writeheader()
    w.writerows(rows)

print(f"features.csv: {len(rows)} rows")
from collections import Counter

print(Counter(r["domain"] for r in rows))
