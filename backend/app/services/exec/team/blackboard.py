"""黑板：任务项、依赖图、就绪判定（S6 / WP-6.7）。

状态机：``pending → ready → running → done``，另有 ``blocked`` / ``failed``。

- 就绪判定是**纯函数**：依赖全部 done → ready；任一 failed → blocked；
- **依赖环检测**：写入时拒绝成环（不会死锁）；
- 事件驱动重算：完成一项即触发重算（不用轮询）。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from sqlalchemy import select

from app.db.base import db_session
from app.db.models import BoardItemRow, utc_now

logger = logging.getLogger(__name__)

STATUSES = ("pending", "ready", "running", "done", "blocked", "failed")
TERMINAL = ("done", "failed")


class BoardError(ValueError):
    """黑板操作不合法。"""


@dataclass
class BoardItem:
    """黑板任务项。"""

    id: int | None
    board_id: str
    title: str
    detail: str = ""
    status: str = "pending"
    assignee: str | None = None
    deps: list[int] = field(default_factory=list)
    result: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "board_id": self.board_id,
            "title": self.title,
            "detail": self.detail,
            "status": self.status,
            "assignee": self.assignee,
            "deps": list(self.deps),
            "result": dict(self.result),
        }


def _row_to_item(row: BoardItemRow) -> BoardItem:
    def _load(raw: str, as_dict: bool = False):
        try:
            val = json.loads(raw or ("{}" if as_dict else "[]"))
        except json.JSONDecodeError:
            val = {} if as_dict else []
        return val

    return BoardItem(
        id=row.id,
        board_id=row.board_id,
        title=row.title,
        detail=row.detail or "",
        status=row.status,
        assignee=row.assignee,
        deps=[int(d) for d in _load(row.deps_json)],
        result=_load(row.result_json, as_dict=True),
    )


# --------------------------------------------------------------------------- #
# 纯函数：就绪判定与环检测
# --------------------------------------------------------------------------- #
def readiness(items: list[BoardItem]) -> dict[int, str]:
    """计算每个任务项的就绪状态。

    规则：
    - 依赖全部 ``done`` → ``ready``；
    - 任一依赖 ``failed`` → ``blocked``；
    - 自身已终态 → 保持原状。
    """
    by_id = {i.id: i for i in items}
    out: dict[int, str] = {}
    for item in items:
        if item.status in TERMINAL:
            out[item.id] = item.status
            continue
        deps = [by_id[d] for d in item.deps if d in by_id]
        if any(d.status == "failed" for d in deps):
            out[item.id] = "blocked"
        elif all(d.status == "done" for d in deps):
            out[item.id] = "ready"
        else:
            out[item.id] = "pending"
    return out


def would_create_cycle(items: list[BoardItem], item_id: int, deps: list[int]) -> bool:
    """若把 ``deps`` 加到 ``item_id`` 上会成环则返回 True（写入时拒绝）。"""
    if item_id in deps:
        return True
    graph: dict[int, list[int]] = {i.id: list(i.deps) for i in items}
    graph[item_id] = list(deps)

    visiting: set[int] = set()
    visited: set[int] = set()

    def visit(node: int) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for dep in graph.get(node, []):
            if visit(dep):
                return True
        visiting.discard(node)
        visited.add(node)
        return False

    return visit(item_id)


def assign_by_capability(
    items: list[BoardItem],
    roles: list,
    *,
    used: set[str] | None = None,
) -> dict[int, str | None]:
    """按能力标签匹配 + 角色负载指派（负载低的优先）。"""
    used = used or set()
    load: dict[str, int] = {}
    for item in items:
        if item.assignee:
            load[item.assignee] = load.get(item.assignee, 0) + 1
    out: dict[int, str | None] = {}
    for item in items:
        if item.assignee:
            out[item.id] = item.assignee
            continue
        words = f"{item.title} {item.detail}"
        best: tuple[int, str] | None = None
        for role in roles:
            if not role.enabled:
                continue
            score = sum(1 for tag in role.expertise if tag and tag in words)
            score += sum(1 for b in role.boundaries if b and b in words) * -1
            score -= load.get(role.name, 0)
            if score > 0 and (best is None or score > best[0]):
                best = (score, role.name)
        chosen = best[1] if best else None
        if chosen:
            load[chosen] = load.get(chosen, 0) + 1
        out[item.id] = chosen
    return out


# --------------------------------------------------------------------------- #
# 服务
# --------------------------------------------------------------------------- #
class BlackboardService:
    """黑板读写与状态推进。"""

    def create_item(
        self,
        board_id: str,
        title: str,
        *,
        detail: str = "",
        deps: list[int] | None = None,
        assignee: str | None = None,
    ) -> BoardItem:
        title = (title or "").strip()
        if not title:
            raise BoardError("任务项标题不能为空")
        deps = [int(d) for d in (deps or [])]
        with db_session() as db:
            items = [_row_to_item(r) for r in db.scalars(
                select(BoardItemRow).where(BoardItemRow.board_id == board_id)
            ).all()]
            # 新项 id 未分配 → 用临时负 id 参与环检测
            temp_id = -(max([abs(i.id or 0) for i in items] or [0]) + 1)
            probe = BoardItem(id=temp_id, board_id=board_id, title=title, deps=deps)
            if would_create_cycle(items, temp_id, deps):
                raise BoardError("依赖会形成环，已拒绝")
            row = BoardItemRow(
                board_id=board_id,
                title=title,
                detail=detail,
                status="pending",
                assignee=assignee,
                deps_json=json.dumps(deps, ensure_ascii=False),
                result_json="{}",
            )
            db.add(row)
            db.flush()
            return _row_to_item(row)

    def list_items(self, board_id: str) -> list[BoardItem]:
        with db_session() as db:
            rows = db.scalars(
                select(BoardItemRow).where(BoardItemRow.board_id == board_id).order_by(BoardItemRow.id)
            ).all()
            return [_row_to_item(r) for r in rows]

    def add_dep(self, item_id: int, dep_id: int) -> BoardItem:
        """给既有任务项追加依赖（**成环即拒**）。"""
        with db_session() as db:
            row = db.get(BoardItemRow, item_id)
            if row is None:
                raise BoardError(f"任务项不存在: {item_id}")
            board_id = row.board_id
        items = self.list_items(board_id)
        current = next((i for i in items if i.id == item_id), None)
        if current is None:
            raise BoardError(f"任务项不存在: {item_id}")
        deps = list(current.deps)
        if dep_id not in deps:
            deps.append(dep_id)
        if would_create_cycle(items, item_id, deps):
            raise BoardError("依赖会形成环，已拒绝")
        with db_session() as db:
            row = db.get(BoardItemRow, item_id)
            if row is not None:
                row.deps_json = json.dumps(deps, ensure_ascii=False)
                row.updated_at = utc_now()
        return next((i for i in self.list_items(board_id) if i.id == item_id), current)

    def set_status(self, item_id: int, status: str) -> BoardItem:
        if status not in STATUSES:
            raise BoardError(f"未知状态: {status}")
        with db_session() as db:
            row = db.get(BoardItemRow, item_id)
            if row is None:
                raise BoardError(f"任务项不存在: {item_id}")
            row.status = status
            row.updated_at = utc_now()
            db.flush()
            item = _row_to_item(row)
        return item

    def complete(self, item_id: int, result: dict | None = None) -> list[BoardItem]:
        """完成一项并**事件驱动重算**（不轮询）。"""
        with db_session() as db:
            row = db.get(BoardItemRow, item_id)
            if row is None:
                raise BoardError(f"任务项不存在: {item_id}")
            row.status = "done"
            row.result_json = json.dumps(result or {}, ensure_ascii=False)
            row.updated_at = utc_now()
            board_id = row.board_id
            db.flush()
        return self.recompute(board_id)

    def recompute(self, board_id: str) -> list[BoardItem]:
        """重算全板状态（依赖变化即时生效）。"""
        items = self.list_items(board_id)
        states = readiness(items)
        with db_session() as db:
            for item in items:
                new_state = states.get(item.id)
                if new_state and new_state != item.status:
                    row = db.get(BoardItemRow, item.id)
                    if row is not None:
                        row.status = new_state
                        row.updated_at = utc_now()
        return self.list_items(board_id)

    def assign(self, board_id: str, roles: list) -> list[BoardItem]:
        """按能力与负载指派。"""
        items = self.list_items(board_id)
        mapping = assign_by_capability(items, roles)
        with db_session() as db:
            for item_id, assignee in mapping.items():
                row = db.get(BoardItemRow, item_id)
                if row is not None:
                    row.assignee = assignee
                    row.updated_at = utc_now()
        return self.list_items(board_id)
