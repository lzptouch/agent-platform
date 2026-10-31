"""产出文件接口（生成文件浏览 / 上传 / 删除）。

**上传边界**（批次 01 / WP-2）：

- 单文件大小上限（默认 50 MB）+ 单请求总量上限（默认 100 MB）→ 超限 413；
- 扩展名 / MIME 白名单 → 可执行文件一律拒绝；
- 落盘走**流式计数**（不整体读进内存），超限即删半成品文件。
"""

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import get_executor
from app.core.uploads import (
    allowed_extensions,
    ALLOWED_EXTENSIONS,
    check_upload,
    format_bytes,
    max_file_bytes,
    max_request_bytes,
)
from app.services.code_executor import LocalCodeExecutor

router = APIRouter(prefix="/files", tags=["files"])

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

#: 流式落盘的读取块大小
CHUNK_SIZE = 1024 * 1024


def _safe_path(executor: LocalCodeExecutor, filename: str):
    name = filename.strip().replace("\\", "/").split("/")[-1]
    if not name or name in {".", ".."}:
        raise HTTPException(status_code=400, detail="非法文件名")
    return executor.output_dir / name


@router.get("/policy", summary="当前生效的上传策略（白名单 / 大小上限）")
def upload_policy() -> dict:
    """**单一真相源**（P4-04）：环境变量覆盖后的实际白名单。

    上传白名单此前有**三份**（前端 `upload-policy.ts`、后端内置清单、
    环境变量覆盖）→ 前端拦下的扩展名后端可能放行。
    前端改为运行时拉取本端点（带本地兜底默认值）。
    """
    return {
        "extensions": sorted(allowed_extensions()),
        "builtin_extensions": sorted(ALLOWED_EXTENSIONS),
        "max_file_bytes": max_file_bytes(),
        "max_request_bytes": max_request_bytes(),
    }


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
    request: Request,
    file: UploadFile = File(...),
    executor: LocalCodeExecutor = Depends(get_executor),
) -> dict:
    name = (file.filename or "").strip().replace("\\", "/").split("/")[-1]
    if not name:
        raise HTTPException(status_code=400, detail="非法文件名")

    # 1) 类型白名单：扩展名 + MIME（可执行文件一律拒绝）
    reason = check_upload(name, file.content_type)
    if reason:
        raise HTTPException(status_code=415, detail=reason)

    # 2) 请求总量上限：先看 Content-Length，避免把超大请求体读进来
    limit_request = max_request_bytes()
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > limit_request:
        raise HTTPException(
            status_code=413,
            detail=f"上传内容超过单请求上限（{format_bytes(limit_request)}）",
        )

    # 3) 流式落盘 + 单文件计数（超限即删半成品）
    limit_file = max_file_bytes()
    target = executor.output_dir / name
    written = 0
    try:
        with target.open("wb") as fh:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit_file:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件超过单文件上限（{format_bytes(limit_file)}）",
                    )
                fh.write(chunk)
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"写入文件失败: {exc}") from exc
    finally:
        await file.close()

    return {"name": name, "size": written, "url": f"/api/v1/files/{name}"}


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
