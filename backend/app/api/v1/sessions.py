"""会话管理接口。"""
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_session_service
from app.schemas.common import Page
from app.schemas.session import SessionCreate, SessionDetail, SessionOut, SessionUpdate
from app.services.session_service import SessionService

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionOut, status_code=201, summary="创建会话")
def create_session(
    payload: SessionCreate,
    service: SessionService = Depends(get_session_service),
) -> SessionOut:
    return service.create(
        mode=payload.mode,
        title=payload.title,
        skills=payload.skills,
        team_id=payload.team_id,
        config=payload.config,
    )


@router.get("", response_model=Page[SessionOut], summary="会话列表（按模式过滤 + 分页）")
def list_sessions(
    mode: str | None = Query(default=None, pattern="^(chat|plan|work)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    include_archived: bool = False,
    only_trashed: bool = False,
    service: SessionService = Depends(get_session_service),
) -> Page[SessionOut]:
    # **W9-12 / AUD2-H14**：``include_archived`` = 包含已归档的；
    # ``only_trashed`` = 只看回收站（已软删）。两者独立。
    items, total = service.list(
        mode=mode, page=page, page_size=page_size,
        include_archived=include_archived, only_trashed=only_trashed,
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{session_id}", response_model=SessionDetail, summary="会话详情（消息分页）")
def get_session(
    session_id: str,
    message_limit: int = Query(default=100, ge=1, le=500),
    before_seq: int | None = None,
    service: SessionService = Depends(get_session_service),
) -> SessionDetail:
    detail = service.get(session_id, message_limit=message_limit, before_seq=before_seq)
    if detail is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return detail


@router.delete(
    "/{session_id}/purge",
    summary="永久删除会话（管理员用；真正物理删除）",
)
def purge_session(
    session_id: str,
    service: SessionService = Depends(get_session_service),
) -> dict:
    """**永久删除**（P3-10）。

    普通 ``DELETE /sessions/{id}`` 是**软删除**（写 ``deleted_at``，消息保留）；
    本端点做真正的物理删除，供回收站「彻底删除」使用。
    """
    if not service.purge(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True, "purged": session_id}


@router.patch("/{session_id}", response_model=SessionOut, summary="更新会话（改名/归档/配置）")
def update_session(
    session_id: str,
    payload: SessionUpdate,
    service: SessionService = Depends(get_session_service),
) -> SessionOut:
    out = service.update(
        session_id,
        title=payload.title,
        archived=payload.archived,
        skills=payload.skills,
        team_id=payload.team_id,
        config=payload.config,
    )
    if out is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return out


@router.delete("/{session_id}", status_code=204, summary="删除会话（级联删除消息）")
def delete_session(
    session_id: str,
    service: SessionService = Depends(get_session_service),
) -> None:
    if not service.delete(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
