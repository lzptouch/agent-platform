"""F-UX-02 · 浏览器视图的**真实数据源**验收测试。

此前结果区四视图里，「浏览器」是**唯一没有数据源的占位**
（「自动化任务页面/截图，后续接入」）→ 验收标准「浏览器视图有真实数据」不成立。

现在数据源 = **浏览器类产物**（``artifacts.kind === 'browser'`` + 来源 URL）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_SRC = BACKEND_ROOT.parent / "frontend" / "web" / "vue-element-plus" / "src"


@pytest.fixture()
def client():
    from starlette.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


class TestBrowserArtifactSource:
    """浏览器类产物的登记与回显。"""

    def test_登记支持kind与url(self, client, tmp_path):
        from app.services.workspace import artifacts as art

        shot = tmp_path / "shot.png"
        shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
        rec = art.register_artifact(
            "ux02-run", None, tmp_path, shot,
            title="商品页", kind="browser", url="https://example.com/item/1",
        )
        assert rec["kind"] == "browser", rec
        assert rec["url"] == "https://example.com/item/1", rec

    def test_列表回显kind与url(self, client, tmp_path):
        from app.services.workspace import artifacts as art

        shot = tmp_path / "shot.png"
        shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
        art.register_artifact(
            "ux02-run-2", None, tmp_path, shot,
            kind="browser", url="https://example.com/item/2",
        )
        items = art.list_artifacts("ux02-run-2")
        assert items, "产物列表为空"
        hit = next(i for i in items if i["kind"] == "browser")
        assert hit["url"] == "https://example.com/item/2", hit

    def test_普通产物不受影响(self, client, tmp_path):
        """普通文件仍按扩展名推断 kind，且 url 为空。"""
        from app.services.workspace import artifacts as art

        doc = tmp_path / "a.md"
        doc.write_text("x", encoding="utf-8")
        rec = art.register_artifact("ux02-run-3", None, tmp_path, doc)
        assert rec["kind"] != "browser", rec
        assert not rec.get("url"), rec

    def test_emit_artifact工具可登记浏览器页面(self, client, tmp_path):
        """工具层能登记 kind=browser + url（前端视图的数据入口）。"""
        from app.services.tool_registry import ToolRegistry
        from app.services.workspace.service import current_run_context

        shot = tmp_path / "page.png"
        shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
        token = current_run_context.set({
            "run_id": "ux02-tool-run",
            "workspace_id": None,
            "workspace_root": str(tmp_path),
        })
        try:
            out = ToolRegistry._emit_artifact({
                "path": str(shot),
                "title": "详情页",
                "kind": "browser",
                "url": "https://example.com/detail",
            })
        finally:
            current_run_context.reset(token)

        assert out.get("registered") is True, out
        art = out["artifact"]
        assert art["kind"] == "browser", art
        assert art["url"] == "https://example.com/detail", art

    def test_表有url列(self, client):
        from app.db.models import ArtifactRow

        assert "url" in ArtifactRow.__table__.columns


class TestBrowserViewFrontend:
    """前端「浏览器」视图不再是占位。"""

    def test_存在独立组件(self, client):
        assert (FRONTEND_SRC / "components" / "ResultBrowser.vue").exists(), (
            "缺 ResultBrowser.vue（浏览器视图仍无实现）"
        )

    def test_面板接线该组件(self, client):
        text = (FRONTEND_SRC / "components" / "ResultPanel.vue").read_text(encoding="utf-8")
        assert "ResultBrowser" in text, "ResultPanel 未接线浏览器视图"
        assert "浏览器视图（自动化任务页面/截图，后续接入）" not in text, (
            "浏览器视图仍是占位文案"
        )

    def test_组件按kind筛选(self, client):
        text = (FRONTEND_SRC / "components" / "ResultBrowser.vue").read_text(encoding="utf-8")
        assert "kind === 'browser'" in text, "未按 kind=browser 筛选"

    def test_展示来源地址(self, client):
        text = (FRONTEND_SRC / "components" / "ResultBrowser.vue").read_text(encoding="utf-8")
        assert "p.url" in text, "未展示来源页面地址"
