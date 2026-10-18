"""Skill 团队接口。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_team_service
from app.schemas.team import ResolveOut, ResolveRequest, TeamCreate, TeamOut, TeamUpdate
from app.services.team_service import (
    TeamConflictError,
    TeamNotFoundError,
    TeamService,
    TeamValidationError,
)

router = APIRouter(prefix="/teams", tags=["teams"])


class ToggleRequest(BaseModel):
    enabled: bool


@router.get("", response_model=list[TeamOut], summary="团队列表")
def list_teams(
    include_disabled: bool = True,
    service: TeamService = Depends(get_team_service),
) -> list[TeamOut]:
    return service.list(include_disabled=include_disabled)


@router.post("", response_model=TeamOut, status_code=201, summary="创建团队")
def create_team(payload: TeamCreate, service: TeamService = Depends(get_team_service)) -> TeamOut:
    try:
        return service.create(
            name=payload.name,
            skill_names=payload.skill_names,
            description=payload.description,
            prompt_prefix=payload.prompt_prefix,
            strategy=payload.strategy,
        )
    except TeamConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except TeamValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{team_id}", response_model=TeamOut, summary="团队详情")
def get_team(team_id: str, service: TeamService = Depends(get_team_service)) -> TeamOut:
    team = service.get(team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    return team


@router.put("/{team_id}", response_model=TeamOut, summary="更新团队")
def update_team(
    team_id: str,
    payload: TeamUpdate,
    service: TeamService = Depends(get_team_service),
) -> TeamOut:
    try:
        team = service.update(team_id, **payload.model_dump(exclude_unset=True))
    except TeamConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except TeamValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    return team


@router.delete("/{team_id}", status_code=204, summary="删除团队（会话 team_id 置空）")
def delete_team(team_id: str, service: TeamService = Depends(get_team_service)) -> None:
    if not service.delete(team_id):
        raise HTTPException(status_code=404, detail="团队不存在")


@router.post("/{team_id}/toggle", response_model=TeamOut, summary="启停用团队")
def toggle_team(
    team_id: str,
    payload: ToggleRequest,
    service: TeamService = Depends(get_team_service),
) -> TeamOut:
    if not service.set_enabled(team_id, payload.enabled):
        raise HTTPException(status_code=404, detail="团队不存在")
    team = service.get(team_id)
    assert team is not None
    return team


@router.post("/{team_id}/resolve", response_model=ResolveOut, summary="预览团队展开结果")
def resolve_team(
    team_id: str,
    payload: ResolveRequest,
    service: TeamService = Depends(get_team_service),
) -> ResolveOut:
    try:
        return service.resolve(team_id, query=payload.query, mode=payload.mode)
    except TeamNotFoundError:
        raise HTTPException(status_code=404, detail="团队不存在") from None
