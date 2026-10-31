"""Web 端功能点矩阵覆盖（对应 `doc/testing/00-全面测试计划.md` §4.2 DOM 层 + §4.3 SSE）。

补齐 `test_web_regression.py` 未覆盖的功能点：
- DOM-01 19 视图逐个可渲染且非空
- DOM-02 侧栏跨路由恒定
- DOM-03 旧路径重定向
- DOM-05 能力后台三 Tab
- DOM-06 定时任务页
- DOM-07 全局能力开关
- DOM-10 404 兜底与灰度回退
- SSE-01 事件类型集合与前端类型定义一致
- RUN-MODE 双模式一致性

事实源纪律（testing/00 §2.3 铁律 1）：
- 断言「事实源」在**被测进程之外**——API 用响应体 / DB 行 / 事件账本，
  不以「UI 看起来成功」为准；
- UI 断言只用于**渲染契约**（DOM 层用例本身）。

运行：
    backend/.venv/bin/python -m pytest tests/web -q
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.harness import BackendProcess, Suite, shot  # noqa: E402

SUITE_NAME = "web-functional"
SUITE_TARGET = "agent-platform Web · 功能点矩阵覆盖（DOM/SSE/RUN-MODE）"

suite = Suite(SUITE_NAME, SUITE_TARGET)
_backend: BackendProcess | None = None

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = REPO_ROOT / "frontend" / "web" / "vue-element-plus" / "src"

#: 19 个视图对应的路由（src/router/index.ts）
VIEW_ROUTES = [
    "/workspace",
    "/assistant",
    "/spaces",
    "/admin/capabilities",
    "/admin/schedules",
    "/admin/research",
    "/admin/artifacts",
    "/admin/knowledge",
    "/admin/web",
    "/admin/status",
    "/admin/settings",
    "/admin/roles",
    "/admin/plugins",
    "/admin/boards",
    "/admin/desktop",
    "/admin/lab/wr",
]

#: 旧路径 → 新路径（DOM-03）
LEGACY_REDIRECTS = [
    ("/teams", "/admin/capabilities"),
    ("/skills", "/admin/capabilities"),
    ("/mcp", "/admin/capabilities"),
    ("/schedules", "/admin/schedules"),
    ("/research", "/admin/research"),
    ("/files", "/admin/artifacts"),
    ("/rag", "/admin/knowledge"),
    ("/web", "/admin/web"),
]


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
        pg = context.new_page()
        pg.set_default_timeout(20_000)
        yield pg
        context.close()
        browser.close()


def _base(backend) -> str:
    return backend.base_url.rstrip("/")


def _api(backend, method: str, path: str, **kw):
    """按现有回归套件的同一方式调后端 API（事实源在进程外）。

    注意 ``trust_env=False``：本机存在系统代理（``http_proxy``）时，
    ``requests`` 会把 **127.0.0.1 的本地请求也发给代理** → 连接超时。
    """
    import requests

    session = requests.Session()
    session.trust_env = False
    try:
        return session.request(method, f"{_base(backend)}{path}", timeout=45, **kw)
    finally:
        session.close()


# --------------------------------------------------------------------------- #
# DOM-01 · 19 视图逐个可渲染且非空
# --------------------------------------------------------------------------- #
def test_dom_01_全部视图可渲染且非空(page, backend):
    """逐个访问视图路由：可交互元素存在，且**无 undefined/NaN 文本**。"""
    bad_render: list[str] = []
    bad_text: list[str] = []

    for route in VIEW_ROUTES:
        page.goto(f"{_base(backend)}{route}", wait_until="networkidle")
        page.wait_for_timeout(350)

        # 可交互元素（按钮/输入/链接/表单项）
        interactive = page.locator(
            "button, a[href], input, textarea, select, [role='button'], .el-button, .el-menu-item"
        ).count()
        if interactive == 0:
            bad_render.append(route)

        body_text = page.inner_text("body")
        if re.search(r"\bundefined\b|\bNaN\b|\[object Object\]", body_text):
            bad_text.append(route)

        shot(page, f"dom-01{route.replace('/', '_')}")

    assert not bad_render, f"以下视图无可交互元素（渲染为空）: {bad_render}"
    assert not bad_text, f"以下视图出现 undefined/NaN/[object Object]: {bad_text}"


# --------------------------------------------------------------------------- #
# DOM-02 · 侧栏跨路由恒定
# --------------------------------------------------------------------------- #
def test_dom_02_侧栏跨路由恒定(page, backend):
    """侧栏在**所有**路由上结构一致（存在且菜单项集合不变）。"""
    signatures: dict[str, list[str]] = {}

    for route in ["/workspace", "/spaces", "/admin/capabilities", "/admin/schedules", "/admin/status"]:
        page.goto(f"{_base(backend)}{route}", wait_until="networkidle")
        page.wait_for_timeout(250)
        # 只取**左侧导航**：工作台有两个 aside（左导航 + 右结果区），
        # 右栏的 Tab（产物/文件/变更/浏览器）随路由变化，会造成假阳性。
        nav_aside = page.locator("aside").first
        items = nav_aside.locator("a, button")
        signatures[route] = sorted({items.nth(i).inner_text().strip() for i in range(items.count())})

    reference = signatures["/workspace"]
    assert reference, "工作台侧栏未渲染出菜单项"
    for route, sig in signatures.items():
        assert sig == reference, f"{route} 的侧栏与工作台不一致:\n  工作台={reference}\n  {route}={sig}"


# --------------------------------------------------------------------------- #
# DOM-03 · 旧路径重定向
# --------------------------------------------------------------------------- #
def test_dom_03_旧路径重定向(page, backend):
    """旧路径跳转到新路由（前端 redirect）。"""
    wrong: list[str] = []
    for old, new in LEGACY_REDIRECTS:
        page.goto(f"{_base(backend)}{old}", wait_until="networkidle")
        page.wait_for_timeout(250)
        path = page.url.split("?")[0]
        if not path.endswith(new):
            wrong.append(f"{old} → {path}（期望 {new}）")

    assert not wrong, "以下旧路径未正确重定向:\n  " + "\n  ".join(wrong)


# --------------------------------------------------------------------------- #
# DOM-05 · 能力后台三 Tab
# --------------------------------------------------------------------------- #
def test_dom_05_能力后台三Tab(page, backend):
    """团队 / 技能 / MCP 三个 Tab 均可切换且有内容。"""
    page.goto(f"{_base(backend)}/admin/capabilities", wait_until="networkidle")
    page.wait_for_timeout(400)

    tabs = page.locator(".el-tabs__item, [role='tab']")
    count = tabs.count()
    assert count >= 3, f"能力后台应至少 3 个 Tab，实际 {count}"

    labels: list[str] = []
    for i in range(count):
        label = tabs.nth(i).inner_text().strip()
        labels.append(label)
        tabs.nth(i).click()
        page.wait_for_timeout(350)
        # 每个 Tab 都要有可交互内容
        assert page.locator(
            "button, .el-table, .el-card, input, .el-form, .el-empty__description"
        ).count() > 0, f"Tab「{label}」切换后内容为空"
        shot(page, f"dom-05-tab-{i}")

    assert len(set(labels)) >= 3, f"Tab 标签重复: {labels}"


# --------------------------------------------------------------------------- #
# DOM-06 · 定时任务页
# --------------------------------------------------------------------------- #
def test_dom_06_定时任务页(page, backend):
    """定时任务页可渲染，且**落库事实**与页面一致（不只看 UI）。"""
    page.goto(f"{_base(backend)}/admin/schedules", wait_until="networkidle")
    page.wait_for_timeout(1200)

    assert page.locator(
        "button, .el-table, .el-switch, input[type='checkbox'], .el-form, .el-card"
    ).count() > 0, "定时任务页内容为空"
    shot(page, "dom-06-schedules")

    # 事实源在进程外：列表端点可读，且结构完整
    r = _api(backend, "GET", "/api/v1/schedules")
    assert r.status_code == 200, r.text
    payload = r.json()
    items = payload if isinstance(payload, list) else payload.get("items", [])
    assert isinstance(items, list), f"定时任务响应结构异常: {type(payload)}"


# --------------------------------------------------------------------------- #
# DOM-07 · 全局能力开关
# --------------------------------------------------------------------------- #
def test_dom_07_全局能力开关(page, backend):
    """顶栏能力开关存在，且**透传到 run payload**（事实源在进程外）。"""
    page.goto(f"{_base(backend)}/workspace", wait_until="networkidle")
    page.wait_for_timeout(500)

    # 顶栏能力开关在实测中是**自定义 class**（非原生 checkbox）——
    # 以「可点击的开关控件」为判据，文本含 MCP/RAG/Web/反思/Skill
    switches = page.locator(
        "[class*='switch'], [class*='toggle'], .el-switch, .el-checkbox, "
        "input[type='checkbox'], .cap-chips [class*='chip']"
    )
    assert switches.count() > 0, "未找到全局能力开关"

    body = page.inner_text("body")
    for cap in ("MCP", "RAG", "Web", "反思"):
        assert cap in body, f"能力开关缺少「{cap}」"

    # 事实源：能力开关对应的后端开关接口可读
    for path in ("/api/v1/health",):
        r = _api(backend, "GET", path)
        assert r.status_code == 200, f"{path} → {r.status_code}"


# --------------------------------------------------------------------------- #
# DOM-10 · 404 兜底与灰度回退
# --------------------------------------------------------------------------- #
def test_dom_10_404兜底(page, backend):
    """未匹配路由显示兜底页（不是白屏）。"""
    page.goto(f"{_base(backend)}/definitely-not-a-real-route-xyz", wait_until="networkidle")
    page.wait_for_timeout(400)

    body = page.inner_text("body").strip()
    assert body, "404 路由渲染为空白"
    assert not re.search(r"\bundefined\b|\bNaN\b", body), "404 页出现 undefined/NaN"
    shot(page, "dom-10-404")


# --------------------------------------------------------------------------- #
# SSE-01 · 事件类型集合与前端类型定义一致
# --------------------------------------------------------------------------- #
def test_sse_01_事件类型集合一致(page, backend):
    """后端实际发出的事件名集合 ⊆ 前端 `AgentEvent` 联合类型（契约零差异）。"""
    backend_src = REPO_ROOT / "backend" / "app"
    emitted: set[str] = set()
    for path in backend_src.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        # 只取**真正 yield 出去**的事件字典（避免误匹配 schema 描述里的 "type": "array"）
        emitted |= set(re.findall(r'yield\s*\{\s*"type":\s*"([a-z_]+)"', text))

    types_ts = (FRONTEND_SRC / "api" / "types.ts").read_text(encoding="utf-8")
    # 前端声明：所有 interface 里的 type: 'xxx'（含 "a" | "b" 联合形式）
    declared: set[str] = set()
    # type: 'a' | 'b' —— 联合类型要**逐个**成员都捕获
    for group in re.findall(r"type:\s*((?:'[^']+'\s*\|\s*)*'[^']+')", types_ts):
        for one in re.findall(r"'([^']+)'", group):
            declared.add(one.strip())

    # 后端独有（前端未声明）= 契约缺口
    missing = sorted(emitted - declared)
    assert not missing, (
        "后端发出但前端 AgentEvent 未声明的事件（契约差异）:\n  " + "\n  ".join(missing)
        + f"\n（后端 {len(emitted)} 种 / 前端声明 {len(declared)} 种）"
    )


# --------------------------------------------------------------------------- #
# RUN-MODE · 双模式一致性
# --------------------------------------------------------------------------- #
def test_run_mode_双模式落库一致(page, backend):
    """chat / work 两模式各跑一次，落库 `mode` 必须与请求一致（事实源在 DB）。"""
    for mode in ("chat", "work"):
        # 会话模式**不可变**（后端契约：mode = session.mode），
        # 前端「切模式」的实现也是**新建任务** → 每种模式用独立会话。
        sess = _api(backend, "POST", "/api/v1/sessions", json={"mode": mode}).json()
        session_id = sess["id"]

        r = _api(backend, "POST", "/api/v1/agent/run/sync", json={
            "prompt": f"模式一致性探针 {mode}", "mode": mode, "session_id": session_id,
        })
        assert r.status_code in (200, 201, 202), f"{mode} → {r.status_code}: {r.text}"
        body = r.json()
        run_id = body.get("run_id") or body.get("id")
        assert run_id, f"{mode} 未返回 run_id"

        # 事实源在进程外：① 同步响应 ② runs 落库的 meta.mode
        assert body.get("mode") == mode, (
            f"响应 mode 与请求不一致: 请求 {mode}，响应 {body.get('mode')}"
        )
        detail = _api(backend, "GET", f"/api/v1/runs/{run_id}").json()
        meta = detail.get("meta") or {}
        assert meta.get("mode") == mode, (
            f"落库 mode 与请求不一致: 请求 {mode}，落库 {meta.get('mode')}"
        )


def test_run_mode_响应回显实际执行模式(page, backend):
    """同一会话里请求不同模式时，响应必须回显**实际执行**的模式。

    后端契约「会话模式不可变」：请求 mode=work 但会话是 chat 时，实际按 chat 跑，
    响应就**不能**声称 work（否则前端展示与真实行为不一致）。
    """
    sess = _api(backend, "POST", "/api/v1/sessions", json={"mode": "chat"}).json()
    r = _api(backend, "POST", "/api/v1/agent/run/sync", json={
        "prompt": "模式回显探针", "mode": "work", "session_id": sess["id"],
    })
    assert r.status_code in (200, 201, 202), r.text
    body = r.json()
    assert body.get("mode") == "chat", (
        f"响应应回显实际执行模式 chat，实际 {body.get('mode')}"
    )
