"""产出文件接口（生成文件浏览 / 上传 / 删除）。"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import get_executor
from app.services.code_executor import LocalCodeExecutor

router = APIRouter(prefix="/files", tags=["files"])

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _safe_path(executor: LocalCodeExecutor, filename: str):
    name = filename.strip().replace("\\", "/").split("/")[-1]
    if not name or name in {".", ".."}:
        raise HTTPException(status_code=400, detail="非法文件名")
    return executor.output_dir / name


@router.get("", summary="列出已生成的文件")
def list_files(executor: LocalCodeExecutor = Depends(get_executor)) -> dict:
    files = []
    for path in sorted(executor.output_dir.iterdir()):
        if not path.is_file():
            continue
        files.append(
            {
                "name": path.name,
                "size": path.stat().st_size,
                "is_image": path.suffix.lower() in IMAGE_SUFFIXES,
                "url": f"/api/v1/files/{path.name}",
            }
        )
    return {"total": len(files), "files": files}


@router.post("/upload", summary="上传文件到输出目录")
async def upload_file(
    file: UploadFile = File(...),
    executor: LocalCodeExecutor = Depends(get_executor),
) -> dict:
    name = (file.filename or "upload.bin").strip().replace("\\", "/").split("/")[-1]
    if not name:
        raise HTTPException(status_code=400, detail="非法文件名")
    target = executor.output_dir / name
    target.write_bytes(await file.read())
    return {"name": name, "size": target.stat().st_size, "url": f"/api/v1/files/{name}"}


@router.get("/{filename}", summary="下载 / 预览已生成的文件")
def get_file(filename: str, executor: LocalCodeExecutor = Depends(get_executor)) -> FileResponse:
    path = _safe_path(executor, filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在: {filename}")
    return FileResponse(path, filename=path.name)


@router.delete("/{filename}", summary="删除已生成的文件")
def delete_file(filename: str, executor: LocalCodeExecutor = Depends(get_executor)) -> dict:
    path = _safe_path(executor, filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在: {filename}")
    path.unlink()
    return {"deleted": path.name}
