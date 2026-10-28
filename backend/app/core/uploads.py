"""上传策略（批次 01 / WP-2）：扩展名 / MIME 白名单与大小上限。

纯策略模块（不依赖 FastAPI），便于：
- 后端端点复用；
- 单元测试直接覆盖边界语义；
- 前端镜像同一份白名单（``frontend/.../src/api/upload-policy.ts``）。

口径：**白名单**（只放行图片 / 文档 / 文本 / 代码），可执行文件一律拒绝；
大小上限见 ``settings.upload_max_file_bytes`` / ``settings.upload_max_request_bytes``。
"""
from __future__ import annotations

from pathlib import Path

from app.core.config import settings

#: 图片
IMAGE_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".ico", ".tif", ".tiff"}
)

#: 文档
DOC_EXTENSIONS = frozenset(
    {
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp",
        ".rtf", ".epub",
    }
)

#: 文本 / 数据
TEXT_EXTENSIONS = frozenset(
    {
        ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml",
        ".toml", ".ini", ".cfg", ".conf", ".xml", ".html", ".htm", ".log",
    }
)

#: 代码
#: 说明：``.sh`` 作为**源码文本**保留（不自动执行）；Windows 可直接执行的
#: 批处理 / PowerShell 脚本（``.bat`` / ``.cmd`` / ``.ps1``）归入禁止清单。
CODE_EXTENSIONS = frozenset(
    {
        ".py", ".pyi", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".java", ".kt",
        ".c", ".h", ".cpp", ".hpp", ".cc", ".cs", ".go", ".rs", ".rb", ".php", ".swift",
        ".scala", ".sh", ".bash", ".zsh", ".sql", ".r", ".m", ".lua",
        ".vue", ".svelte", ".ipynb",
    }
)

#: 允许上传的扩展名全集
ALLOWED_EXTENSIONS = frozenset(
    IMAGE_EXTENSIONS | DOC_EXTENSIONS | TEXT_EXTENSIONS | CODE_EXTENSIONS
)

#: 明确禁止的可执行 / 二进制类型（即使被误配进白名单也要拒绝）
DENIED_EXTENSIONS = frozenset(
    {
        ".exe", ".dll", ".com", ".bat", ".cmd", ".scr", ".msi", ".msp", ".sys", ".cpl",
        ".ps1", ".vbs", ".wsf", ".hta", ".jar", ".apk", ".so", ".dylib", ".deb", ".rpm",
        ".app", ".pkg", ".whl", ".pyd", ".pyc", ".pyo", ".bin", ".elf", ".o", ".a",
        ".node", ".lnk", ".url", ".reg",
    }
)

#: 可执行文件的 MIME（客户端声明与扩展名不一致时的兜底判据）
EXECUTABLE_MIME_TYPES = frozenset(
    {
        "application/x-msdownload",
        "application/x-dosexec",
        "application/x-executable",
        "application/x-mach-binary",
        "application/x-msdos-program",
        "application/vnd.microsoft.portable-executable",
        "application/x-msi",
        "application/x-sharedlib",
        "application/x-elf",
        "application/java-archive",
        "application/x-sh",
        "application/vnd.microsoft.portable-executable",
    }
)

#: 允许的 MIME 前缀 / 精确值
ALLOWED_MIME_PREFIXES = ("text/", "image/")
ALLOWED_MIME_TYPES = frozenset(
    {
        "application/json",
        "application/xml",
        "application/pdf",
        "application/zip",
        "application/x-zip-compressed",
        "application/octet-stream",  # 浏览器常给二进制文件兜底这个类型，交给扩展名判定
        "application/x-yaml",
        "application/yaml",
    }
)


def allowed_extensions() -> frozenset[str]:
    """当前生效的扩展名白名单（``settings.upload_allowed_extensions`` 可覆盖）。"""
    raw = (settings.upload_allowed_extensions or "").strip()
    if not raw:
        return ALLOWED_EXTENSIONS
    items = {
        ext if ext.startswith(".") else f".{ext}"
        for ext in (part.strip().lower() for part in raw.split(","))
        if ext
    }
    return frozenset(items) if items else ALLOWED_EXTENSIONS


def check_extension(filename: str) -> str | None:
    """校验文件扩展名；返回拒绝原因（None = 放行）。"""
    suffix = Path(filename or "").suffix.lower()
    if not suffix:
        return f"文件缺少扩展名，无法判定类型：{filename}"
    if suffix in DENIED_EXTENSIONS:
        return f"禁止上传可执行文件类型（{suffix}）：{filename}"
    if suffix not in allowed_extensions():
        return f"文件类型不在白名单内（{suffix}）：{filename}"
    return None


def check_mime(content_type: str | None) -> str | None:
    """校验 MIME；返回拒绝原因（None = 放行）。

    客户端未提供 MIME 时不做判定（由扩展名把关）。
    """
    mime = (content_type or "").split(";")[0].strip().lower()
    if not mime:
        return None
    if mime in EXECUTABLE_MIME_TYPES:
        return f"禁止上传可执行文件类型（MIME {mime}）"
    if mime.startswith(ALLOWED_MIME_PREFIXES) or mime in ALLOWED_MIME_TYPES:
        return None
    return f"文件类型不在白名单内（MIME {mime}）"


def check_upload(filename: str, content_type: str | None) -> str | None:
    """扩展名 + MIME 联合校验；返回拒绝原因（None = 放行）。"""
    return check_extension(filename) or check_mime(content_type)


def max_file_bytes() -> int:
    """单文件大小上限。"""
    return int(settings.upload_max_file_bytes)


def max_request_bytes() -> int:
    """单请求总量上限。"""
    return int(settings.upload_max_request_bytes)


def format_bytes(size: int) -> str:
    """人类可读的字节数（用于错误提示）。"""
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.0f} MB"
    if size >= 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size} B"
