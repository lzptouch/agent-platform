"""S2 权限引擎与执行边界的契约测试。

按 doc/roadmap/03-阶段S2 的 §5.1 组织：归一化 / 判定语义 / 审批流 /
策略执行 / 审计 / 迁移 / 沙箱诚实化 / 单例与缓存。
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from app.core.workspace import get_workspace_dir, reset_workspace_dir, set_workspace_dir
from app.db.base import db_session
from app.db.models import PermissionDecisionRow, PermissionRuleRow
from app.services.security import audit, policy, sandbox
from app.services.security.permissions import (
    ALLOW,
    ASK,
    DENY,
    PermissionRequest,
    PermissionService,
    Rule,
    decide,
)


@pytest.fixture(autouse=True)
def _workspace(tmp_path):
    set_workspace_dir(tmp_path)
    yield tmp_path
    reset_workspace_dir()


@pytest.fixture()
def engine():
    """权限引擎单例，并把审批通道标记为活跃（模拟有前端在轮询待审批列表）。"""
    PermissionService.reset_for_test()
    svc = PermissionService.instance()
    svc.approval_timeout = 2.0
    svc.note_channel_poll()  # 审批通道活跃
    yield svc
    PermissionService.reset_for_test()


def rule(scope, pattern, decision, **kw) -> Rule:
    return Rule(None, scope, pattern, decision, **kw)


# --------------------------------------------------------------------------- #
# WP-2.2 归一化
# --------------------------------------------------------------------------- #
class TestNormalize:
    def test_路径_点穿越归一(self):
        p = policy.normalize_path("a/b/../../c/x.txt", cwd=Path("/tmp/root"))
        assert ".." not in p
        assert p.endswith(os.path.normpath("c/x.txt"))

    def test_路径_波浪线展开(self):
        p = policy.normalize_path("~/x.txt")
        assert not p.startswith("~")
        assert os.path.isabs(p)

    def test_命令_串联拆分(self):
        assert policy.split_command_segments("ls && rm -rf /tmp; echo ok") == ["ls", "rm -rf /tmp", "echo ok"]

    def test_命令_引号与重定向剥离(self):
        norm = policy.normalize_command('echo "hello world" > out.txt 2>&1')
        assert norm["first"] == "echo"
        assert "out.txt" not in norm["tokens"]

    def test_网络_本地判定(self):
        assert policy.normalize_network("http://127.0.0.1:8000/api")["is_local"] is True
        assert policy.normalize_network("https://api.example.com")["is_local"] is False

    def test_python危险调用扫描(self):
        assert policy.python_has_dangerous_calls("import os; os.remove('x')") == ["os.remove"]
        assert policy.python_has_dangerous_calls("print('hello')") == []


# --------------------------------------------------------------------------- #
# WP-2.2 判定语义（纯函数）
# --------------------------------------------------------------------------- #
class TestDecide:
    def test_最长前缀命中(self):
        rules = [rule("file", "~/data", ASK), rule("file", "~/data/secret/**", DENY, priority=1)]
        d = decide(PermissionRequest(tool="read_file", path="~/data/secret/key.pem"), rules)
        assert d.decision == DENY

    def test_同优先级_deny优先(self):
        rules = [rule("file", "~/a/**", ALLOW), rule("file", "~/a/**", DENY)]
        d = decide(PermissionRequest(tool="read_file", path="~/a/x"), rules)
        assert d.decision == DENY

    def test_优先级_小者先(self):
        rules = [rule("file", "~/a/**", ALLOW, priority=100), rule("file", "~/a/**", DENY, priority=1)]
        d = decide(PermissionRequest(tool="read_file", path="~/a/x"), rules)
        assert d.decision == DENY

    def test_四类scope分流(self):
        rules = [rule("file", "~/secret/**", DENY, priority=1)]
        # 同名 pattern 但 scope=tool 的规则不应影响 file 判定
        rules.append(rule("tool", "read_file", DENY))
        d = decide(PermissionRequest(tool="read_file", path="~/secret/x"), rules)
        assert d.decision == DENY
        assert d.scope == "file"

    def test_信任分层_L0只读放行(self):
        d = decide(PermissionRequest(tool="read_file"), [])
        assert d.decision == ALLOW

    def test_信任分层_L1工作区放行(self, tmp_path):
        d = decide(PermissionRequest(tool="write_file", path=str(tmp_path / "note.txt")), [])
        assert d.decision == ALLOW
        assert "工作区" in d.reason

    def test_信任分层_L2越界询问(self, tmp_path):
        d = decide(PermissionRequest(tool="write_file", path=str(tmp_path.parent / "outside.txt")), [])
        assert d.decision == ASK

    def test_信任分层_L4禁止路径直接deny(self):
        rules = [rule("file", "~/.ssh/**", DENY, risk="critical", priority=1)]
        d = decide(PermissionRequest(tool="write_file", path="~/.ssh/id_rsa"), rules)
        assert d.decision == DENY

    def test_危险动作优先于工作区放行(self, tmp_path):
        # 高危动作必须先于「工作区内路径放行」判定
        d = decide(PermissionRequest(tool="execute_bash", action="batch_delete",
                                     path=str(tmp_path / "x")), [])
        assert d.decision == DENY

    def test_串联命令取最严(self):
        rules = [rule("command", "rm -rf /", DENY, priority=1)]
        d = decide(PermissionRequest(tool="execute_bash", command="ls && rm -rf /"), rules)
        assert d.decision == DENY

    def test_未知命令默认询问(self):
        d = decide(PermissionRequest(tool="execute_bash", command="my-custom-tool --flag"), [])
        assert d.decision == ASK


# --------------------------------------------------------------------------- #
# WP-2.3 审批流（阻塞 + 超时 + 四种决策语义）
# --------------------------------------------------------------------------- #
class TestApprovalFlow:
    def _ask_request(self, tmp_path) -> PermissionRequest:
        return PermissionRequest(tool="write_file", path=str(tmp_path.parent / "outside.txt"))

    def test_ask_阻塞等待并可被决策唤醒(self, engine, tmp_path):
        req = self._ask_request(tmp_path)
        result: list = []

        def run():
            result.append(engine.enforce(req, run_id="r1"))

        t = threading.Thread(target=run)
        t.start()
        time.sleep(0.3)
        assert t.is_alive(), "ask 应阻塞等待"
        pending = engine.pending_decisions()
        assert len(pending) == 1
        engine.resolve_decision(pending[0]["id"], "allow_once")
        t.join(timeout=3)
        assert result[0].decision == ALLOW

    def test_超时按deny(self, engine, tmp_path):
        req = self._ask_request(tmp_path)
        d = engine.enforce(req, run_id="r1", timeout=0.5)
        assert d.decision == DENY
        assert "超时" in d.reason
        with db_session() as db:
            row = db.scalars(
                __import__("sqlalchemy").select(PermissionDecisionRow).where(
                    PermissionDecisionRow.run_id == "r1"
                )
            ).first()
            assert row is not None and row.decided_by == "timeout"

    def test_allow_once_放行一次(self, engine, tmp_path):
        req = self._ask_request(tmp_path)
        result: list = []
        t = threading.Thread(target=lambda: result.append(engine.enforce(req)))
        t.start()
        time.sleep(0.3)
        pending = engine.pending_decisions()
        engine.resolve_decision(pending[0]["id"], "allow_once")
        t.join(timeout=3)
        assert result[0].decision == ALLOW
        # allow_once 不落库规则
        with db_session() as db:
            assert not db.scalars(
                __import__("sqlalchemy").select(PermissionRuleRow).where(
                    PermissionRuleRow.origin == "user"
                )
            ).all()

    def test_allow_workspace_落库(self, engine, tmp_path):
        from app.services.permissions import PermissionService as Compat

        req = self._ask_request(tmp_path)
        result: list = []
        t = threading.Thread(target=lambda: result.append(engine.enforce(req)))
        t.start()
        time.sleep(0.3)
        pending = engine.pending_decisions()
        engine.resolve_decision(pending[0]["id"], "allow_workspace")
        t.join(timeout=3)
        assert result[0].decision == ALLOW

    def test_无审批通道时立即拒绝(self, tmp_path):
        # 不模拟通道轮询（桌面模式关 + 无轮询）→ ask 立即 deny
        PermissionService.reset_for_test()
        svc = PermissionService.instance()
        svc.approval_timeout = 60.0  # 若错误地阻塞，这里会慢 60s
        start = time.monotonic()
        d = svc.enforce(self._ask_request(tmp_path))
        elapsed = time.monotonic() - start
        assert d.decision == DENY
        assert elapsed < 2.0, f"无通道时应立即拒绝，实际等待 {elapsed:.1f}s"

    def test_通道轮询后阻塞等待(self, engine, tmp_path, monkeypatch):
        # 模拟 Web 形态有人轮询待审批列表
        from app.core.config import settings

        monkeypatch.setattr(type(settings), "desktop_mode", property(lambda self: False))
        engine.pending_decisions()  # 触发 note_channel_poll
        req = self._ask_request(tmp_path)
        result: list = []
        t = threading.Thread(target=lambda: result.append(engine.enforce(req)))
        t.start()
        time.sleep(0.3)
        assert t.is_alive(), "通道活跃时应阻塞等待"
        pending = engine.pending_decisions()
        engine.resolve_decision(pending[0]["id"], "deny")
        t.join(timeout=3)
        assert result[0].decision == DENY


# --------------------------------------------------------------------------- #
# WP-2.7 审计
# --------------------------------------------------------------------------- #
class TestAudit:
    def test_审计按run还原(self, tmp_path):
        audit.record(run_id="run-a", tool="write_file", decision="allow", reason="ok", target="x")
        audit.record(run_id="run-a", tool="execute_bash", decision="deny", reason="no", target="rm")
        audit.record(run_id="run-b", tool="read_file", decision="allow", reason="ok", target="y")
        rows = audit.read_for_run("run-a")
        assert len(rows) == 2
        assert rows[0]["tool"] == "write_file"
        assert rows[1]["decision"] == "deny"

    def test_审计写失败不阻断(self, monkeypatch):
        monkeypatch.setattr(audit, "audit_path", lambda workspace=None: Path("/proc/readonly/x/audit.jsonl"))
        audit.record(run_id="r", tool="t", decision="deny", reason="x", target="t")  # 不抛异常


# --------------------------------------------------------------------------- #
# WP-2.6 沙箱诚实化
# --------------------------------------------------------------------------- #
class TestSandboxCapability:
    def test_返回真实能力而非硬编码(self):
        cap = sandbox.probe()
        assert cap.level == "policy_only"
        assert cap.available is True
        assert "策略层" in cap.message
        assert cap.enforced_paths and cap.enforced_commands


# --------------------------------------------------------------------------- #
# WP-2.8 单例与缓存
# --------------------------------------------------------------------------- #
class TestSingletonAndCache:
    def test_单例(self):
        PermissionService.reset_for_test()
        a = PermissionService.instance()
        b = PermissionService.instance()
        assert a is b

    def test_规则缓存与失效(self, engine):
        first = engine.load_rules()
        # 新写一条规则 → 缓存失效后再读应包含它
        from app.services.permissions import PermissionService as Compat

        Compat().set_rule("tool", "some_new_tool", "allow")
        second = engine.load_rules(force=False)
        assert any(r.pattern == "some_new_tool" for r in second), "缓存未失效"

    def test_过期规则视为不存在(self, engine):
        from app.db.models import utc_now

        with db_session() as db:
            db.add(PermissionRuleRow(
                scope="tool", pattern="expired_tool", decision="deny",
                expires_at="2000-01-01T00:00:00+00:00", updated_at=utc_now(),
            ))
        engine.invalidate_cache()
        rules = engine.load_rules()
        assert not any(r.pattern == "expired_tool" for r in rules)


# --------------------------------------------------------------------------- #
# WP-2.1 迁移与内置规则
# --------------------------------------------------------------------------- #
class TestMigrationAndBuiltins:
    def test_决策日志表存在(self):
        from sqlalchemy import inspect

        from app.db.base import get_engine

        tables = inspect(get_engine()).get_table_names()
        assert "permission_decisions" in tables

    def test_规则表新列存在(self):
        from sqlalchemy import inspect

        from app.db.base import get_engine

        cols = {c["name"] for c in inspect(get_engine()).get_columns("permission_rules")}
        assert {"pattern", "risk", "workspace_id", "priority", "origin", "expires_at"} <= cols
        assert "target" not in cols
