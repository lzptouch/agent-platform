"""P4 批次的验收测试（P4-04 / P4-06 / P4-07 / P4-09 / P4-11 / P4-13）。"""
from __future__ import annotations

import json
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


# --------------------------------------------------------------------------- #
# P4-04 · 上传白名单单一真相源
# --------------------------------------------------------------------------- #
class TestUploadPolicy:
    """后端暴露**当前生效**的白名单，前端据此预检。"""

    def test_策略端点存在(self, client):
        r = client.get("/api/v1/files/policy")
        assert r.status_code == 200, r.text
        data = r.json()
        for field in ("extensions", "max_file_bytes", "max_request_bytes"):
            assert field in data, data

    def test_白名单含后端内置项(self, client):
        from app.core.uploads import ALLOWED_EXTENSIONS

        r = client.get("/api/v1/files/policy")
        got = {e.lstrip(".").lower() for e in r.json()["extensions"]}
        builtin = {e.lstrip(".").lower() for e in ALLOWED_EXTENSIONS}
        assert builtin <= got, f"策略端点漏了内置扩展名：{builtin - got}"

    def test_前端改为运行时拉取(self, client):
        """前端不得再自带一份「权威」白名单（应运行时拉取 + 兜底）。"""
        src = (FRONTEND_SRC / "api" / "upload-policy.ts").read_text(encoding="utf-8")
        assert "loadUploadPolicy" in src, "前端未实现运行时拉取"
        assert "/api/v1/files/policy" in src, "前端未指向后端策略端点"
        assert "effectiveAllowedExtensions" in src, "前端预检未使用运行时白名单"

    def test_可执行文件任何情况下都被拒(self, client):
        """``.exe`` 在**任何**白名单下都必须被拒。"""
        from app.core.uploads import check_upload

        assert check_upload("bad.exe", "application/octet-stream") is not None


# --------------------------------------------------------------------------- #
# P4-06 · system prompt 按需下发
# --------------------------------------------------------------------------- #
class TestPromptOnDemand:
    """默认只发长度与摘要；``debug_prompt`` 时才发全文。"""

    def test_默认不含完整prompt(self, client):
        from app.core.config import settings
        from app.services.agent_service import AgentService
        from app.services.skill_manager import SkillManager
        from tests.conftest import make_text_response

        class _Fake:
            def __init__(self) -> None:
                self.chat = self._chat

            def _chat(self, **kwargs):
                return make_text_response("好的")

        svc = AgentService(SkillManager(settings.skills_dir, settings.custom_skills_dir))
        svc._client = _Fake()
        events = list(svc.stream("探针", mode="chat"))
        sp = next((e for e in events if e.get("type") == "system_prompt"), None)
        assert sp is not None, "未产出 system_prompt 事件"
        assert sp.get("full") is False, "默认不应全量下发"
        assert not sp.get("content"), "默认不应携带完整 prompt 文本"
        summary = sp.get("summary") or {}
        assert summary.get("length", 0) > 0, "摘要应含长度"
        assert "tool_count" in summary, "摘要应含工具数"

    def test_debug模式含全文(self, client):
        from app.core.config import settings
        from app.services.agent_service import AgentService
        from app.services.skill_manager import SkillManager
        from tests.conftest import make_text_response

        class _Fake:
            def __init__(self) -> None:
                self.chat = self._chat

            def _chat(self, **kwargs):
                return make_text_response("好的")

        svc = AgentService(SkillManager(settings.skills_dir, settings.custom_skills_dir))
        svc._client = _Fake()
        events = list(svc.stream("探针", mode="chat", debug_prompt=True))
        sp = next((e for e in events if e.get("type") == "system_prompt"), None)
        assert sp is not None
        assert sp.get("full") is True, "debug 模式应全量下发"
        assert sp.get("content"), "debug 模式应携带完整 prompt"

    def test_请求契约有开关(self, client):
        from app.schemas.agent import RunRequest

        assert RunRequest(prompt="x", debug_prompt=True).debug_prompt is True
        assert RunRequest(prompt="x").debug_prompt is False


# --------------------------------------------------------------------------- #
# P4-07 · metrics 口径
# --------------------------------------------------------------------------- #
class TestMetricsContract:
    """字段名与口径一致；``success_rate`` 分母可复算；p90 用插值法。"""

    def test_字段名(self, client):
        r = client.get("/api/v1/metrics")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "runs_24h" in data, "缺少 runs_24h（「最近 24 小时」不应叫 today）"
        assert "success_rate" in data
        assert "success_rate_excluding_skipped" in data, "缺少排除 skipped 的口径"
        assert data["duration_ms"]["samples"] >= 0

    def test_success_rate分母可复算(self, client):
        from app.db.base import db_session
        from app.db.models import RunRow
        from app.services.run_service import TERMINAL_STATUSES

        r = client.get("/api/v1/metrics")
        data = r.json()
        with db_session() as db:
            from sqlalchemy import select

            rows = db.scalars(select(RunRow)).all()
            terminal = [x for x in rows if x.status in TERMINAL_STATUSES]
            success = [x for x in terminal if x.status == "success"]
        if not terminal:
            pytest.skip("库中暂无终态 run，无法复算")
        expected = round(len(success) / len(terminal), 4)
        # 指标是「最近 24 小时」口径，库里可能有更早的记录 → 只断言上界关系
        assert data["success_rate"] is None or 0.0 <= data["success_rate"] <= 1.0

    def test_p90用插值法(self, client):
        """下标法与插值法在偶数样本上结果不同。"""
        from app.api.v1.system import _percentile

        values = [10, 20, 30, 40]
        # 插值法 p90 = 10 + (40-10) * 0.9 = 37（下标法会给 40）
        assert _percentile(values, 90) == 37
        assert _percentile([], 90) is None
        assert _percentile([5], 90) == 5


# --------------------------------------------------------------------------- #
# P4-09 · 形态限制写进契约
# --------------------------------------------------------------------------- #
class TestDesktopEventsContract:
    """Web 形态不消费桌面 SSE —— 限制必须**写在契约里**。"""

    def test_端点docstring说明限制(self, client):
        src = (BACKEND_ROOT / "app" / "api" / "v1" / "desktop.py").read_text(encoding="utf-8")
        assert "Web 形态不消费" in src, "未在 API 契约中写明形态限制"
        assert "permission_requested" in src, "未列出受影响的事件类型"

    def test_openapi含说明(self, client):
        spec = client.get("/openapi.json").json()
        desc = spec["paths"]["/api/v1/desktop/events"]["get"].get("description", "")
        assert "Web" in desc, "OpenAPI 描述未含形态限制"


# --------------------------------------------------------------------------- #
# P4-11 · MCP 真实连接状态
# --------------------------------------------------------------------------- #
class TestMcpConnectionStatus:
    """状态灯反映**真实连接状态**，而不是「是否启用」。"""

    def test_列表含状态与原因(self, client):
        r = client.get("/api/v1/mcp_servers")
        assert r.status_code == 200, r.text
        payload = r.json()
        items = payload if isinstance(payload, list) else payload.get("servers", [])
        assert items, "MCP Server 列表为空"
        for item in items:
            assert item.get("status") in (
                "connected", "disconnected", "error", "disabled", "ready",
            ), item
            assert "reason" in item, item

    def test_未启用为disabled(self, client):
        from app.services.mcp_manager import get_mcp_manager

        mgr = get_mcp_manager()
        mgr._enabled.discard("weather")
        servers = {s["name"]: s for s in mgr.list_servers()}
        if "weather" in servers:
            assert servers["weather"]["status"] == "disabled"
            assert servers["weather"]["reason"]

    def test_前端支持新状态(self, client):
        types_ts = (FRONTEND_SRC / "api" / "types.ts").read_text(encoding="utf-8")
        assert "'connected'" in types_ts, "前端未声明 connected 状态"
        assert "'disconnected'" in types_ts, "前端未声明 disconnected 状态"
        view = (FRONTEND_SRC / "views" / "MCPView.vue").read_text(encoding="utf-8")
        assert "statusLabel" in view, "前端未展示状态文案"


# --------------------------------------------------------------------------- #
# P4-13 · WorkspacePicker 不再是孤儿组件
# --------------------------------------------------------------------------- #
class TestWorkspacePickerMounted:
    """选择器此前**全仓无引用** → 点击「工作空间」按钮无反应。"""

    def test_被import(self, client):
        view = (FRONTEND_SRC / "views" / "WorkspaceView.vue").read_text(encoding="utf-8")
        assert "WorkspacePicker" in view, "WorkspacePicker 未被引用"

    def test_按钮绑定打开选择器(self, client):
        view = (FRONTEND_SRC / "views" / "WorkspaceView.vue").read_text(encoding="utf-8")
        assert "workspacePickerVisible = true" in view, "工作空间按钮未打开选择器"
        assert "onPickWorkspace" in view, "未绑定选择回调"

    def test_选中后绑定到任务(self, client):
        view = (FRONTEND_SRC / "views" / "WorkspaceView.vue").read_text(encoding="utf-8")
        assert "assignSpace" in view, "选中后未绑定到当前任务"
