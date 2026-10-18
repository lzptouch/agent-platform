"""Skill 管理接口（含 CRUD / 启停用 / 导入导出）。"""

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response

from app.api.deps import get_skill_manager
from app.schemas.skill import (
    SkillCreate,
    SkillDetail,
    SkillListResponse,
    SkillMeta,
    SkillToggle,
    SkillUpdate,
    ValidationResult,
)
from app.services.skill_manager import (
    SkillConflictError,
    SkillForbiddenError,
    SkillManager,
    SkillValidationError,
)

router = APIRouter(prefix="/skills", tags=["skills"])


def _to_meta(skill: dict) -> SkillMeta:
    return SkillMeta(**{k: v for k, v in skill.items() if k not in ("content", "mtime")})


@router.get("", response_model=SkillListResponse, summary="列出所有 Skill")
def list_skills(manager: SkillManager = Depends(get_skill_manager)) -> SkillListResponse:
    skills = [_to_meta(s) for s in manager.list_skills()]
    return SkillListResponse(total=len(skills), skills=skills)


@router.post("", response_model=SkillMeta, status_code=201, summary="创建 Skill（写入自定义目录）")
def create_skill(payload: SkillCreate, manager: SkillManager = Depends(get_skill_manager)) -> SkillMeta:
    try:
        skill = manager.create(payload.name, payload.description, payload.content)
    except SkillConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except SkillValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _to_meta(skill)


@router.post("/import", response_model=SkillMeta, summary="导入 Skill zip 包")
async def import_skill(
    file: UploadFile,
    overwrite: bool = Query(default=False),
    manager: SkillManager = Depends(get_skill_manager),
) -> SkillMeta:
    data = await file.read()
    try:
        skill = manager.import_zip(data, overwrite=overwrite)
    except SkillConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except SkillValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _to_meta(skill)


@router.post("/reload", summary="重新扫描 skills 目录")
def reload_skills(manager: SkillManager = Depends(get_skill_manager)) -> dict:
    count = manager.reload()
    return {"reloaded": count, "skills": [s["name"] for s in manager.list_skills()]}


@router.get("/{name}", response_model=SkillDetail, summary="获取 Skill 详情")
def get_skill(name: str, manager: SkillManager = Depends(get_skill_manager)) -> SkillDetail:
    skill = manager.get(name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill 不存在: {name}")
    return SkillDetail(**{k: v for k, v in skill.items() if k != "mtime"})


@router.put("/{name}", response_model=SkillMeta, summary="更新 Skill（仅自定义）")
def update_skill(name: str, payload: SkillUpdate, manager: SkillManager = Depends(get_skill_manager)) -> SkillMeta:
    try:
        skill = manager.update(name, description=payload.description, content=payload.content)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Skill 不存在: {name}") from None
    except SkillForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except SkillValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _to_meta(skill)


@router.post("/{name}/toggle", response_model=SkillMeta, summary="启停用 Skill")
def toggle_skill(name: str, payload: SkillToggle, manager: SkillManager = Depends(get_skill_manager)) -> SkillMeta:
    try:
        manager.set_enabled(name, payload.enabled)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Skill 不存在: {name}") from None
    skill = manager.get(name)
    assert skill is not None
    return _to_meta(skill)


@router.delete("/{name}", summary="删除 Skill（软删除，仅自定义）")
def delete_skill(name: str, manager: SkillManager = Depends(get_skill_manager)) -> dict:
    try:
        trash_path = manager.delete(name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Skill 不存在: {name}") from None
    except SkillForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return {"deleted": name, "trash_path": trash_path}


@router.get("/{name}/export", summary="导出 Skill 为 zip")
def export_skill(name: str, manager: SkillManager = Depends(get_skill_manager)) -> Response:
    try:
        data, filename = manager.export_zip(name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Skill 不存在: {name}") from None
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{name}/validate", response_model=ValidationResult, summary="校验 Skill 是否符合规范")
def validate_skill(name: str, manager: SkillManager = Depends(get_skill_manager)) -> ValidationResult:
    skill = manager.get(name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill 不存在: {name}")
    from pathlib import Path

    from app.core.config import PROJECT_ROOT

    valid, message, parsed_name = manager.validate_skill(PROJECT_ROOT / skill["path"])
    return ValidationResult(valid=valid, message=message, name=parsed_name)


@router.get("/{name}/files/{resource_path:path}", summary="读取 Skill 附属资源文件")
def get_skill_resource(
    name: str,
    resource_path: str,
    manager: SkillManager = Depends(get_skill_manager),
) -> FileResponse:
    path = manager.get_resource_path(name, resource_path)
    if not path:
        raise HTTPException(status_code=404, detail=f"资源不存在: {name}/{resource_path}")
    return FileResponse(path)
