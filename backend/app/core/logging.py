"""结构化日志与上下文（S7 / WP-7.8）。

- JSON 行日志（可按 request_id / run_id / session_id 检索）；
- 上下文自动注入（请求入口 / run 开始结束 / 调度触发）；
- **敏感字段脱敏**（密码/密钥/token 不入日志）。

保留既有 plain-text 日志为兼容模式（``settings.structured_logging`` 默认开）。
"""
from __future__ import annotations

import json
import logging
import random
import re
import sys
from contextvars import ContextVar, Token
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

#: 当前日志上下文（请求 / run / 任务）
current_context: ContextVar[dict[str, Any]] = ContextVar("log_context", default={})

#: 脱敏的字段名
_SENSITIVE_KEYS = ("password", "passwd", "secret", "token", "api_key", "apikey",
                   "authorization", "credential", "key")

#: 脱敏的正则（值里有密钥格式则脱敏）
_SECRET_VALUE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}|AKIA[0-9A-Z]{16}|-----BEGIN)",
)


def set_context(**fields: Any) -> None:
    """设置日志上下文（请求 ID / run / 任务）。"""
    ctx = dict(current_context.get())
    ctx.update(fields)
    current_context.set(ctx)


def clear_context() -> None:
    current_context.set({})


def bind_context(**fields: Any) -> Token:
    """绑定上下文字段并返回复位令牌（**推荐**：可在 finally 里精确复位）。"""
    ctx = dict(current_context.get())
    ctx.update(fields)
    return current_context.set(ctx)


def reset_context(token: Token) -> None:
    """复位上下文（用 bind_context 返回的令牌）。"""
    try:
        current_context.reset(token)
    except ValueError:
        # 令牌来自别的上下文（跨线程/跨任务）→ 退化为整体清空
        current_context.set({})


def _redact(value: Any) -> Any:
    """脱敏：值里有密钥格式 → 掩码。"""
    if isinstance(value, str) and _SECRET_VALUE.search(value):
        return value[:12] + "***"
    return value


def _redact_dict(data: dict) -> dict:
    """递归脱敏（键名敏感 → 整值掩码）。"""
    out: dict = {}
    for key, value in data.items():
        low = key.lower()
        if any(k in low for k in _SENSITIVE_KEYS):
            out[key] = "***"
        elif isinstance(value, dict):
            out[key] = _redact_dict(value)
        elif isinstance(value, list):
            out[key] = [_redact_dict(v) if isinstance(v, dict) else _redact(v) for v in value]
        else:
            out[key] = _redact(value)
    return out


def _format(record: logging.LogRecord) -> str:
    """格式化为 JSON 行（上下文全量注入，敏感字段脱敏）。"""
    ctx = dict(current_context.get())
    payload: dict = {
        "ts": record.created,
        "level": record.levelname,
        "logger": record.name,
        "message": record.getMessage(),
    }
    # 上下文里的所有字段都进载荷（request_id / run_id / session_id / task_id 等）
    for key, value in ctx.items():
        payload.setdefault(key, value)
    # 固定字段保底（即便上下文没有）
    for key in ("request_id", "run_id", "session_id", "task_id"):
        payload.setdefault(key, None)
    if record.exc_info:
        payload["exc"] = logging.Formatter().formatException(record.exc_info)
    return json.dumps(_redact_dict(payload), ensure_ascii=False, default=str)


class StructuredFormatter(logging.Formatter):
    """JSON 行格式化器。"""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        return _format(record)


class LevelSamplingFilter(logging.Filter):
    """按级别采样：**错误及以上全量**，DEBUG 级按比例抽样。

    ``rate=1.0`` 表示全量记录；``rate=0`` 表示只留 INFO 以上。
    """

    def __init__(self, rate: float = 1.0) -> None:
        super().__init__()
        self.rate = max(0.0, min(1.0, float(rate)))

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if record.levelno >= logging.INFO:
            return True
        if self.rate >= 1.0:
            return True
        if self.rate <= 0.0:
            return False
        return random.random() < self.rate


def configure(level: str = "INFO") -> None:
    """配置结构化日志（输出到 stderr）。"""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(StructuredFormatter())
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def enable_file_logging(
    level: str | None = None,
    directory: str | Path | None = None,
    filename: str | None = None,
) -> logging.Handler | None:
    """挂载**轮转文件日志**（JSON 行）。

    - 默认写到 ``settings.logs_dir/app.log``（``data/logs/``）；
    - 按大小轮转（``log_file_max_bytes`` / ``log_file_backup_count``）；
    - 错误及以上全量，DEBUG 级按 ``log_debug_sample_rate`` 抽样；
    - 幂等：已挂载过就不重复挂（避免同一文件被写两遍）。

    返回 handler；未启用（``settings.log_to_file=False``）时返回 ``None``。
    """
    from app.core.config import settings

    if not settings.log_to_file:
        return None
    root = logging.getLogger()
    for existing in root.handlers:
        if getattr(existing, "_agent_file_handler", False):
            return existing

    target_dir = Path(directory) if directory else Path(settings.logs_dir)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    path = target_dir / (filename or settings.log_file_name)
    try:
        handler = RotatingFileHandler(
            path,
            maxBytes=settings.log_file_max_bytes,
            backupCount=settings.log_file_backup_count,
            encoding="utf-8",
        )
    except OSError:
        return None
    handler.setFormatter(StructuredFormatter())
    handler.setLevel(getattr(logging, (level or settings.log_file_level).upper(), logging.DEBUG))
    handler.addFilter(LevelSamplingFilter(settings.log_debug_sample_rate))
    handler._agent_file_handler = True  # type: ignore[attr-defined]
    root.addHandler(handler)

    # 记录级别是**logger 级**闸门：root 停在 INFO 的话 DEBUG 根本到不了 handler，
    # 采样也就无从谈起 → 放宽 root 到 DEBUG，并把其它 handler（stderr）固定在 INFO，
    # 避免调试日志把 stderr 淹掉。
    if root.level > logging.DEBUG or root.level == logging.NOTSET:
        root.setLevel(logging.DEBUG)
    for other in root.handlers:
        if other is not handler and other.level == logging.NOTSET:
            other.setLevel(logging.INFO)
    return handler
