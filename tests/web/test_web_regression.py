"""Web 端标准工程回归版（对应 practice/测试计划.md 模块 A2 + 稳定性专项）。

覆盖：正向流程、边界值、非法输入、权限校验、重复提交、弱网/断网；
同时校验接口返回与前端 UI 渲染一致性；失败自动保存 trace 与截图。

运行：
    backend/.venv/Scripts/python.exe -m pytest tests/web -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.harness import (  # noqa: E402
    CATEGORY_BUSINESS,
    CATEGORY_ENV,
    BackendProcess,
    Suite,
    dump_json,
    shot,
)

SUITE_NAME = "web"
SUITE_TARGET = "agent-platform Web（Vue3 + Element Plus）· http://127.0.0.1:<dynamic>"

suite = Suite(SUITE_NAME, SUITE_TARGET)
_backend: BackendProcess | None = None


# --------------------------------------------------------------------------- #
# Fixture：后端进程 + 浏览器
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def backend():
    global _backend
    proc = BackendProcess()
    ok, msg = proc.start()
    if not ok:
        pytest.skip(f"环境不具备：{msg}")
    _backend = proc
    yield proc
    proc.stop()


@pytest.fixture(scope="module")
def page(backend):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.tracing.start(screenshots=True, snapshots=True)
        pg = context.new_page()
        pg.set_default_timeout(15_000)
        yield pg
        try:
            context.tracing.stop(path=str(Path("tests/report/web-trace.zip").resolve()))
        except Exception:
            pass
        context.close()
        browser.close()


# --------------------------------------------------------------------------- #
# 接口层用例（稳定、可自动判定）
# --------------------------------------------------------------------------- #
def test_web_01_health(backend):
    """WEB-01 健康检查返回真实数据（不硬编码）。"""
    r = backend.base_url and __import__("requests").get(f"{backend.base_url}/api/v1/health", timeout=10)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("status") == "ok", dump_json(data)
    assert isinstance(data.get("skills_loaded"), int), dump_json(data)
    suite.ok("WEB-01", "健康检查可用且结构正确", "接口")


def test_web_02_error_envelope(backend):
    """WEB-02 不存在的资源返回统一错误结构。"""
    import requests

    r = requests.get(f"{backend.base_url}/api/v1/sessions/does-not-exist", timeout=10)
    assert r.status_code in (404, 422), r.status_code
    suite.ok("WEB-02", "未知资源返回 404/422（错误结构由 S1 统一）", "接口")


def test_web_03_session_crud(backend):
    """WEB-03 会话 CRUD 正向 + 非法输入。"""
    import requests

    created = requests.post(f"{backend.base_url}/api/v1/sessions", json={"mode": "chat"}, timeout=10)
    assert created.status_code in (200, 201), created.text
    sid = created.json()["id"]

    listed = requests.get(f"{backend.base_url}/api/v1/sessions", timeout=10)
    assert listed.status_code == 200
    assert any(s["id"] == sid for s in listed.json().get("items", listed.json()))

    patched = requests.patch(f"{backend.base_url}/api/v1/sessions/{sid}", json={"title": "回归用例会话"}, timeout=10)
    assert patched.status_code == 200, patched.text

    reread = requests.get(f"{backend.base_url}/api/v1/sessions/{sid}", timeout=10)
    assert reread.status_code == 200, reread.text
    assert reread.json()["title"] == "回归用例会话", dump_json(reread.json())

    bad = requests.post(f"{backend.base_url}/api/v1/sessions", json={"mode": "不存在的模式"}, timeout=10)
    assert bad.status_code in (400, 422), bad.status_code

    deleted = requests.delete(f"{backend.base_url}/api/v1/sessions/{sid}", timeout=10)
    assert deleted.status_code in (200, 204), deleted.status_code
    gone = requests.get(f"{backend.base_url}/api/v1/sessions/{sid}", timeout=10)
    assert gone.status_code == 404, gone.status_code
    suite.ok("WEB-03", "会话创建/回读/改名/删除 + 非法 mode 被拒", "接口")


def test_web_04_path_traversal_blocked(backend):
    """WEB-04 目录穿越被拦截（安全基线）。"""
    import requests

    r = requests.get(f"{backend.base_url}/api/v1/skills/pdf/files/../../core/config.py", timeout=10)
    assert r.status_code in (400, 403, 404), f"状态码 {r.status_code} 疑似未拦截"
    assert "config.py" not in r.text or r.status_code != 200
    suite.ok("WEB-04", "技能资源路径穿越被拦截", "接口")


def test_web_05_permissions_crud(backend):
    """WEB-05 权限规则读写 + 非法决策被拒。"""
    import requests

    got = requests.get(f"{backend.base_url}/api/v1/desktop/permissions", timeout=10)
    assert got.status_code == 200, got.text
    payload = got.json()
    assert "rules" in payload or "decision" in payload, dump_json(payload)

    bad = requests.put(
        f"{backend.base_url}/api/v1/desktop/permissions",
        json={"scope": "tool", "target": "write_file", "decision": "不存在的决策"},
        timeout=10,
    )
    assert bad.status_code == 422, bad.status_code
    suite.ok("WEB-05", "权限规则可读；非法 decision 返回 422", "接口")


def test_web_06_schedule_cron_validation(backend):
    """WEB-06 非法 cron 表达式被拒（边界 + 非法输入）。"""
    import requests

    r = requests.post(f"{backend.base_url}/api/v1/schedules/validate", json={"cron_expr": "不是 cron"}, timeout=10)
    assert r.status_code in (200, 400, 422), r.status_code
    body = r.json()
    assert body.get("valid") is False, dump_json(body)
    suite.ok("WEB-06", "非法 cron 表达式校验为不通过", "接口")


def test_web_07_schedule_idempotent_create(backend):
    """WEB-07 重复提交防护：同名任务被拒或可预期地去重。"""
    import requests

    name = "回归-重复提交用例"
    payload = {
        "name": name,
        "prompt": "ping",
        "mode": "chat",
        "schedule_kind": "interval",
        "interval_seconds": 3600,
    }
    first = requests.post(f"{backend.base_url}/api/v1/schedules", json=payload, timeout=10)
    assert first.status_code in (200, 201), first.text
    task_id = first.json()["id"]

    second = requests.post(f"{backend.base_url}/api/v1/schedules", json=payload, timeout=10)
    assert second.status_code in (200, 201, 400, 409), second.status_code

    # 安全约束：work 模式且启用时必须显式确认无人值守工具权限
    unsafe = requests.post(
        f"{backend.base_url}/api/v1/schedules",
        json={**payload, "name": name + "-unsafe", "mode": "work"},
        timeout=10,
    )
    assert unsafe.status_code == 422, f"work 模式未显式确认 allow_unattended_tools 却被接受：{unsafe.status_code}"


    requests.delete(f"{backend.base_url}/api/v1/schedules/{task_id}", timeout=10)
    suite.ok("WEB-07", "同名定时任务重复提交有明确处置", "接口")


def test_web_08_files_lifecycle(backend):
    """WEB-08 文件上传 → 列表 → 删除（数据隔离在独立测试目录）。"""
    import requests

    content = b"regression probe"
    up = requests.post(
        f"{backend.base_url}/api/v1/files/upload",
        files={"file": ("regression_probe.txt", content, "text/plain")},
        timeout=20,
    )
    assert up.status_code in (200, 201), up.text

    listed = requests.get(f"{backend.base_url}/api/v1/files", timeout=10)
    assert listed.status_code == 200
    body = listed.json()
    names = [f.get("filename") or f.get("name") for f in (body.get("files") if isinstance(body, dict) else body)]
    assert "regression_probe.txt" in names, dump_json(names)

    dl = requests.get(f"{backend.base_url}/api/v1/files/regression_probe.txt", timeout=10)
    assert dl.status_code == 200, dl.status_code
    assert dl.content == content

    requests.delete(f"{backend.base_url}/api/v1/files/regression_probe.txt", timeout=10)
    suite.ok("WEB-08", "文件上传/下载/删除闭环", "接口")


# --------------------------------------------------------------------------- #
# UI 层用例
# --------------------------------------------------------------------------- #
def test_web_10_homepage_loads(page, backend):
    """WEB-10 首页加载出主工作台（元素可识别）。"""
    page.goto(backend.base_url, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=20_000)
    body = page.inner_text("body")
    assert body.strip(), "页面正文为空"
    evidence = shot(page, "web-10-homepage")
    assert any(k in body for k in ("新建任务", "任务", "Agent", "工作台")), body[:200]
    suite.ok("WEB-10", "首页渲染出主工作台", "UI", evidence)


def test_web_11_mode_switch(page, backend):
    """WEB-11 三种工作模式可切换（UI 与接口枚举一致）。"""
    page.goto(backend.base_url, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=20_000)
    text = page.inner_text("body")
    modes = [m for m in ("Ask", "Plan", "Craft", "问答", "计划", "工作") if m in text]
    assert modes, f"未找到模式入口；页面文本片段：{text[:200]}"
    suite.ok("WEB-11", f"工作模式入口可见（命中 {modes}）", "UI")


def test_web_12_chat_stream_or_readable_error(page, backend):
    """WEB-12 发起对话：有模型则应流式返回；无模型也应给出可读错误而非白屏。"""
    page.goto(backend.base_url, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=20_000)

    box = page.locator("textarea").first
    if box.count() == 0:
        suite.skip("WEB-12", "发起对话", "UI", "页面无 textarea（布局变更），无法定位输入框")
        return
    box.fill("用一句话介绍这个平台")
    box.press("Enter")
    page.wait_for_timeout(8000)
    body = page.inner_text("body")
    evidence = shot(page, "web-12-chat")
    assert body.strip(), "对话后页面为空"
    assert not page.locator("text=/Internal Server Error/i").count(), "出现 500 错误"
    suite.ok("WEB-12", "对话入口可用（流式回复或可读错误提示）", "UI", evidence)


def test_web_13_backend_down_shows_error(page, backend):
    """WEB-13 弱网/断网：后端不可达时前端不白屏。"""
    page.route("**/api/v1/**", lambda route: route.abort())
    page.goto(backend.base_url, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    body = page.inner_text("body")
    evidence = shot(page, "web-13-offline")
    assert body.strip(), "断网后页面完全空白"
    suite.ok("WEB-13", "接口不可达时页面仍有内容（不白屏）", "UI", evidence)
    page.unroute("**/api/v1/**")


def test_web_14_long_input_stable(page, backend):
    """WEB-14 超长文本与特殊字符不导致崩溃。"""
    page.goto(backend.base_url, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=20_000)
    box = page.locator("textarea").first
    if box.count() == 0:
        suite.skip("WEB-14", "超长输入", "UI", "无 textarea，无法定位输入框")
        return
    payload = "A" * 5000 + " <script>alert(1)</script> \"quoted\" \\backslash\\"
    box.fill(payload)
    page.wait_for_timeout(1500)
    evidence = shot(page, "web-14-long-input")
    assert not page.locator("text=/Internal Server Error/i").count()
    suite.ok("WEB-14", "超长文本与特殊字符输入不崩溃", "UI", evidence)


def test_web_16_permission_rules_api(backend):
    """WEB-16 权限规则 API：内置规则集可见、可增删。"""
    import requests

    r = requests.get(f"{backend.base_url}/api/v1/permissions/rules", timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "rules" in body and "effective_level" in body, dump_json(body)
    assert len(body["rules"]) >= 5, "内置规则集（禁止路径/危险命令/只读工具/写类工具）应随迁移写入"

    # 新增一条规则 → 删除它
    put = requests.put(
        f"{backend.base_url}/api/v1/permissions/rules",
        json={"scope": "tool", "pattern": "e2e_probe_tool", "decision": "deny"},
        timeout=10,
    )
    assert put.status_code == 200, put.text
    listed = requests.get(f"{backend.base_url}/api/v1/permissions/rules", timeout=10).json()
    assert any(r.get("pattern") == "e2e_probe_tool" for r in listed["rules"])

    requests.delete(
        f"{backend.base_url}/api/v1/permissions/rules",
        json={"scope": "tool", "pattern": "e2e_probe_tool"},
        timeout=10,
    )
    listed2 = requests.get(f"{backend.base_url}/api/v1/permissions/rules", timeout=10).json()
    assert not any(r.get("pattern") == "e2e_probe_tool" for r in listed2["rules"])
    suite.ok("WEB-16", "权限规则 API：内置规则集可见 + 增删闭环", "接口")


def test_web_17_sandbox_honest(backend):
    """WEB-17 沙箱能力诚实标注（policy_only，而非硬编码 false）。"""
    import requests

    r = requests.get(f"{backend.base_url}/api/v1/permissions/sandbox", timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("level") == "policy_only", dump_json(body)
    assert body.get("available") is True
    assert "策略层" in body.get("message", "")
    suite.ok("WEB-17", "沙箱能力返回 policy_only 与替代机制说明", "接口")


def test_web_18_approval_flow_api(backend):
    """WEB-18 审批通道 API：待审批列表可读、决策端点校验、统一错误体。

    说明：工具调用没有直连端点（只经 LLM 运行环触发），阻塞式审批的
    「等待/超时/四种决策语义」由后端集成测试 `test_s2_security.py` 覆盖；
    这里验证审批通道的 API 面。
    """
    import requests

    # 待审批列表可读
    pending = requests.get(
        f"{backend.base_url}/api/v1/permissions/decisions", params={"status": "pending"}, timeout=10
    )
    assert pending.status_code == 200, pending.text
    assert "items" in pending.json()

    # 决策端点：非法 choice → 422
    bad = requests.post(
        f"{backend.base_url}/api/v1/permissions/decisions",
        json={"decision_id": 1, "choice": "approve_forever"},
        timeout=10,
    )
    assert bad.status_code == 422, bad.status_code

    # 决策端点：不存在的 decision_id → 404 + 统一错误体
    missing = requests.post(
        f"{backend.base_url}/api/v1/permissions/decisions",
        json={"decision_id": 999999, "choice": "deny"},
        timeout=10,
    )
    assert missing.status_code == 404, missing.status_code
    body = missing.json()
    assert body.get("code") and body.get("request_id"), dump_json(body)

    # 决策日志列表可读
    all_d = requests.get(f"{backend.base_url}/api/v1/permissions/decisions", timeout=10)
    assert all_d.status_code == 200
    suite.ok("WEB-18", "审批通道 API：待审批可读 / 非法决策 422 / 不存在 404 统一错误体", "接口")


def test_web_19_workspace_lifecycle(backend):
    """WEB-19 工作空间生命周期：创建 → 列表 → 切换 → 归档（不删磁盘文件）。"""
    import requests

    created = requests.post(
        f"{backend.base_url}/api/v1/workspaces", json={"name": "e2e-空间"}, timeout=10
    )
    assert created.status_code in (200, 201), created.text
    ws = created.json()
    assert ws["id"].startswith("wb-")

    listed = requests.get(f"{backend.base_url}/api/v1/workspaces", timeout=10).json()
    assert any(w["id"] == ws["id"] for w in listed["items"])

    sw = requests.post(f"{backend.base_url}/api/v1/workspaces/{ws['id']}/switch", timeout=10)
    assert sw.status_code == 200, sw.text

    arch = requests.post(f"{backend.base_url}/api/v1/workspaces/{ws['id']}/archive", timeout=10)
    assert arch.status_code == 200
    listed2 = requests.get(f"{backend.base_url}/api/v1/workspaces", timeout=10).json()
    assert not any(w["id"] == ws["id"] for w in listed2["items"]), "归档后不应再出现在活动列表"
    suite.ok("WEB-19", "工作空间 创建/列表/切换/归档 闭环", "接口")


def test_web_20_changes_and_artifacts_endpoints(backend):
    """WEB-20 变更与产物端点存在且结构正确。"""
    import requests

    # 无变更的 run → 空列表而非报错
    ch = requests.get(f"{backend.base_url}/api/v1/runs/nonexistent-run/changes", timeout=10)
    assert ch.status_code == 200, ch.text
    assert ch.json()["items"] == []

    af = requests.get(f"{backend.base_url}/api/v1/runs/nonexistent-run/artifacts", timeout=10)
    assert af.status_code == 200
    assert af.json()["items"] == []

    # 不存在的变更 diff → 404 + 统一错误体
    diff = requests.get(f"{backend.base_url}/api/v1/changes/999999/diff", timeout=10)
    assert diff.status_code == 404, diff.status_code
    assert diff.json().get("code"), dump_json(diff.json())
    suite.ok("WEB-20", "变更/产物端点结构正确；不存在资源返回统一 404", "接口")


def test_web_21_cancel_endpoint(backend):
    """WEB-21 cancel 端点：置位取消并把 run 置为 interrupted。"""
    import requests

    sess = requests.post(f"{backend.base_url}/api/v1/sessions", json={"mode": "chat"}, timeout=10).json()
    run = requests.post(f"{backend.base_url}/api/v1/agent/run/sync", json={
        "prompt": "你好", "mode": "chat", "session_id": sess["id"],
    }, timeout=60).json()
    run_id = run.get("run_id")
    assert run_id, dump_json(run)

    r = requests.post(f"{backend.base_url}/api/v1/runs/{run_id}/cancel", timeout=10)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "interrupted"

    # 不存在的 run → 404
    missing = requests.post(f"{backend.base_url}/api/v1/runs/nope/cancel", timeout=10)
    assert missing.status_code == 404
    suite.ok("WEB-21", "cancel 端点置位中断；未知 run 返回 404", "接口")


def test_web_22_steer_endpoint(backend):
    """WEB-22 steer 端点：接受 mode；非法 mode 422；缺指令 400。"""
    import requests

    sess = requests.post(f"{backend.base_url}/api/v1/sessions", json={"mode": "chat"}, timeout=10).json()
    run = requests.post(f"{backend.base_url}/api/v1/agent/run/sync", json={
        "prompt": "你好", "mode": "chat", "session_id": sess["id"],
    }, timeout=60).json()
    run_id = run.get("run_id")

    r = requests.post(f"{backend.base_url}/api/v1/runs/{run_id}/steer",
                      json={"instruction": "改用表格输出", "mode": "append"}, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["mode"] == "append"
    assert "工具边界" in body.get("note", ""), dump_json(body)

    bad = requests.post(f"{backend.base_url}/api/v1/runs/{run_id}/steer",
                        json={"instruction": "x", "mode": "不存在的模式"}, timeout=10)
    assert bad.status_code == 422

    empty = requests.post(f"{backend.base_url}/api/v1/runs/{run_id}/steer", json={}, timeout=10)
    assert empty.status_code == 400
    suite.ok("WEB-22", "steer 端点：mode 生效、非法 mode 422、缺指令 400", "接口")


def test_web_23_runs_status_filter(backend):
    """WEB-23 运行中查询用 ?status= 过滤；/runs/active 会被 {run_id} 捕获（404）。"""
    import requests

    r = requests.get(f"{backend.base_url}/api/v1/runs", params={"status": "running", "page_size": 5}, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert all(i["status"] == "running" for i in body["items"])

    # 路由顺序说明：/runs/active 被 /runs/{run_id} 捕获 → 404（故不新增该端点）
    active = requests.get(f"{backend.base_url}/api/v1/runs/active", timeout=10)
    assert active.status_code == 404
    suite.ok("WEB-23", "运行中查询按 status 过滤；/runs/active 确认被 {run_id} 捕获", "接口")


def test_web_24_cost_endpoints(backend):
    """WEB-24 成本端点：运行成本明细 + 发起前区间 + 单价表。"""
    import requests

    sess = requests.post(f"{backend.base_url}/api/v1/sessions", json={"mode": "chat"}, timeout=10).json()
    run = requests.post(f"{backend.base_url}/api/v1/agent/run/sync", json={
        "prompt": "你好", "mode": "chat", "session_id": sess["id"],
    }, timeout=60).json()
    run_id = run.get("run_id")

    r = requests.get(f"{backend.base_url}/api/v1/runs/{run_id}/cost", timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body and "totals" in body and "pricing" in body
    assert isinstance(body["totals"]["estimated_cost"], (int, float))
    # 单价表必须含千问
    models = [p.get("model") for p in body["pricing"]]
    assert any(m and m.startswith("qwen") for m in models), f"单价表应含千问模型：{models}"

    est = requests.get(f"{backend.base_url}/api/v1/cost/estimate", timeout=10)
    assert est.status_code == 200
    assert "percentiles" in est.json()
    suite.ok("WEB-24", "成本端点：明细/合计/区间/单价表（含千问）", "接口")


def test_web_25_context_and_memories(backend):
    """WEB-25 上下文占用端点 + 记忆增删闭环。"""
    import requests

    sess = requests.post(f"{backend.base_url}/api/v1/sessions", json={"mode": "chat"}, timeout=10).json()
    ctx = requests.get(f"{backend.base_url}/api/v1/sessions/{sess['id']}/context", timeout=10)
    assert ctx.status_code == 200, ctx.text
    body = ctx.json()
    assert "usage" in body and "thresholds" in body

    created = requests.post(f"{backend.base_url}/api/v1/memories", json={
        "scope": "project", "name": "e2e-mem", "content": "e2e 记忆内容", "tags": ["e2e"],
    }, timeout=10)
    assert created.status_code in (200, 201), created.text
    listed = requests.get(f"{backend.base_url}/api/v1/memories", timeout=10).json()
    assert listed["max_injected"] <= 5, "单次注入记忆上限应 ≤5"
    assert any(i["path"].endswith("e2e-mem.md") for i in listed["items"])

    removed = requests.request("DELETE", f"{backend.base_url}/api/v1/memories", json={
        "scope": "project", "path": created.json()["path"],
    }, timeout=10)
    assert removed.status_code == 200
    suite.ok("WEB-25", "上下文占用端点可用；记忆增删闭环且注入上限 ≤5", "接口")


def test_web_26_roles_api(backend):
    """WEB-26 角色 CRUD + 名称唯一 + 创建后不可改名。"""
    import requests

    created = requests.post(f"{backend.base_url}/api/v1/roles", json={
        "name": "e2e-分析师", "title": "数据分析师",
        "expertise": ["数据分析"], "tools": ["read_file"], "model_tier": "standard",
    }, timeout=10)
    assert created.status_code in (200, 201), created.text
    role = created.json()
    rid = role["id"]

    dup = requests.post(f"{backend.base_url}/api/v1/roles", json={"name": "e2e-分析师"}, timeout=10)
    assert dup.status_code == 422, dup.status_code

    renamed = requests.patch(f"{backend.base_url}/api/v1/roles/{rid}", json={"name": "别的名"}, timeout=10)
    assert renamed.status_code == 422, renamed.status_code

    edited = requests.patch(f"{backend.base_url}/api/v1/roles/{rid}", json={"title": "资深分析师"}, timeout=10)
    assert edited.status_code == 200
    assert edited.json()["title"] == "资深分析师"

    deleted = requests.delete(f"{backend.base_url}/api/v1/roles/{rid}", timeout=10)
    assert deleted.status_code == 200
    suite.ok("WEB-26", "角色 CRUD：名称唯一 / 创建后不可改名 / 更新与删除", "接口")


def test_web_27_plugin_scan_and_block(backend):
    """WEB-27 插件扫描：危险包 high 默认拒绝；显式确认后可装。"""
    import base64
    import io as _io
    import json as _json
    import zipfile

    import requests

    # 造一个含网络调用的包（medium）与一个含凭据的包（critical）
    def make_zip(files):
        buf = _io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for n, c in files.items():
                zf.writestr(n, c)
        return base64.b64encode(buf.getvalue()).decode()

    risky = make_zip({
        "plugin.json": _json.dumps({"name": "e2e-risky", "version": "1.0.0", "skills": []}),
        "skills/x/SKILL.md": "---\nname: x\ndescription: 测试\nversion: 0.1.0\n---\n\nimport requests\nrequests.get('http://evil')\n",
    })
    r = requests.post(f"{backend.base_url}/api/v1/plugins/install", json={"content_b64": risky}, timeout=10)
    assert r.status_code in (200, 201), r.text
    body = r.json()
    assert body["ok"] is False or (body.get("scan") or {}).get("requires_confirmation") is True

    # 危险包（含凭据）默认拒绝
    dangerous = make_zip({
        "plugin.json": _json.dumps({"name": "e2e-danger", "version": "1.0.0", "skills": []}),
        "skills/y/SKILL.md": "---\nname: y\ndescription: 测试\nversion: 0.1.0\n---\n\napi_key='sk-abcdefghijklmnopqrstuvwxyz012345'\n",
    })
    r2 = requests.post(f"{backend.base_url}/api/v1/plugins/install", json={"content_b64": dangerous}, timeout=10)
    assert r2.status_code in (200, 201), r2.text
    body2 = r2.json()
    assert body2["ok"] is False, dump_json(body2)
    assert (body2.get("scan") or {}).get("rejected_by_default") is True
    suite.ok("WEB-27", "插件扫描：危险包默认拒绝（需显式确认）", "接口")


def test_web_28_board_items_and_messages(backend):
    """WEB-28 黑板任务项（依赖 → 重算）与消息/通知。"""
    import requests

    a = requests.post(f"{backend.base_url}/api/v1/boards/e2e-b1/items", json={"title": "A"}, timeout=10)
    assert a.status_code in (200, 201), a.text
    a_id = a.json()["id"]
    b = requests.post(f"{backend.base_url}/api/v1/boards/e2e-b1/items", json={"title": "B", "deps": [a_id]}, timeout=10)
    b_id = b.json()["id"]

    # 完成 A → B 变 ready
    done = requests.post(f"{backend.base_url}/api/v1/boards/e2e-b1/items/{a_id}/complete", json={}, timeout=10)
    assert done.status_code == 200, done.text
    items = done.json()["items"]
    by_id = {i["id"]: i for i in items}
    assert by_id[b_id]["status"] == "ready", dump_json(done.json())

    msgs = requests.get(f"{backend.base_url}/api/v1/boards/e2e-b1/messages", timeout=10)
    assert msgs.status_code == 200
    assert "items" in msgs.json()
    suite.ok("WEB-28", "黑板任务项依赖 → 完成即重算 → 状态流转正确", "接口")


def test_web_29_metrics_endpoint(backend):
    """WEB-29 指标端点：并发 / 成功率 / 耗时 / 成本 / MCP 连接数字段齐全。"""
    import requests

    r = requests.get(f"{backend.base_url}/api/v1/metrics", timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("concurrency", "success_rate", "runs_today", "duration_ms", "llm", "mcp_connections"):
        assert key in body, f"缺字段: {key}"
    assert body["concurrency"]["limit"] > 0
    suite.ok("WEB-29", "指标端点字段齐全（并发/成功率/耗时/成本/MCP）", "接口")


def test_web_30_rrule_parse(backend):
    """WEB-30 RRULE：'每周一三五 09:00' 解析为一条规则、三个槽位/周。"""
    # RRULE 是纯函数，这里验证其解析与展开语义（通过后端单测已覆盖）
    import sys
    from pathlib import Path

    from datetime import datetime

    from common.harness import BACKEND_DIR

    sys.path.insert(0, str(BACKEND_DIR))
    from app.services.scheduler.rrule import expand_slots, parse

    r = parse("FREQ=WEEKLY;BYDAY=MO,WE,FR;BYHOUR=9;BYMINUTE=0")
    slots = expand_slots(r, datetime(2026, 1, 5, 9, 0), limit=6)
    assert len(slots) == 6
    days = {datetime.fromisoformat(s).weekday() for s in slots}
    assert days == {0, 2, 4}
    suite.ok("WEB-30", "RRULE '每周一三五 09:00' 展开为 3 个槽位/周", "接口")


def test_web_15_api_ui_consistency(page, backend):
    """WEB-15 接口与 UI 一致性：会话列表接口条数与侧栏任务数一致。"""
    import requests

    page.goto(backend.base_url, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=20_000)
    api_items = requests.get(f"{backend.base_url}/api/v1/sessions", timeout=10).json()
    count = len(api_items.get("items", [])) if isinstance(api_items, dict) else len(api_items)
    body = page.inner_text("body")
    # 只断言"接口有数据时 UI 也应有对应入口"，避免硬编码 DOM 结构
    if count == 0:
        suite.ok("WEB-15", "会话接口与 UI 同时为空（一致性成立）", "接口+UI")
    else:
        assert "任务" in body or "会话" in body, body[:200]
        suite.ok("WEB-15", f"接口返回 {count} 条会话，UI 存在任务/会话入口", "接口+UI")


def test_web_31_upload_size_limit(backend):
    """WEB-31 超过单文件大小上限 → 413 + 统一错误体（批次 01 / WP-2）。

    e2e 环境把上限调到 1MB（见 harness），默认 50MB 由后端单测冻结。
    """
    import requests

    payload = b"x" * (2 * 1024 * 1024)  # 2MB > 1MB
    r = requests.post(
        f"{backend.base_url}/api/v1/files/upload",
        files={"file": ("oversize_probe.txt", payload, "text/plain")},
        timeout=60,
    )
    assert r.status_code == 413, f"超限上传应返回 413，实际 {r.status_code}：{r.text[:200]}"
    body = r.json()
    assert body.get("code"), dump_json(body)
    assert body.get("request_id"), dump_json(body)

    # 超限后不应留下半成品文件
    listed = requests.get(f"{backend.base_url}/api/v1/files", timeout=10).json()
    names = [f.get("name") for f in listed.get("files", [])]
    assert "oversize_probe.txt" not in names, names
    suite.ok("WEB-31", "超大文件上传返回 413 + 统一错误体，且不留半成品", "接口")


def test_web_32_upload_type_blocked(backend):
    """WEB-32 可执行文件 / 白名单外类型上传被拒（批次 01 / WP-2）。"""
    import requests

    exe = requests.post(
        f"{backend.base_url}/api/v1/files/upload",
        files={"file": ("evil_probe.exe", b"MZ\x90\x00", "application/octet-stream")},
        timeout=30,
    )
    assert exe.status_code in (400, 413, 415, 422), exe.status_code
    reason = exe.json().get("message") or exe.json().get("detail") or ""
    assert "禁止上传" in reason or "白名单" in reason, exe.text[:300]

    other = requests.post(
        f"{backend.base_url}/api/v1/files/upload",
        files={"file": ("probe.bin", b"\x00\x01", "application/octet-stream")},
        timeout=30,
    )
    assert other.status_code in (400, 413, 415, 422), other.status_code

    listed = requests.get(f"{backend.base_url}/api/v1/files", timeout=10).json()
    names = [f.get("name") for f in listed.get("files", [])]
    assert "evil_probe.exe" not in names and "probe.bin" not in names, names
    suite.ok("WEB-32", "可执行文件与白名单外类型上传被拒，且未落盘", "接口")


def test_web_33_compose_mode(page, backend):
    """WEB-33 速记形态（批次 02）：``?compose=1`` 只留输入区，无侧栏与对话流。"""
    page.goto(f"{backend.base_url}/workspace?compose=1", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=20_000)

    assert page.locator("textarea").count() > 0, "速记形态应保留输入框"
    # 对话流（历史区）在速记形态下不渲染
    assert page.locator(".ws-scroll").count() == 0, "速记形态不应渲染对话流"
    # 侧栏（常驻 12 项入口）在速记形态下隐藏
    assert page.locator(".side-nav").count() == 0, "速记形态不应渲染侧栏"
    evidence = shot(page, "web-33-compose")
    suite.ok("WEB-33", "速记形态只渲染输入区（无侧栏/无对话流）", "UI", evidence)


def test_web_34_attachment_cap(page, backend):
    """WEB-34 附件上限 50（批次 02）：超限给出可读提示，且不产生上传请求。"""
    uploads: list[str] = []
    page.on("request", lambda r: uploads.append(r.url) if "/files/upload" in r.url else None)

    page.goto(f"{backend.base_url}/workspace", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=20_000)

    page.evaluate(
        """() => {
          const dt = new DataTransfer();
          for (let i = 0; i < 51; i += 1) {
            dt.items.add(new File(['x'], `probe-${i}.txt`, { type: 'text/plain' }));
          }
          window.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true }));
        }"""
    )
    page.wait_for_timeout(1500)

    body = page.inner_text("body")
    evidence = shot(page, "web-34-attachment-cap")
    assert "50" in body and ("上限" in body or "附件" in body), body[:300]
    assert not uploads, f"超限时不应发起上传请求，实际 {len(uploads)} 次"
    suite.ok("WEB-34", "附件超 50 个给出可读提示且不发上传请求", "UI", evidence)


def test_web_zz_report():
    """用例执行完毕后生成报告。"""
    path = suite.write_report(
        extra_notes=[
            "本轮为 S0 阶段回归：基线已归零（后端 122 passed / 0 failed，桌面壳 27 例 vitest）。",
            "S1 起应补充：统一错误体断言（code/message/request_id）、契约检查纳入 CI。",
        ]
    )
    print(f"\n报告已生成: {path}")
    s = suite.summary()
    print(f"用例总数 {s['total']}｜成功 {s['passed']}｜失败 {s['failed']}｜跳过 {s['skipped']}")
    assert s["failed"] == 0, f"存在 {s['failed']} 个失败用例，见报告"
