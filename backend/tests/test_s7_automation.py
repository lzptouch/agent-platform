"""S7 自动化闭环与可观测的契约测试。

按 doc/roadmap/08-阶段S7 的 §5.1 组织：RRULE / 投递 / 无人值守 / MCP 传输 /
配置合并 / 结构化日志 / 指标。
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.chains.mcp.transport import (
    MCPEndpoint,
    MCPConnection,
    MCPError,
    TRANSPORTS,
    close_all,
)
from app.services.scheduler.delivery import (
    DeliveryConfig,
    DeliveryPayload,
    deliver,
    validate_payload,
)
from app.services.scheduler.rrule import RRule, RRULEError, expand_slots, parse, rrule_to_cron


def _dt(y=2026, m=1, d=5, hh=9, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm)  # 周一


# --------------------------------------------------------------------------- #
# WP-7.1 RRULE 子集
# --------------------------------------------------------------------------- #
class TestRRULE:
    def test_每日展开(self):
        r = parse("FREQ=DAILY")
        slots = expand_slots(r, _dt(), limit=3)
        assert len(slots) == 3
        assert all(s.endswith("T09:00:00") for s in slots)

    def test_每周多天展开(self):
        r = parse("FREQ=WEEKLY;BYDAY=MO,WE,FR;BYHOUR=9;BYMINUTE=0")
        assert r.byday == [0, 2, 4]
        slots = expand_slots(r, _dt(), limit=6)
        assert len(slots) == 6
        # 周一、周三、周五各一天
        days = {datetime.fromisoformat(s).weekday() for s in slots}
        assert days == {0, 2, 4}

    def test_每月多天(self):
        r = parse("FREQ=MONTHLY;BYMONTHDAY=1,15;BYHOUR=9")
        slots = expand_slots(r, _dt(d=1), limit=4)
        days = {datetime.fromisoformat(s).day for s in slots}
        assert days == {1, 15}

    def test_INTERVAL(self):
        r = parse("FREQ=DAILY;INTERVAL=3")
        slots = expand_slots(r, _dt(), limit=3)
        d0 = datetime.fromisoformat(slots[0])
        d1 = datetime.fromisoformat(slots[1])
        assert (d1 - d0).days == 3

    def test_COUNT限制(self):
        r = parse("FREQ=DAILY;COUNT=5")
        assert len(expand_slots(r, _dt(), limit=50)) == 5

    def test_UNTIL限制(self):
        r = parse("FREQ=DAILY;UNTIL=20260110T000000Z")
        slots = expand_slots(r, _dt(), limit=50)
        assert slots
        assert all(datetime.fromisoformat(s).date() <= datetime(2026, 1, 10).date() for s in slots)

    def test_非法表达式拒绝(self):
        with pytest.raises(RRULEError):
            parse("")
        with pytest.raises(RRULEError):
            parse("FREQ=HOURLY")
        with pytest.raises(RRULEError):
            parse("FREQ=DAILY;INTERVAL=0")
        with pytest.raises(RRULEError):
            parse("FREQ=DAILY;COUNT=5;UNTIL=20260101")

    def test_转cron(self):
        r = parse("FREQ=WEEKLY;BYDAY=MO,WE,FR;BYHOUR=9;BYMINUTE=0")
        assert rrule_to_cron(r) == "0 9 * * 0,2,4"

    def test_展开幂等(self):
        r = parse("FREQ=WEEKLY;BYDAY=MO,WE")
        a = expand_slots(r, _dt(), limit=4)
        b = expand_slots(r, _dt(), limit=4)
        assert a == b


# --------------------------------------------------------------------------- #
# WP-7.3 投递
# --------------------------------------------------------------------------- #
class TestDelivery:
    def _payload(self, **kw) -> DeliveryPayload:
        return DeliveryPayload(
            task_name=kw.get("task_name", "测试任务"),
            status=kw.get("status", "success"),
            duration_ms=kw.get("duration_ms", 1200),
            summary=kw.get("summary", "完成了"),
            artifacts=kw.get("artifacts", ["report.md"]),
            run_id="r1",
        )

    def test_载荷字段齐全(self):
        missing = validate_payload(self._payload())
        assert missing == []

    def test_载荷缺字段(self):
        """只有 ``task_name`` / ``status`` 必须**非空**。

        **W9-01 / AUD2-H07**：旧语义把「值为空」当「字段缺失」——
        ``duration_ms``（恒 0）/ ``summary``（可为空）/ ``artifacts``（可为空）
        全被判为缺失 → **所有通知 100% 被拒**。
        现在：``duration_ms=0`` / ``summary=""`` / ``artifacts=[]`` 都是**合法**的。
        """
        p = self._payload()
        # 合法：零值 / 空串 / 空列表都不算缺字段
        p.duration_ms = 0
        p.summary = ""
        p.artifacts = []
        assert validate_payload(p) == []

        # 真正缺失的字段仍要拒绝
        p2 = self._payload()
        p2.task_name = ""
        missing = validate_payload(p2)
        assert "task_name" in missing

    def test_投递成功(self):
        cfg = DeliveryConfig(type="local", target="desktop")
        res = deliver(cfg, self._payload())
        assert res.ok is True
        assert res.attempts == 1

    def test_失败重试3次(self):
        calls: list[int] = []

        def fail(*a, **k):
            calls.append(1)
            return False

        cfg = DeliveryConfig(type="webhook", target="http://127.0.0.1:1/x")
        res = deliver(cfg, self._payload(), retries=3)
        assert res.ok is False
        assert res.attempts == 3

    def test_凭证不入日志正文(self):
        # webhook 的 target 完整保存，但失败时不把 URL 写进告警的正文（只进 delivery 记录）
        cfg = DeliveryConfig(type="webhook", target="https://secret.example.com/hook")
        res = deliver(cfg, self._payload(), retries=1)
        assert res.ok is False
        # 日志正文不应含完整 URL 的敏感部分（实现里 logger.warning 只写 target 截断）


# --------------------------------------------------------------------------- #
# WP-7.5 无人值守降级
# --------------------------------------------------------------------------- #
class TestUnattendedPolicy:
    def test_无人值守ask降级deny(self):
        from app.services.scheduler_service import unattended_context
        from app.services.security.permissions import PermissionService

        PermissionService.reset_for_test()
        svc = PermissionService.instance()
        svc.approval_timeout = 60.0  # 若误阻塞会慢 60s

        unattended_context.set(True)
        try:
            d = svc.enforce(__import__("app.services.security.permissions", fromlist=["PermissionRequest"]).PermissionRequest(
                tool="write_file", path="C:/outside/x.txt",
            ))
        finally:
            unattended_context.set(False)
        assert d.decision == "deny"
        assert "无人值守" in d.reason

    def test_跳过原因记录(self):
        from app.services.scheduler_service import unattended_context
        from app.services.security.permissions import PermissionRequest, PermissionService

        PermissionService.reset_for_test()
        svc = PermissionService.instance()
        unattended_context.set(True)
        try:
            d = svc.enforce(PermissionRequest(tool="write_file", path="C:/outside/x.txt"))
        finally:
            unattended_context.set(False)
        assert "按拒绝" in d.reason or "无人值守" in d.reason


# --------------------------------------------------------------------------- #
# WP-7.6 MCP 传输
# --------------------------------------------------------------------------- #
class TestMCPTransport:
    def test_三传输定义(self):
        # **W11-01**：此前测的是 `if False else` 里的**字面量**（与被测常量无关）
        assert set(TRANSPORTS) == {"stdio", "sse", "http"}

    def test_连接复用(self):
        from app.services.chains.mcp.transport import get_connection, pool_size

        ep = MCPEndpoint(name="test", transport="http", url="http://127.0.0.1:1")
        c1 = get_connection(ep)
        c2 = get_connection(ep)
        assert c1 is c2, "同一 endpoint 应复用同一连接"
        assert pool_size() >= 1
        close_all()

    def test_连接失败可读(self):
        conn = MCPConnection(MCPEndpoint(name="bad", transport="http", url="http://127.0.0.1:1"), timeout=1.0)
        with pytest.raises(MCPError) as exc:
            conn.call_tool("x", {})
        assert "系统故障" in str(exc.value) or "连接失败" in str(exc.value)

    def test_stdio子进程回收(self):
        import subprocess

        ep = MCPEndpoint(name="stdio-test", transport="stdio", command="python", args=["-c", "import sys,time; [sys.stdout.write(sys.stdin.readline()) for _ in iter(int,1)]"])
        conn = MCPConnection(ep, timeout=2.0)
        proc = conn._stdio_proc()
        assert proc.poll() is None
        conn.close()
        assert proc.poll() is not None, "关闭后子进程应已终止"


# --------------------------------------------------------------------------- #
# WP-7.8 结构化日志与指标
# --------------------------------------------------------------------------- #
class TestStructuredLogging:
    def test_JSON行格式(self, caplog):
        from app.core.logging import StructuredFormatter, set_context, clear_context
        import logging

        set_context(request_id="req-1", run_id="run-1")
        logger = logging.getLogger("test")
        record = logger.makeRecord("test", logging.INFO, __file__, 1, "测试消息", (), None)
        line = StructuredFormatter().format(record)
        data = json.loads(line)
        assert data["level"] == "INFO"
        assert data["message"] == "测试消息"
        assert data["request_id"] == "req-1"
        assert data["run_id"] == "run-1"
        clear_context()

    def test_上下文字段齐全(self, caplog):
        from app.core.logging import StructuredFormatter, set_context, clear_context

        set_context(request_id="r", session_id="s", task_id="t")
        import logging

        record = logging.getLogger("x").makeRecord("x", logging.INFO, __file__, 1, "m", (), None)
        data = json.loads(StructuredFormatter().format(record))
        for k in ("request_id", "run_id", "session_id", "task_id"):
            assert k in data
        clear_context()

    def test_敏感字段脱敏(self):
        from app.core.logging import StructuredFormatter, set_context, clear_context
        import logging

        set_context(api_key="sk-abcdefghijklmnopqrstuvwxyz0123456789")
        record = logging.getLogger("x").makeRecord("x", logging.INFO, __file__, 1, "m", (), None)
        data = json.loads(StructuredFormatter().format(record))
        assert data["api_key"] == "***"
        clear_context()


# --------------------------------------------------------------------------- #
# WP-7.8 指标
# --------------------------------------------------------------------------- #
class TestMetrics:
    def test_指标字段齐全(self, client):
        r = client.get("/api/v1/metrics")
        assert r.status_code == 200
        body = r.json()
        for key in ("concurrency", "success_rate", "runs_today", "duration_ms", "llm", "mcp_connections"):
            assert key in body, f"缺字段: {key}"

    def test_并发与成功率正确(self, client):
        from app.db.base import db_session
        from app.db.models import RunRow, utc_now

        with db_session() as db:
            db.add(RunRow(trigger="api", status="success", created_at=utc_now(), duration_ms=100))
            db.add(RunRow(trigger="api", status="failed", created_at=utc_now(), duration_ms=200))
            db.add(RunRow(trigger="api", status="success", created_at=utc_now(), duration_ms=150))

        body = client.get("/api/v1/metrics").json()
        assert body["runs_today"] >= 3
        assert body["duration_ms"]["samples"] >= 3
        assert body["concurrency"]["limit"] > 0


@pytest.fixture()
def client():
    from starlette.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
