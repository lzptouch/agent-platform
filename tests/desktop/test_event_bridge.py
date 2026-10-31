"""F-ENG-04 · 桌面事件桥的**端到端**断言（后端 SSE → 壳 → 渲染进程）。

此前这条链路的验收只有「桥两侧通道齐全 + `parseSseBuffer` 单测」的**静态契约**，
**没有 e2e 断言事件真的到达渲染进程** → 「贯通」不成立。

本测试用真实链路闭环：

1. 起桌面应用（Electron + sidecar）；
2. 通过 CDP 连到**渲染进程**（后端托管页面）；
3. 在渲染进程内**切换工作空间**（web API）→ 后端广播 ``workspace_changed``；
4. 事件经 sidecar 的 ``/desktop/events`` SSE → 壳的 IPC → 渲染进程的
   ``onBackendEvent`` → 前端消费者把它记进 ``window.__agentBackendEvents``；
5. 断言渲染进程**确实收到**该事件。

环境不具备（Electron 运行时缺失 / 壳未构建）时**跳过**并归类为环境问题。
"""
from __future__ import annotations

import time
from typing import Any

import pytest

from test_desktop_regression import electron_runtime  # noqa: F401 - 复用夹具


def _find_page(browser) -> Any:
    """在已连接的 CDP 浏览器里找**后端托管页面**（渲染进程）。"""
    for ctx in browser.contexts:
        for page in ctx.pages:
            if (page.url or "").startswith("http://127.0.0.1"):
                return page
    # 兜底：取第一个非 about:blank 页面
    for ctx in browser.contexts:
        for page in ctx.pages:
            if (page.url or "") != "about:blank":
                return page
    return None


class TestDesktopEventBridge:
    """F-ENG-04：事件贯通到渲染进程。"""

    def test_事件到达渲染进程(self, electron_runtime):
        """后端广播 → SSE → 壳 → IPC → 渲染进程（**端到端**）。"""
        from playwright.sync_api import sync_playwright

        page_url = electron_runtime.wait_for_backend_page(timeout=60)
        assert page_url, "渲染进程未加载后端托管页面（握手失败）"

        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(
                f"http://127.0.0.1:{electron_runtime.cdp_port}",
            )
            try:
                page = _find_page(browser)
                assert page is not None, "未找到渲染进程页面"

                # 消费者已挂载（前端实现）
                has_hook = page.evaluate(
                    "() => Array.isArray(window.__agentBackendEvents)",
                )
                assert has_hook, "渲染进程未挂载事件记录器（前端消费者未生效）"

                # 在渲染进程内**触发**一个会广播事件的操作
                # （Electron 用的是**独立 userData → 独立 DB** → 可能一个工作空间都没有，
                #  故先创建再切换）
                result = page.evaluate("""async () => {
                    const mk = await fetch('/api/v1/workspaces', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: 'f-eng-04-bridge' }),
                    })
                    const created = mk.ok ? await mk.json() : null
                    const list = await fetch('/api/v1/workspaces?include_archived=false')
                        .then(r => r.json())
                    const ws = (list.items || [])[0] || created
                    if (!ws) return { ok: false, reason: 'no-workspace' }
                    const res = await fetch(
                        `/api/v1/workspaces/${encodeURIComponent(ws.id)}/switch`,
                        { method: 'POST' },
                    )
                    return { ok: res.ok, ws: ws.id }
                }""")
                assert result.get("ok"), f"渲染进程内切换工作空间失败: {result}"

                # 等待事件**到达渲染进程**
                deadline = time.time() + 30
                types: list[str] = []
                while time.time() < deadline:
                    types = page.evaluate(
                        "() => (window.__agentBackendEvents || []).map(e => e.type)",
                    ) or []
                    if "workspace_changed" in types:
                        break
                    time.sleep(0.5)

                assert "workspace_changed" in types, (
                    f"事件未到达渲染进程（收到的类型: {types}）——"
                    "链路在后端 SSE → 壳 IPC 之间断开"
                )
            finally:
                try:
                    browser.close()
                except Exception:  # noqa: BLE001
                    pass

    def test_渲染进程消费者已实现(self):
        """静态契约：web 前端**确实**有事件消费者（不只类型声明）。"""
        from pathlib import Path

        repo = Path(__file__).resolve().parents[2]
        view = repo / "frontend" / "web" / "vue-element-plus" / "src" / "views" / "WorkspaceView.vue"
        text = view.read_text(encoding="utf-8")
        assert "onBackendEvent" in text, "web 前端未订阅后端事件"
        assert "subscribeBackendEvents()" in text, "订阅函数定义了却未被调用"

    def test_后端事件源一致(self):
        """Web 与桌面切换工作空间**都广播**事件（此前只有桌面广播）。"""
        from pathlib import Path

        repo = Path(__file__).resolve().parents[2]
        ws_api = (repo / "backend" / "app" / "api" / "v1" / "workspace.py").read_text(encoding="utf-8")
        assert 'bus.publish("workspace_changed"' in ws_api, (
            "Web 切换工作空间未广播事件（与桌面端点行为不一致）"
        )
