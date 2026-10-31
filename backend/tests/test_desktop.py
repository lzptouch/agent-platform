"""桌面端（Agent Desktop）后端测试。

覆盖：

- 三态权限引擎（``PermissionService``）：规则读写、判定顺序、档位聚合；
- 桌面配置服务（``DesktopService``）：配置读写、工作区校验与切换；
- 桌面端点（``/api/v1/desktop/*`` 与 ``/runs/{id}/cancel|steer``）；
- 会话引导与访问边界（``desktop/bootstrap``）。
"""
from __future__ import annotations

import asyncio
import os

import pytest
from fastapi.testclient import TestClient

from app.core import workspace as workspace_module
from app.core.config import settings
from app.desktop import bootstrap
from app.main import app
from app.services.desktop_service import DesktopService
from app.services.security.permissions import PermissionService


async def _take_first(agen):
    """取异步生成器的第一帧并立刻关闭它（不能把无限流交给 TestClient）。"""
    try:
        return await agen.__anext__()
    finally:
        await agen.aclose()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        c.get("/api/v1/health")  # 触发初始化
        yield c


@pytest.fixture(autouse=True)
def _reset_workspace():
    workspace_module.reset_workspace_dir()
    yield
    workspace_module.reset_workspace_dir()


# ====================================================================== #
# 权限引擎
# ====================================================================== #
class TestPermissionService:
    def test_default_decisions(self):
        svc = PermissionService()
        assert svc.classify("read_file").decision == "allow"
        assert svc.classify("execute_bash").decision == "ask"
        assert svc.classify("unknown_tool").decision == "ask"

    def test_high_risk_action_is_deny_by_default(self):
        svc = PermissionService()
        check = svc.classify("execute_bash", action="batch_delete")
        assert check.decision == "deny"
        assert check.denied is True

    def test_workspace_path_is_allowed(self):
        svc = PermissionService()
        inside = str(workspace_module.get_workspace_dir() / "note.txt")
        check = svc.classify("write_file", path=inside)
        assert check.decision == "allow"

    def test_outside_workspace_needs_ask(self):
        svc = PermissionService()
        # 用**平台中立**的绝对路径：Windows 风格的 "C:/Windows/..." 在 POSIX 上
        # 会被 normalize_path 当相对路径解析到 cwd 下，语义完全变了。
        outside = "C:/Windows/System32/drivers/etc/hosts" if os.name == "nt" else "/etc/hosts"
        check = svc.classify("read_file", path=outside)
        assert check.decision == "ask"

    def test_action_beats_path(self):
        """工作区内的批量删除也必须被拦（动作维度优先于路径维度）。"""
        svc = PermissionService()
        inside = str(workspace_module.get_workspace_dir())
        check = svc.classify("execute_bash", action="batch_delete", path=inside)
        assert check.decision == "deny"

    def test_set_and_match_path_prefix_rule(self, tmp_path):
        """路径前缀规则命中即 deny（规则的目标是**目录前缀**，不是精确路径）。

        平台中立：用 tmp_path 构造一个"工作区外的目录"，
        不用硬编码 Windows 路径——那在 POSIX 上会被当成相对路径，测不到本意。
        """
        svc = PermissionService()
        restricted = tmp_path / "restricted"
        restricted.mkdir()
        svc.set_rule("path", str(restricted), "deny")
        check = svc.classify("read_file", path=str(restricted / "x.dll"))
        assert check.decision == "deny"

    def test_effective_level_aggregation(self):
        svc = PermissionService()
        assert svc.effective_level() == "ask"
        svc.set_level("allow")
        assert svc.effective_level() == "allow"
        svc.set_level("readonly")
        assert svc.effective_level() == "readonly"

    def test_record_hit_increments(self):
        svc = PermissionService()
        svc.set_rule("tool", "execute_bash", "ask")
        svc.record_hit("tool", "execute_bash")
        rules = {r["target"]: r for r in svc.list_rules()}
        assert rules["execute_bash"]["hit_count"] == 1


# ====================================================================== #
# 配置与工作区
# ====================================================================== #
class TestDesktopService:
    def test_preferences_default_and_update(self):
        svc = DesktopService()
        prefs = svc.get_preferences()
        assert prefs["default_mode"] == "chat"
        updated = svc.update_preferences({"default_mode": "work", "notify_channel": "toast"})
        assert updated["default_mode"] == "work"
        assert updated["notify_channel"] == "toast"

    def test_update_preferences_rejects_bad_mode(self):
        svc = DesktopService()
        with pytest.raises(ValueError):
            svc.update_preferences({"default_mode": "bogus"})

    def test_workspace_requires_absolute_path(self):
        svc = DesktopService()
        with pytest.raises(ValueError):
            svc.set_workspace("relative/path")

    def test_workspace_rejects_missing_dir(self):
        svc = DesktopService()
        with pytest.raises(ValueError):
            svc.set_workspace("C:/definitely/not/exist/xyz")

    def test_workspace_set_ok_and_immediate(self, tmp_path):
        svc = DesktopService()
        result = svc.set_workspace(str(tmp_path))
        assert result["ok"] is True
        assert result["effective"] == "immediate"
        assert workspace_module.get_workspace_dir() == tmp_path.resolve()
        assert svc.get_workspace()["writable"] is True

    def test_components_shape(self):
        svc = DesktopService()
        comps = svc.components()
        assert "playwright_chromium" in comps
        assert "installed" in comps["playwright_chromium"]


# ====================================================================== #
# 端点（非桌面模式下也应可用——守卫只在桌面模式启用）
# ====================================================================== #
class TestDesktopAPI:
    def test_status(self, client):
        r = client.get("/api/v1/desktop/status")
        assert r.status_code == 200
        data = r.json()
        assert data["protocol"] >= 1
        assert "runtime" in data and "security" in data

    def test_preferences_roundtrip(self, client):
        assert client.get("/api/v1/desktop/preferences").status_code == 200
        r = client.put("/api/v1/desktop/preferences", json={"default_mode": "work"})
        assert r.status_code == 200
        assert r.json()["preferences"]["default_mode"] == "work"
        assert client.put(
            "/api/v1/desktop/preferences", json={"default_mode": "bogus"}
        ).status_code == 422

    def test_permissions_crud(self, client):
        r = client.get("/api/v1/desktop/permissions")
        assert r.status_code == 200
        assert "effective_level" in r.json()
        r = client.put(
            "/api/v1/desktop/permissions",
            json={"scope": "tool", "target": "execute_bash", "decision": "allow"},
        )
        assert r.status_code == 200
        assert r.json()["rule"]["decision"] == "allow"
        assert client.put(
            "/api/v1/desktop/permissions",
            json={"scope": "tool", "target": "x", "decision": "bogus"},
        ).status_code == 422

    def test_workspace_endpoints(self, client, tmp_path):
        assert client.get("/api/v1/desktop/workspace").status_code == 200
        r = client.put("/api/v1/desktop/workspace", json={"path": str(tmp_path)})
        assert r.status_code == 200
        assert r.json()["effective"] == "immediate"
        assert client.put("/api/v1/desktop/workspace", json={"path": "rel"}).status_code == 400
        assert client.put("/api/v1/desktop/workspace", json={}).status_code == 400

    def test_resume_scan(self, client):
        r = client.post("/api/v1/desktop/scheduler/resume-scan", json={})
        assert r.status_code == 200
        body = r.json()
        assert "rescued" in body and "skipped" in body

    def test_events_hello(self, client):
        """SSE 首帧必须是 hello。

        用 ``max_events=1`` 的**有界模式**：Starlette 的 TestClient 会先把
        响应体收完再返回，对无限流端点来说无界模式在测试里必然挂死。
        """
        with client.stream("GET", "/api/v1/desktop/events?max_events=1") as r:
            assert r.status_code == 200
            assert "text/event-stream" in r.headers.get("content-type", "")
            first = next(iter(r.iter_text()), "")
            assert '"type": "hello"' in first

    def test_events_unbounded_starts_with_hello(self):
        """默认（无界）模式也必须先发 hello——桌面壳靠它确认协议版本。

        这里直接取生成器的首帧就收手：不能把无限流交给 TestClient。
        """
        from app.api.v1.desktop import desktop_events

        resp = desktop_events(after_id=0, max_events=None)
        assert resp.media_type == "text/event-stream"
        first = asyncio.run(_take_first(resp.body_iterator))
        assert '"type": "hello"' in first
        assert '"protocol": 1' in first

    def test_run_cancel_and_steer_not_found(self, client):
        assert client.post("/api/v1/runs/nope/cancel").status_code == 404
        assert client.post("/api/v1/runs/nope/steer", json={"instruction": "x"}).status_code == 404
        assert client.post("/api/v1/runs/nope/steer", json={}).status_code == 404


# ====================================================================== #
# 会话引导与访问边界（单元级）
# ====================================================================== #
class TestBootstrap:
    def setup_method(self):
        bootstrap.reset_state()

    def teardown_method(self):
        bootstrap.reset_state()
        for key in ("AGENT_DESKTOP", "AGENT_DESKTOP_TOKEN", "AGENT_DESKTOP_BOOTSTRAP_NONCE"):
            os.environ.pop(key, None)

    def _enable(self, token="tok123", nonce="nonce456"):
        os.environ["AGENT_DESKTOP"] = "1"
        os.environ["AGENT_DESKTOP_TOKEN"] = token
        os.environ["AGENT_DESKTOP_BOOTSTRAP_NONCE"] = nonce

    def test_nonce_single_use(self):
        self._enable()
        assert bootstrap.consume_nonce("nonce456") is True
        assert bootstrap.consume_nonce("nonce456") is False  # 已作废
        assert bootstrap.consume_nonce("wrong") is False

    def test_issue_session_requires_token(self):
        with pytest.raises(RuntimeError):
            bootstrap.issue_session()
        self._enable()
        sid = bootstrap.issue_session()
        assert sid and bootstrap.current_session_id() == sid
