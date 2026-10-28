"""桌面事件总线（后端 → 壳）。

事件是**单向**的：后端发布，壳通过 ``GET /api/v1/desktop/events``（SSE）订阅。
实现采用「线程安全的环形缓冲 + 轮询」——与既有 ``runs.py`` 的 DB-tail SSE 同构，
避免在多线程（FastAPI 同步依赖跑在线程池）与 asyncio 之间传递队列的复杂度。

历史只保留最近 200 条，重连时带 ``after_id`` 补发。
"""
from __future__ import annotations

import threading
from collections import deque
from typing import Any

from app.db.models import utc_now

MAX_EVENTS = 200


class DesktopEventBus:
    """进程内事件总线。"""

    def __init__(self, maxlen: int = MAX_EVENTS) -> None:
        self._lock = threading.Lock()
        self._events: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._seq = 0

    def publish(self, event_type: str, **payload: Any) -> dict[str, Any]:
        """发布一条事件，返回事件体。"""
        with self._lock:
            self._seq += 1
            event = {"id": self._seq, "type": event_type, "ts": utc_now(), **payload}
            self._events.append(event)
            return event

    def since(self, after_id: int = 0) -> list[dict[str, Any]]:
        """取出 ``id > after_id`` 的事件（按发布顺序）。"""
        with self._lock:
            return [event for event in self._events if int(event.get("id", 0)) > after_id]

    def latest_id(self) -> int:
        with self._lock:
            return self._seq

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._seq = 0


#: 全局单例（与应用同生命周期）
bus = DesktopEventBus()
