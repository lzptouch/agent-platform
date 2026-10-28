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
    start = dtstart.replace(tzinfo=None)  # 本地时间（无时区）
    hour = rule.byhour if rule.byhour is not None else start.hour
    minute = rule.byminute if rule.byminute is not None else start.minute

    cursor = start
    end = start + timedelta(days=horizon_days)
    until_local = rule.until.replace(tzinfo=None) if rule.until else None

    while cursor <= end and len(out) < limit and (rule.count is None or len(out) < rule.count):
        if until_local is not None and cursor > until_local:
            break
        for slot in _slots_in_period(rule, cursor):
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


def _slots_in_period(rule: RRule, cursor: datetime) -> list[datetime]:
    """按周期展开当期的槽位。"""
    hour = rule.byhour if rule.byhour is not None else cursor.hour
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
    """把 RRULE 子集展开为 cron（供既有调度器使用）。"""
    minute = rule.byminute if rule.byminute is not None else 0
    hour = rule.byhour if rule.byhour is not None else "*"
    if rule.freq == "DAILY":
        return f"{minute} {hour} */{rule.interval} * *"
    if rule.freq == "WEEKLY":
        days = ",".join(str(d) for d in rule.byday) if rule.byday else "*"
        return f"{minute} {hour} * * {days}"
    days = ",".join(str(d) for d in rule.bymonthday) if rule.bymonthday else "1"
    return f"{minute} {hour} {days} * *"
