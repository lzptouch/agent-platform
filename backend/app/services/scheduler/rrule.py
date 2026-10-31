"""RRULE 子集解析与槽位展开（S7 / WP-7.1）。

支持一个**可解析、可校验、可展开**的子集：

    FREQ = DAILY | WEEKLY | MONTHLY
    [INTERVAL=n]
    [BYDAY=MO,TU,WE,TH,FR,SA,SU]      # WEEKLY
    [BYMONTHDAY=1,15]                  # MONTHLY
    [BYHOUR=..] / [BYMINUTE=..]        # 未给时用 dtstart 的时分
    [COUNT=n] | [UNTIL=YYYYmmdd]      # 互斥

**非法表达式立即拒绝**（``RRULEError``）。槽位以本地时区生成（ISO 字符串），
与既有 ``_compute_slot`` 的确定性语义对齐（重启/补跑一致）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from apscheduler.triggers.base import BaseTrigger

#: RRULE 子集里允许出现的键
ALLOWED_KEYS = ("FREQ", "INTERVAL", "BYDAY", "BYMONTHDAY", "BYHOUR", "BYMINUTE", "COUNT", "UNTIL")
FREQS = ("DAILY", "WEEKLY", "MONTHLY")
#: 星期名 → Python weekday（周一 = 0）
BYDAY = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


class RRULEError(ValueError):
    """RRULE 表达式不合法。"""


@dataclass
class RRule:
    """一份解析后的 RRULE。"""

    freq: str
    interval: int = 1
    byday: list[int] = field(default_factory=list)
    bymonthday: list[int] = field(default_factory=list)
    byhour: int | None = None
    byminute: int | None = None
    count: int | None = None
    until: datetime | None = None

    def as_dict(self) -> dict:
        return {
            "freq": self.freq,
            "interval": self.interval,
            "byday": list(self.byday),
            "bymonthday": list(self.bymonthday),
            "byhour": self.byhour,
            "byminute": self.byminute,
            "count": self.count,
            "until": self.until.isoformat() if self.until else None,
        }


def _parse_kv(part: str) -> tuple[str, str]:
    if "=" not in part:
        raise RRULEError(f"缺少键值（KEY=VALUE）: {part!r}")
    key, _, value = part.partition("=")
    return key.strip().upper(), value.strip()


def parse(rrule: str) -> RRule:
    """解析 RRULE 子集文本，非法抛 ``RRULEError``。"""
    text = (rrule or "").strip()
    if not text:
        raise RRULEError("RRULE 为空")
    if text.upper().startswith("RRULE:"):
        text = text[6:]

    kv: dict[str, str] = {}
    for part in re.split(r"[;\s]+", text):
        if not part:
            continue
        key, value = _parse_kv(part)
        if key not in ALLOWED_KEYS:
            raise RRULEError(f"未知键: {key}")
        if key in kv:
            raise RRULEError(f"键重复: {key}")
        kv[key] = value

    freq = kv.get("FREQ", "").upper()
    if freq not in FREQS:
        raise RRULEError(f"FREQ 必须是 {'/'.join(FREQS)} 之一: {freq}")

    interval = 1
    if "INTERVAL" in kv:
        try:
            interval = int(kv["INTERVAL"])
        except ValueError as exc:
            raise RRULEError(f"INTERVAL 必须是整数: {kv['INTERVAL']!r}") from exc
        if interval < 1:
            raise RRULEError(f"INTERVAL 必须 ≥1: {interval}")

    byday: list[int] = []
    if "BYDAY" in kv:
        for token in kv["BYDAY"].split(","):
            day = BYDAY.get(token.strip().upper())
            if day is None:
                raise RRULEError(f"BYDAY 值非法: {token!r}")
            if day not in byday:
                byday.append(day)
        byday.sort()

    bymonthday: list[int] = []
    if "BYMONTHDAY" in kv:
        for token in kv["BYMONTHDAY"].split(","):
            try:
                day = int(token)
            except ValueError as exc:
                raise RRULEError(f"BYMONTHDAY 值非法: {token!r}") from exc
            if not (1 <= day <= 31):
                raise RRULEError(f"BYMONTHDAY 必须 1-31: {day}")
            if day not in bymonthday:
                bymonthday.append(day)
        bymonthday.sort()

    def _int(key: str, lo: int, hi: int) -> int | None:
        if key not in kv:
            return None
        try:
            value = int(kv[key])
        except ValueError as exc:
            raise RRULEError(f"{key} 必须是整数: {kv[key]!r}") from exc
        if not (lo <= value <= hi):
            raise RRULEError(f"{key} 必须在 {lo}~{hi}: {value}")
        return value

    byhour = _int("BYHOUR", 0, 23)
    byminute = _int("BYMINUTE", 0, 59)

    count = None
    if "COUNT" in kv:
        count = _int("COUNT", 1, 10_000)
    until = None
    if "UNTIL" in kv:
        until = _parse_until(kv["UNTIL"])
    if count is not None and until is not None:
        raise RRULEError("COUNT 与 UNTIL 互斥，只能用一个")

    # 语义约束：WEEKLY 不给 BYDAY 时按 dtstart 的星期；MONTHLY 不给 BYMONTHDAY 时按月日
    if freq == "MONTHLY" and byday:
        raise RRULEError("MONTHLY 不支持 BYDAY（用 BYMONTHDAY）")

    return RRule(
        freq=freq, interval=interval, byday=byday, bymonthday=bymonthday,
        byhour=byhour, byminute=byminute, count=count, until=until,
    )


def _parse_until(raw: str) -> datetime:
    raw = raw.strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y%m%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise RRULEError(f"UNTIL 格式非法（支持 YYYYmmdd / YYYYmmddTHHMMSSZ）: {raw!r}")


def expand_slots(
    rule: RRule,
    dtstart: datetime,
    *,
    limit: int = 60,
    horizon_days: int = 370,
) -> list[str]:
    """展开为槽位列表（本地时间 ISO 字符串，确定性）。

    数量受 ``rule.count`` 与 ``rule.until`` 约束，并加保险上限（``limit`` 与
    ``horizon_days``）。
    """
    out: list[str] = []
    # **W9-07 / AUD2-H09（UNTIL 时区偏移）**：``rule.until`` 按 UTC 解析，
    # 此前直接 ``replace(tzinfo=None)`` → 与**本地朴素时间**比较
    # → Asia/Shanghai 下 ``UNTIL=20250101T000000Z`` 被当作本地 00:00
    # → **结束时间提前 8 小时**。现在先转成**本地时区**再剥离 tzinfo。
    local_tz = dtstart.tzinfo
    # **W9-02**：游标归一到**日期零点**。
    # 此前游标保留 dtstart 的**时刻**（如 16:30），而槽位是「该日的 BYHOUR:BYMINUTE」
    # （如 09:00）→ ``slot < cursor`` 恒成立 → **每个周期的槽位都被跳过** →
    # DAILY / WEEKLY 规则**展开不出任何槽位**。
    start = dtstart.replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    hour = rule.byhour if rule.byhour is not None else dtstart.hour
    minute = rule.byminute if rule.byminute is not None else dtstart.minute

    cursor = start
    end = start + timedelta(days=horizon_days)
    if rule.until is not None:
        until_local = (
            rule.until.astimezone(local_tz).replace(tzinfo=None)
            if local_tz is not None
            else rule.until.replace(tzinfo=None)
        )
    else:
        until_local = None

    while cursor <= end and len(out) < limit and (rule.count is None or len(out) < rule.count):
        if until_local is not None and cursor > until_local:
            break
        for slot in _slots_in_period(rule, cursor, hour, minute):
            if slot < start:
                continue
            if until_local is not None and slot > until_local:
                break
            iso = slot.isoformat()
            if iso not in out:
                out.append(iso)
            if rule.count is not None and len(out) >= rule.count:
                break
        cursor = _advance(rule, cursor)
    return out


def _slots_in_period(
    rule: RRule, cursor: datetime, hour: int | None = None, minute: int | None = None
) -> list[datetime]:
    """按周期展开当期的槽位。

    **W9-02**：``hour`` / ``minute`` 必须**显式传入**（来自 dtstart 或规则）——
    此前从 ``cursor`` 取，而游标已归一到**日期零点** → 未指定 ``BYHOUR`` 的
    ``FREQ=DAILY`` 会把槽位时间变成 ``00:00``（而非 dtstart 的 09:00）。
    """
    if hour is None:
        hour = rule.byhour if rule.byhour is not None else cursor.hour
    if minute is None:
        minute = rule.byminute if rule.byminute is not None else cursor.minute
    out: list[datetime] = []
    if rule.freq == "DAILY":
        out.append(cursor.replace(hour=hour, minute=minute, second=0, microsecond=0))
    elif rule.freq == "WEEKLY":
        # 找当周内 byday 的各天
        monday = cursor - timedelta(days=cursor.weekday())
        days = rule.byday if rule.byday else [cursor.weekday()]
        for day in days:
            d = monday + timedelta(days=day)
            out.append(d.replace(hour=hour, minute=minute, second=0, microsecond=0))
    elif rule.freq == "MONTHLY":
        days = rule.bymonthday if rule.bymonthday else [cursor.day]
        for day in days:
            try:
                out.append(cursor.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0))
            except ValueError:
                continue  # 本月无此日（如 2 月 30 日）
    return sorted(out)


def _advance(rule: RRule, cursor: datetime) -> datetime:
    """推进到下一个周期起点。"""
    if rule.freq == "DAILY":
        return cursor + timedelta(days=rule.interval)
    if rule.freq == "WEEKLY":
        monday = cursor - timedelta(days=cursor.weekday())
        return monday + timedelta(weeks=rule.interval)
    # MONTHLY：按 interval 个月推进到每月 1 号
    month = cursor.month - 1 + rule.interval
    year = cursor.year + month // 12
    month = month % 12 + 1
    return cursor.replace(year=year, month=month, day=1)


def rrule_to_cron(rule: RRule) -> str:
    """把 RRULE 子集**降级**为 cron 表达式（**仅供展示/兼容**）。

    .. warning::
       **不要**用它构建真实的调度触发器 —— 它**无法表达 INTERVAL**：

       - ``FREQ=WEEKLY;INTERVAL=2``（每两周）→ 变成**每周**；
       - ``FREQ=MONTHLY;INTERVAL=3`` → 变成**每月**；
       - ``FREQ=DAILY;INTERVAL=2`` → ``*/2`` 落在 cron 的**日-of-月**字段
         → 实际是「每月 1,3,5,…,31 日」（每月重置，2 月只有 1,3,…,27 日），
         与「每 2 天」完全不同。

       **AUD2-H08 / W9-02 修复**：真实调度改用 :class:`RRuleTrigger`
       （直接按 RRULE 语义计算触发时刻），本函数仅保留给 UI 预览与旧数据兼容。
    """
    minute = rule.byminute if rule.byminute is not None else 0
    hour = rule.byhour if rule.byhour is not None else "*"
    if rule.freq == "DAILY":
        return f"{minute} {hour} */{rule.interval} * *"
    if rule.freq == "WEEKLY":
        days = ",".join(str(d) for d in rule.byday) if rule.byday else "*"
        return f"{minute} {hour} * * {days}"
    days = ",".join(str(d) for d in rule.bymonthday) if rule.bymonthday else "1"
    return f"{minute} {hour} {days} * *"


class RRuleTrigger(BaseTrigger):
    """按 **RRULE 语义**直接计算触发时刻的 APScheduler 触发器（**支持 INTERVAL**）。

    **AUD2-H08 / W9-02 修复**：此前把 RRULE **降级成 crontab** 来建 job
    → ``INTERVAL`` 被丢弃 / 语义错位 → **触发时刻与 RRULE 语义系统性偏离**。

    本触发器直接复用 :func:`_advance` 与 :func:`_slots_in_period`
    （与 :func:`expand_slots` **同一套语义**），
    从而保证「**实际触发时刻**」与「**幂等槽位**」（``_rrule_slot``）永远一致 ——
    否则 ``uq_runs_task_slot(task_id, scheduled_for)`` 形同虚设，会产生重复 run。

    **AUD2-H10 / W9-08 修复**：此前触发器（crontab）与槽位展开（dtstart 锚点）
    是**两套独立算法** → 同一规则可能给出不同的触发点 → 幂等闸门失效。
    现在两者同源。
    """

    def __init__(self, rule: RRule, dtstart: datetime, tzinfo) -> None:
        # APScheduler 的 BaseTrigger 没有 __init__（只有 __slots__ = ()）→
        # 自行设置 APScheduler 期望的属性。
        self.timezone = tzinfo
        self.start_date = None
        self.end_date = None
        self.rule = rule
        self.dtstart = dtstart
        self.tzinfo = tzinfo

    # ---- APScheduler 触发器协议 ---- #
    def get_next_fire_time(self, previous_fire_time, now):
        """求下一次触发时刻（与 ``expand_slots`` 同一套语义）。"""
        tz = self.tzinfo
        anchor_local = self.dtstart.astimezone(tz).replace(tzinfo=None)
        now_local = now.astimezone(tz).replace(tzinfo=None)
        if previous_fire_time is not None:
            prev_local = previous_fire_time.astimezone(tz).replace(tzinfo=None)
        else:
            prev_local = None

        cursor = anchor_local.replace(hour=0, minute=0, second=0, microsecond=0)
        # 时分来自 dtstart（未指定 BYHOUR/BYMINUTE 时）——不能从 cursor 取（已归一到零点）
        hour = self.rule.byhour if self.rule.byhour is not None else anchor_local.hour
        minute = self.rule.byminute if self.rule.byminute is not None else anchor_local.minute
        emitted = 0
        # 上限：防止规则异常时无限扫描（3 年 × 周期数）
        for _ in range(4000):
            for slot in _slots_in_period(self.rule, cursor, hour, minute):
                if slot < cursor:
                    continue
                if self.rule.count is not None and emitted >= self.rule.count:
                    return None
                emitted += 1
                if prev_local is None:
                    if slot < now_local:
                        continue
                else:
                    if slot <= prev_local:
                        continue
                aware = slot.replace(tzinfo=tz)
                if self.rule.until is not None and aware > self.rule.until:
                    return None
                return aware
            cursor = _advance(self.rule, cursor)
            if cursor > now_local + timedelta(days=3 * 366):
                break
        return None
