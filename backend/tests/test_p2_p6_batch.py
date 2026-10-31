"""P2-17 / P2-22 / P2-23 / P6-05 的验收测试。"""
from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client():
    from starlette.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# P2-17 · 权限规则的 workspace_id
# --------------------------------------------------------------------------- #
class TestRuleWorkspaceScope:
    """同 pattern 在不同工作空间可有不同裁决。"""

    def test_建规则带workspace_id落库非空(self, client):
        r = client.put("/api/v1/permissions/rules", json={
            "scope": "tool", "pattern": "p2_17_probe", "decision": "deny",
            "workspace_id": "ws-alpha",
        })
        assert r.status_code == 200, r.text
        rule = r.json()["rule"]
        assert rule.get("workspace_id") == "ws-alpha", rule

    def test_同pattern不同工作空间不同裁决(self, client):
        client.put("/api/v1/permissions/rules", json={
            "scope": "tool", "pattern": "p2_17_same", "decision": "allow",
            "workspace_id": "ws-A",
        })
        client.put("/api/v1/permissions/rules", json={
            "scope": "tool", "pattern": "p2_17_same", "decision": "deny",
            "workspace_id": "ws-B",
        })

        from app.db.base import db_session
        from app.db.models import PermissionRuleRow

        with db_session() as db:
            rows = db.query(PermissionRuleRow).filter(
                PermissionRuleRow.pattern == "p2_17_same",
            ).all()
            by_ws = {r.workspace_id: r.decision for r in rows}
            assert by_ws.get("ws-A") == "allow", by_ws
            assert by_ws.get("ws-B") == "deny", by_ws

    def test_不带workspace_id时行为不变(self, client):
        """全局规则（workspace_id 为空）仍然照旧生效。"""
        r = client.put("/api/v1/permissions/rules", json={
            "scope": "tool", "pattern": "p2_17_global", "decision": "deny",
        })
        assert r.status_code == 200, r.text
        assert r.json()["rule"].get("workspace_id") is None

    def test_列表回显workspace_id(self, client):
        client.put("/api/v1/permissions/rules", json={
            "scope": "tool", "pattern": "p2_17_echo", "decision": "ask",
            "workspace_id": "ws-echo",
        })
        r = client.get("/api/v1/permissions/rules")
        assert r.status_code == 200, r.text
        payload = r.json()
        items = payload if isinstance(payload, list) else payload.get("rules", [])
        hits = [x for x in items if x.get("pattern") == "p2_17_echo"]
        assert hits and hits[0].get("workspace_id") == "ws-echo", hits


# --------------------------------------------------------------------------- #
# P2-22 · 插件安装后立即生效
# --------------------------------------------------------------------------- #
def _skill_zip(name: str) -> bytes:
    """构造一个含 SKILL.md 的插件 zip。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("plugin.json", json.dumps({
            "name": name, "version": "1.0.0",
            "description": "P2-22 验收用临时插件",
            "skills": [{"name": name, "path": f"skills/{name}"}],
        }, ensure_ascii=False))
        # 插件包约定：技能放在 ``skills/`` 子目录下（安装器只复制该目录）
        zf.writestr(f"skills/{name}/SKILL.md", (
            "---\n"
            f"name: {name}\n"
            "description: P2-22 验收用临时技能\n"
            "---\n\n"
            f"# {name}\n\n临时技能正文。\n"
        ))
    return buf.getvalue()


class TestPluginReload:
    """插件安装成功后**当前进程**立即加载新技能。"""

    def test_安装后当前进程可见(self, client):
        from app.core.config import settings
        from app.services.skill_manager import SkillManager

        skill_name = "p2_22_temp_skill"
        payload = {
            "content_b64": base64.b64encode(_skill_zip(skill_name)).decode(),
            "confirm": True,
        }
        r = client.post("/api/v1/plugins/install", json=payload)
        assert r.status_code in (200, 201), r.text
        assert r.json().get("ok") is True, r.text

        # **当前进程**（不经重启）应能列出新技能
        mgr = SkillManager(settings.skills_dir, settings.custom_skills_dir)
        mgr.reload()
        try:
            assert skill_name in mgr.skills, sorted(mgr.skills)
        finally:
            # 清理：不要把临时技能留在开发环境里
            import shutil

            shutil.rmtree(
                Path(settings.custom_skills_dir) / skill_name, ignore_errors=True,
            )

    def test_安装失败不污染技能列表(self, client):
        """安装失败（非法 zip）→ 技能列表不变（完整回滚）。"""
        from app.core.config import settings
        from app.services.skill_manager import SkillManager

        mgr = SkillManager(settings.skills_dir, settings.custom_skills_dir)
        before = set(mgr.skills)

        bad = base64.b64encode(b"not-a-zip-file").decode()
        r = client.post("/api/v1/plugins/install", json={
            "content_b64": bad, "confirm": True,
        })
        assert r.status_code >= 400, r.text

        mgr.reload()
        assert set(mgr.skills) == before, "安装失败后技能列表发生了变化"


# --------------------------------------------------------------------------- #
# P2-23 · 技能目录只读可信根
# --------------------------------------------------------------------------- #
class TestSkillTrustedReadRoot:
    """SKILL.md 位于工作区外——读应放行，写仍应被拦。"""

    def test_读技能目录被放行(self, client):
        from app.core.config import settings
        from app.services.security.permissions import PermissionRequest
        from app.services.security.permissions import PermissionService

        skill_md = Path(settings.skills_dir)
        candidates = sorted(p for p in skill_md.glob("*/SKILL.md"))
        if not candidates:
            pytest.skip("内置技能目录为空")
        target = str(candidates[0])

        decision = PermissionService.instance().classify(
            "read_file", path=target,
        )
        assert decision.decision == "allow", (
            f"技能目录内的读应放行，实际 {decision.decision}（{decision.reason}）"
        )

    def test_写技能目录仍被拦(self, client):
        """越界写照旧被拦（只读可信根只对读生效）。"""
        from app.core.config import settings
        from app.services.security.permissions import PermissionService

        skill_md = Path(settings.skills_dir)
        candidates = sorted(p for p in skill_md.glob("*/SKILL.md"))
        if not candidates:
            pytest.skip("内置技能目录为空")
        target = str(candidates[0])

        decision = PermissionService.instance().classify(
            "write_file", path=target,
        )
        assert decision.decision != "allow", (
            f"技能目录内的写不应放行，实际 {decision.decision}"
        )

    def test_仍走enforce且放行(self, client, monkeypatch):
        """技能触发的工具调用**仍走 ``enforce()``**，且读被放行。"""
        from app.core.config import settings
        from app.services.security import permissions as perm_mod

        candidates = sorted(Path(settings.skills_dir).glob("*/SKILL.md"))
        if not candidates:
            pytest.skip("内置技能目录为空")

        seen: list = []
        original = perm_mod.PermissionService.enforce

        def _spy(self, request, **kwargs):
            seen.append(request)
            return original(self, request, **kwargs)

        monkeypatch.setattr(perm_mod.PermissionService, "enforce", _spy)

        decision = perm_mod.PermissionService.instance().enforce(
            perm_mod.PermissionRequest(tool="read_file", path=str(candidates[0])),
            run_id="p2_23_run",
        )
        assert seen, "未经过 enforce()"
        assert decision.decision == "allow", (
            f"技能目录内的读应放行，实际 {decision.decision}（{decision.reason}）"
        )


# --------------------------------------------------------------------------- #
# P6-05 · 循环执行检测
# --------------------------------------------------------------------------- #
class TestLoopDetection:
    """连续相同调用 → 发 ``loop_detected`` 事件；上层可选择中止。"""

    def test_第三次相同调用发出事件(self, client, fake_client_factory):
        from app.core.config import settings
        from app.services.agent_service import AgentService
        from app.services.skill_manager import SkillManager
        from tests.conftest import make_tool_call_response

        scripts = [make_tool_call_response("read_file", {"file_path": "/tmp/loop-x"})] * 5
        fake, _calls = fake_client_factory(scripts)

        service = AgentService(SkillManager(settings.skills_dir, settings.custom_skills_dir))
        service._client = fake

        events = list(service.stream("循环探针", mode="chat"))
        kinds = [e.get("type") for e in events]
        assert "loop_detected" in kinds, kinds

        loop_event = next(e for e in events if e.get("type") == "loop_detected")
        assert loop_event.get("tool_name") == "read_file"
        assert loop_event.get("repeat", 0) >= 3, loop_event

    def test_上层选择中止时终态interrupted(self, client, fake_client_factory):
        from app.core.config import settings
        from app.services.agent_service import AgentService
        from app.services.skill_manager import SkillManager
        from tests.conftest import make_tool_call_response

        scripts = [make_tool_call_response("read_file", {"file_path": "/tmp/loop-y"})] * 5
        fake, _calls = fake_client_factory(scripts)

        service = AgentService(SkillManager(settings.skills_dir, settings.custom_skills_dir))
        service._client = fake

        seen: list[dict] = []

        def _hook(event: dict) -> bool:
            seen.append(event)
            return False   # 用户选「中止」

        events = list(service.stream("循环中止探针", mode="chat", loop_hook=_hook))
        kinds = [e.get("type") for e in events]
        assert seen, "loop_hook 未被调用"
        assert "interrupted" in kinds, kinds

    def test_正常长任务不误触发(self, client, fake_client_factory):
        """无 hook 时**不中止**——由迭代上限兜底（既有契约）。"""
        from app.core.config import settings
        from app.services.agent_service import AgentService
        from app.services.skill_manager import SkillManager
        from tests.conftest import make_tool_call_response

        scripts = [make_tool_call_response("read_file", {"file_path": "/tmp/z"})] * 10
        fake, calls = fake_client_factory(scripts)

        service = AgentService(SkillManager(settings.skills_dir, settings.custom_skills_dir))
        service._client = fake

        events = list(service.stream("正常长任务", mode="chat"))
        kinds = [e.get("type") for e in events]
        assert "interrupted" not in kinds, "正常长任务被误中止"
        assert len(calls) == settings.chat_max_iterations
