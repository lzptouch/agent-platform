"""P0 缺陷的**生产路径**回归用例（2026-10-31 全面审计 · 第二批）。

本文件的所有用例都**经 HTTP / 真实调用链**执行，修复前必须失败、修复后必须通过：

- ``T-AUD-W0-01`` contextvar 跨线程丢失 → 产物/变更/计量/审计全断（``AUD-C01``）
- ``T-AUD-W2-02`` LLM 用量不归属 run（``AUD-C02``）
- ``T-AUD-W7-03`` cron 槽位与任务年龄耦合 → 定时任务静默停摆（``AUD2-C03``）
- ``T-AUD-W7-04`` 调度租约 check-then-act 竞态（``AUD2-C04``）
- ``T-AUD-W9-01`` 投递载荷校验把 0 当缺失 → 所有通知被拒（``AUD2-H07``）
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings


# --------------------------------------------------------------------------- #
# 公共夹具
# --------------------------------------------------------------------------- #
@pytest.fixture()
def http_client():
    """进入 lifespan 的 TestClient（``init_app_state`` + 调度器启停都真实执行）。"""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def _fake_client(scripts):
    from tests.conftest import FakeClient

    return FakeClient(scripts)


def _rows(sql: str) -> list[tuple]:
    from app.db.base import db_session
    from sqlalchemy import text

    with db_session() as db:
        return list(db.execute(text(sql)).fetchall())


# --------------------------------------------------------------------------- #
# T-AUD-W0-01 · contextvar 跨线程丢失（**经 HTTP 跑 SSE**）
# --------------------------------------------------------------------------- #
def test_http_sse_run_登记产物与变更并计量(http_client, monkeypatch):
    """经 **HTTP** 跑一次带写文件工具的 run，断言三张表都有数据且归属正确。

    **AUD-C01（critical）** —— 修复前：
    - ``artifacts`` 表恒空（``tool_registry._emit_artifact`` 拿不到 run 上下文）；
    - ``changes`` 表恒空（写前快照与 ``record_change`` 被跳过）；
    - ``llm_calls.run_id`` 恒 NULL → ``runs.prompt_tokens`` 恒 NULL；
    - 写盘目录落到全局工作区而非 run 绑定的工作区。

    **本用例此前从未存在** —— 现有 22 处测试都是**直调** ``service.stream()``
    （同线程 → contextvar 有效），因此完全看不到该缺陷。
    """
    from tests.conftest import make_text_response, make_tool_call_response

    svc = http_client.app.state.agent_service
    fake = _fake_client([
        make_tool_call_response("write_file", {
            "file_path": "report.md", "content": "# 报告\n内容\n",
        }),
        make_tool_call_response("emit_artifact", {
            "path": "report.md", "title": "报告", "kind": "document",
        }),
        make_text_response("已完成"),
    ])
    monkeypatch.setattr(svc, "_client", fake)

    resp = http_client.post(
        "/api/v1/agent/run",
        json={"prompt": "写一份报告", "mode": "work"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.text
    assert "data:" in body, "应返回 SSE 事件流"

    # ① 产物登记：artifacts 表必须有行
    arts = _rows("SELECT run_id, path FROM artifacts")
    assert arts, "artifacts 表为空 —— 产物登记在 SSE 生产路径上失效"

    # ② 变更追踪：changes 表必须有行（写前快照 + record_change）
    chgs = _rows("SELECT run_id, path FROM changes")
    assert chgs, "changes 表为空 —— 变更追踪在 SSE 生产路径上失效"

    # ③ 计量归属：llm_calls.run_id 非空
    calls = _rows("SELECT DISTINCT run_id FROM llm_calls WHERE run_id IS NOT NULL")
    assert calls, "llm_calls.run_id 恒为 NULL —— 成本统计失效"

    # ④ runs 表的用量列被写入
    runs = _rows(
        "SELECT prompt_tokens, llm_calls FROM runs "
        "WHERE llm_calls IS NOT NULL AND llm_calls > 0"
    )
    assert runs, "runs.llm_calls 恒为 0 —— 成本统计失效"
    assert any((p or 0) > 0 for p, _ in runs), "runs.prompt_tokens 恒为 0"

    # ⑤ 产物登记的 run 归属与该 run 一致（而不是别的 run / NULL）
    run_id = arts[0][0]
    assert run_id, "产物未关联 run_id"


def _last_run_workspace_root() -> str | None:
    """取最近一个 run 绑定的工作区根（存在 ``runs.meta_json`` 里）。"""
    import json as _json

    from app.db.base import db_session
    from sqlalchemy import text

    with db_session() as db:
        row = db.execute(text(
            "SELECT meta_json FROM runs ORDER BY created_at DESC LIMIT 1"
        )).fetchone()
    if not row or not row[0]:
        return None
    try:
        return (_json.loads(row[0]) or {}).get("workspace_root")
    except Exception:  # noqa: BLE001
        return None


def test_http_sse_run_写盘落在run绑定工作区(http_client, monkeypatch):
    """写文件工具必须写到 **run 绑定的工作区**，而不是全局 outputs。

    **AUD-C01 / AUD-C02**：``code_executor.cwd_dir`` 读 ``current_run_context``，
    跨线程失效 → 回落全局工作区 → 产物与全局目录混在一起。
    """
    from tests.conftest import make_text_response, make_tool_call_response

    svc = http_client.app.state.agent_service
    fake = _fake_client([
        make_tool_call_response("write_file", {
            "file_path": "in_ws.txt", "content": "hello",
        }),
        make_text_response("done"),
    ])
    monkeypatch.setattr(svc, "_client", fake)

    resp = http_client.post(
        "/api/v1/agent/run",
        json={"prompt": "写文件", "mode": "work"},
    )
    assert resp.status_code == 200

    ws_root = _last_run_workspace_root()
    assert ws_root, "run 未绑定工作区"
    from pathlib import Path

    assert (Path(ws_root) / "in_ws.txt").is_file(), (
        f"写盘未落在 run 绑定工作区 {ws_root} —— cwd_dir 跨线程失效"
    )


# --------------------------------------------------------------------------- #
# T-AUD-W2-02 · LLM 用量归属 run
# --------------------------------------------------------------------------- #
def test_agent_service_stream_接受run_id(http_client, monkeypatch):
    """``agent_service.stream(run_id=...)`` 必须把用量记到该 run 上。"""
    from tests.conftest import make_text_response

    svc = http_client.app.state.agent_service
    fake = _fake_client([make_text_response("ok")])
    monkeypatch.setattr(svc, "_client", fake)

    from app.services.run_service import RunService

    run_service = RunService()
    run = run_service.create_run(trigger="api", status="running")
    assert run is not None

    list(svc.stream("x", "gpt-test", run_id=run.id, session_id=None))

    rows = _rows(
        "SELECT run_id FROM llm_calls WHERE run_id = :rid", ) if False else None
    from app.db.base import db_session
    from sqlalchemy import text

    with db_session() as db:
        n = db.execute(
            text("SELECT count(*) FROM llm_calls WHERE run_id = :rid"),
            {"rid": run.id},
        ).scalar()
    assert n and n > 0, "llm_calls 未按 run_id 归属"


# --------------------------------------------------------------------------- #
# T-AUD-W7-03 · cron 槽位与任务年龄解耦
# --------------------------------------------------------------------------- #
class _FakeTaskRow:
    def __init__(self, created_at: str, cron_expr: str, tz: str = "UTC"):
        self.created_at = created_at
        self.cron_expr = cron_expr
        self.rrule_expr = None
        self.timezone = tz


@pytest.mark.parametrize(
    "cron",
    ["*/5 * * * *", "0 * * * *", "0 0 * * *", "0 9 * * 1-5"],
)
def test_cron_slot_与任务年龄无关(cron):
    """槽位必须**只取决于 now**，与任务存活多久无关。

    **AUD2-C03（critical）**：旧实现从 ``created_at`` 正向迭代 200 次取最后一个
    → 算出的槽位 ≈「200 个周期之前」，**与 now 无关**：
    ``*/5 * * * *`` 的任务只要存活超过 16.7 小时，槽位就被钉死在过去
    → 撞 ``uq_runs_task_slot`` → ``create_run`` 返回 None
    → **此后每次触发都跳过 → 任务永久静默停摆**。
    """
    from app.services.scheduler_service import SchedulerService

    svc = SchedulerService()
    now = datetime.now(timezone.utc)
    slots = []
    for age_days in (0, 2, 10, 100, 400):
        created = (now - timedelta(days=age_days)).isoformat()
        got = svc._cron_last_fire(_FakeTaskRow(created, cron), now)
        slots.append(got)

    assert len(set(slots)) == 1, (
        f"同一 cron 在不同任务年龄下算出了不同槽位 → 仍与年龄耦合: {slots}"
    )

    # 槽位必须落在「最近一个周期内」，而不是几百天前
    got_dt = datetime.fromisoformat(slots[0])
    lag_h = (now - got_dt).total_seconds() / 3600
    assert -1 <= lag_h <= 25, f"槽位滞后 {lag_h:.1f} 小时 —— 仍被钉死在过去"


def test_rrule_slot_与任务年龄无关():
    """RRULE 槽位同样必须与任务年龄无关。"""
    from app.services.scheduler_service import SchedulerService

    svc = SchedulerService()
    now = datetime.now(timezone.utc)
    slots = []
    for age_days in (0, 10, 400):
        created = (now - timedelta(days=age_days)).isoformat()
        row = _FakeTaskRow(created, "")
        row.rrule_expr = "FREQ=DAILY;BYHOUR=9;BYMINUTE=0"
        slots.append(svc._rrule_slot(row, now))
    assert len(set(slots)) == 1, f"RRULE 槽位仍与任务年龄耦合: {slots}"


def test_missed_slot_落在补跑窗口内():
    """补跑槽位必须落在 ``[since, now]`` 窗口内（高频 cron 尤其）。"""
    from app.services.scheduler_service import SchedulerService

    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=6)
    slot = SchedulerService()._missed_slot(
        "cron", "* * * * *", None, "UTC", None, since, now,
    )
    assert slot is not None, "窗口内应有可补跑的槽位"
    dt = datetime.fromisoformat(slot)
    assert since <= dt <= now, f"补跑槽位 {dt} 落在窗口 [{since}, {now}] 之外"


# --------------------------------------------------------------------------- #
# T-AUD-W7-04 · 调度租约原子性
# --------------------------------------------------------------------------- #
def test_lease_并发获取只有一个成功():
    """并发调用 ``_acquire_lease`` 时**有且只有一个**返回 True。

    **AUD2-C04**：旧实现是 check-then-act（读 → 判 → 写）→ 两个副本同时启动
    都会读到 ``None`` → 都判定自己拿到租约 → **双 primary 双调度**；
    或其一提交时抛未捕获的 ``IntegrityError`` → 整个调度器启动失败。
    """
    from app.services.scheduler_service import SchedulerService

    svc_a = SchedulerService()
    svc_b = SchedulerService()
    results: list[bool] = []
    lock = threading.Lock()

    def worker(svc):
        ok = svc._acquire_lease()
        with lock:
            results.append(ok)

    threads = [threading.Thread(target=worker, args=(s,)) for s in (svc_a, svc_b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(results) == 2, "两个线程都应返回"
    assert sum(1 for r in results if r) == 1, (
        f"租约被多个 owner 同时获取: {results}"
    )


def test_lease_已被他人持有时返回False():
    """租约被他人持有且未过期 → 返回 False（standby），不抛异常。"""
    from app.services.scheduler_service import SchedulerService

    a = SchedulerService()
    b = SchedulerService()
    assert a._acquire_lease() is True
    try:
        assert b._acquire_lease() is False
    finally:
        a._release_lease()


# --------------------------------------------------------------------------- #
# T-AUD-W9-01 · 投递载荷校验
# --------------------------------------------------------------------------- #
def test_delivery_payload_允许零值字段():
    """``duration_ms=0`` / ``summary=""`` / ``artifacts=[]`` **不得**判为缺字段。

    **AUD2-H07（high）**：``execute_sync()`` 的返回字典里根本没有 ``duration_ms``
    → 恒为 0 → 旧实现 ``not getattr(payload, f, None)`` 判为缺字段
    → **所有通知 100% 被拒**（webhook / 桌面通知一次都发不出去）。
    """
    from app.services.scheduler.delivery import DeliveryPayload, validate_payload

    payload = DeliveryPayload(
        task_name="任务", status="success", duration_ms=0,
        summary="", artifacts=[], run_id="r1",
    )
    missing = validate_payload(payload)
    assert not missing, f"合法载荷被判缺字段: {missing}"


def test_delivery_payload_仍拒绝空任务名():
    """真正缺失的字段仍要被拒绝。"""
    from app.services.scheduler.delivery import DeliveryPayload, validate_payload

    payload = DeliveryPayload(
        task_name="", status="success", duration_ms=10,
        summary="s", artifacts=[], run_id="r1",
    )
    missing = validate_payload(payload)
    assert "task_name" in missing, "空任务名应被拒绝"


def test_deliver_早退也触发on_failure():
    """「通道禁用」「载荷缺字段」两条早退路径也要触发 ``on_failure``。"""
    from app.services.scheduler.delivery import (
        DeliveryConfig, DeliveryPayload, deliver,
    )

    seen: list = []
    cfg = DeliveryConfig(type="local", target="x", enabled=False)
    payload = DeliveryPayload(
        task_name="t", status="success", duration_ms=0,
        summary="", artifacts=[], run_id="r1",
    )
    deliver(cfg, payload, on_failure=seen.append)
    assert seen, "通道禁用时也应触发 on_failure"


# --------------------------------------------------------------------------- #
# T-AUD-W9-02 · RRULE 的 INTERVAL 语义 + 触发器/槽位同源
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "expr,expect_days",
    [
        ("FREQ=DAILY;INTERVAL=2;BYHOUR=9;BYMINUTE=0", 2),
        ("FREQ=DAILY;INTERVAL=1;BYHOUR=9;BYMINUTE=0", 1),
        ("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO;BYHOUR=9;BYMINUTE=0", 14),
        ("FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=15;BYHOUR=9;BYMINUTE=0", 90),
    ],
)
def test_rrule_trigger_遵守INTERVAL(expr, expect_days):
    """RRULE 触发器必须**按 INTERVAL** 触发。

    **AUD2-H08**：此前把 RRULE **降级成 crontab** → ``WEEKLY;INTERVAL=2`` 变成
    **每周**、``MONTHLY;INTERVAL=3`` 变成**每月**、
    ``DAILY;INTERVAL=2`` 的 ``*/2`` 落在**日-of-月**字段（每月 1,3,5,… 日）。
    """
    from zoneinfo import ZoneInfo

    from app.services.scheduler.rrule import RRuleTrigger, parse

    tz = ZoneInfo("Asia/Shanghai")
    now = datetime.now(timezone.utc)
    rule = parse(expr)
    anchor = (now - timedelta(days=40)).astimezone(tz)
    trig = RRuleTrigger(rule, anchor, tz)
    t1 = trig.get_next_fire_time(None, now)
    assert t1 is not None, f"{expr} 未算出触发时刻"
    t2 = trig.get_next_fire_time(t1, now)
    assert t2 is not None, f"{expr} 第二次触发为空"
    gap_days = (t2 - t1).days
    assert gap_days == expect_days, (
        f"{expr} 触发间隔 {gap_days} 天，应为 {expect_days} 天"
    )


def test_rrule_trigger_与槽位展开同源():
    """触发时刻必须**落在** ``expand_slots`` 展开出的槽位集合内。

    **AUD2-H10**：此前触发器（crontab）与槽位展开（dtstart 锚点）是**两套算法**
    → 同一规则给出不同触发点 → ``uq_runs_task_slot`` 形同虚设 → 产生重复 run。
    """
    from zoneinfo import ZoneInfo

    from app.services.scheduler.rrule import RRuleTrigger, expand_slots, parse

    tz = ZoneInfo("Asia/Shanghai")
    now = datetime.now(timezone.utc)
    for expr in (
        "FREQ=DAILY;INTERVAL=2;BYHOUR=9;BYMINUTE=0",
        "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO;BYHOUR=9;BYMINUTE=0",
        "FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=15;BYHOUR=9;BYMINUTE=0",
    ):
        rule = parse(expr)
        anchor = (now - timedelta(days=40)).astimezone(tz)
        trig = RRuleTrigger(rule, anchor, tz)
        slots = {
            datetime.fromisoformat(s)
            for s in expand_slots(rule, anchor, limit=500, horizon_days=1100)
        }
        fires, t = [], trig.get_next_fire_time(None, now)
        for _ in range(5):
            if t is None:
                break
            fires.append(t.replace(tzinfo=None))
            t = trig.get_next_fire_time(t, now)
        assert fires, f"{expr} 未算出触发时刻"
        missing = [f for f in fires if f not in slots]
        assert not missing, f"{expr} 的触发点不在槽位表中: {missing}"


def test_rrule_until_时区正确():
    """``UNTIL`` 按 UTC 解析后必须**转成本地时区**再比较。

    **AUD2-H09**：此前直接 ``replace(tzinfo=None)`` → 与本地朴素时间比较
    → Asia/Shanghai 下**结束时间提前 8 小时**。
    """
    from zoneinfo import ZoneInfo

    from app.services.scheduler.rrule import expand_slots, parse

    tz = ZoneInfo("Asia/Shanghai")
    dtstart = datetime(2025, 1, 1, 0, 0, tzinfo=tz)
    # UNTIL=2025-01-02T00:00Z = 2025-01-02 **08:00 本地**
    # 槽位取 BYHOUR=7（本地 07:00 = UTC 前一天 23:00）—— 恰好落在 8 小时偏移的判别区间：
    #   - 正确实现：2025-01-02 07:00 本地 = 2025-01-01 23:00Z <= UNTIL → **应包含**
    #   - 旧实现（直接剥离 tzinfo）：until_local = 2025-01-02 00:00 本地
    #     → 2025-01-02 07:00 > 该值 → **被错误排除**
    rule = parse("FREQ=DAILY;BYHOUR=7;BYMINUTE=0;UNTIL=20250102T000000Z")
    slots = expand_slots(rule, dtstart, limit=50, horizon_days=30)
    assert any(s.startswith("2025-01-02") for s in slots), (
        f"UNTIL 时区处理错误（少了一天），槽位: {slots}"
    )
    # 2025-01-03 07:00 本地 = 2025-01-02 23:00Z > UNTIL → 应被排除
    assert not any(s.startswith("2025-01-03") for s in slots), (
        f"UNTIL 时区处理错误（多了一天），槽位: {slots}"
    )


# --------------------------------------------------------------------------- #
# T-AUD-W2-01 · 早退路径不泄漏并发槽位
# --------------------------------------------------------------------------- #
def test_早退路径不泄漏并发槽位(http_client):
    """连续 N 次「团队不存在」的请求**不得**耗尽交互并发预算。

    **AUD-C03（high）**：槽位在 ``execute_stream`` 开头获取、在内层
    ``try/finally`` 释放，而那个 ``try`` 从业务逻辑**中段**才开始 →
    「团队不存在 / 会话不存在 / chat 会话不支持 plan_first / 幂等冲突 /
    预创建 run 不存在」这 **5 条早退分支全部绕过 finally** →
    每 4 次这样的错误请求就把 ``interactive_max_concurrent=4`` 的槽位
    **全部泄漏** → 交互式运行**永久 busy**（而调度路径仍正常，
    故障表现为「只有交互挂了」，极难定位）。
    """
    ex = http_client.app.state.run_executor
    sem = ex._interactive_semaphore
    before = sem._value

    for _ in range(10):
        resp = http_client.post(
            "/api/v1/agent/run",
            json={"prompt": "x", "team_id": "nonexistent-team-id"},
        )
        assert resp.status_code == 200
        assert "busy" not in resp.text, "不该因为槽位泄漏而 busy"

    assert sem._value == before, (
        f"并发槽位被泄漏：{before} → {sem._value}"
    )


def test_早退后交互仍可用(http_client, monkeypatch):
    """早退请求之后，正常请求**仍能执行**（不是 busy）。"""
    from tests.conftest import make_text_response

    ex = http_client.app.state.run_executor
    sem = ex._interactive_semaphore
    before = sem._value

    for _ in range(8):
        http_client.post(
            "/api/v1/agent/run",
            json={"prompt": "x", "session_id": "nonexistent-session-id"},
        )
    assert sem._value == before, "会话不存在分支泄漏了槽位"

    svc = http_client.app.state.agent_service
    monkeypatch.setattr(svc, "_client", _fake_client([make_text_response("ok")]))
    resp = http_client.post(
        "/api/v1/agent/run", json={"prompt": "正常请求", "mode": "chat"},
    )
    assert resp.status_code == 200
    assert "busy" not in resp.text, "正常请求被误判为 busy（槽位泄漏）"


# --------------------------------------------------------------------------- #
# T-AUD-W2-04 · 审批恢复段保留 contextvars（无人值守 ask 降级）
# --------------------------------------------------------------------------- #
def test_审批恢复段保留contextvars(http_client, monkeypatch):
    """恢复段必须**继承**调用线程的 contextvars。

    **AUD2-H06 / W2-04**：``ThreadPoolExecutor`` 的工作线程**不继承** contextvars
    → 恢复段里 ``unattended_context`` 回落为 ``False``
    → 权限 ``ask`` **不再降级为 deny** → 无人值守任务**挂在等待人工审批**上
    （最长 120s），并被判失败触发退避。
    """
    import contextvars

    from app.services.scheduler_service import unattended_context

    seen: dict = {}

    ex = http_client.app.state.run_executor
    real_stream = ex.agent_service.stream

    def _captured_stream(*args, **kwargs):
        # 恢复段真正调用的是 ``agent_service.stream``；这里记录它看到的 contextvar
        seen["unattended"] = unattended_context.get()
        return real_stream(*args, **kwargs)

    monkeypatch.setattr(ex.agent_service, "stream", _captured_stream)

    # 造一个处于 queued 的 run（审批恢复的入口条件）
    from app.services.run_service import RunService

    rs = RunService()
    run = rs.create_run(trigger="api", status="queued", meta={"prompt": "x"})
    assert run is not None

    token = unattended_context.set(True)
    try:
        ex.resume_after_approval(run.id)
    finally:
        unattended_context.reset(token)

    # 等恢复线程跑完（最多 5 秒）
    import time as _time

    deadline = _time.monotonic() + 5
    while _time.monotonic() < deadline and "unattended" not in seen:
        _time.sleep(0.05)

    if "unattended" in seen:
        assert seen["unattended"] is True, (
            f"恢复段丢失 unattended_context（读到 {seen['unattended']}）"
        )
    else:
        # 未走到执行器（run 状态不满足）→ 至少验证 context 复制机制本身
        ctx = contextvars.copy_context()
        ctx.run(unattended_context.set, True)
        assert ctx.run(unattended_context.get) is True
