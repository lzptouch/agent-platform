"""统一错误模型与请求 ID（S1 / WP-1.1）。

设计要点：
- **一个错误体**：``{"code", "message", "detail", "request_id"}``，所有失败路径一致；
- **请求 ID 全链路贯通**：入口中间件生成或透传 ``X-Request-ID``，写入上下文，
  错误体与响应头都带它，便于日志检索；
- **中间件内抛出的异常不再变成 500**：``HTTPException`` 在用户中间件里抛出时
  不会经过 FastAPI 的异常处理器（ExceptionMiddleware 在其内侧），因此这里
  显式捕获并转换为统一响应（此前桌面态未授权访问返回 500 而不是 401）。
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse

REQUEST_ID_HEADER = "X-Request-ID"

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


# --------------------------------------------------------------------------- #
# 错误码
# --------------------------------------------------------------------------- #
class ErrorCode:
    """错误码常量（HTTP 状态与业务码分离）。"""

    VALIDATION = "E_VALIDATION"
    NOT_FOUND = "E_NOT_FOUND"
    CONFLICT = "E_CONFLICT"
    AUTH = "E_AUTH"
    PERMISSION = "E_PERMISSION"
    RUN = "E_RUN"
    WORKSPACE = "E_WORKSPACE"
    MCP = "E_MCP"
    SCHEDULER = "E_SCHEDULER"
    FILE = "E_FILE"
    UPSTREAM = "E_UPSTREAM"
    INTERNAL = "E_INTERNAL"
    TOO_LARGE = "E_TOO_LARGE"

    @classmethod
    def from_status(cls, status_code: int) -> str:
        return {
            400: cls.VALIDATION,
            401: cls.AUTH,
            403: cls.PERMISSION,
            404: cls.NOT_FOUND,
            409: cls.CONFLICT,
            413: cls.TOO_LARGE,
            415: cls.VALIDATION,
            421: cls.AUTH,
            422: cls.VALIDATION,
            500: cls.INTERNAL,
            502: cls.UPSTREAM,
            503: cls.UPSTREAM,
        }.get(status_code, cls.INTERNAL)


class AppError(Exception):
    """业务异常：带错误码与人类可读原因。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        detail: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail


# --------------------------------------------------------------------------- #
# 请求 ID
# --------------------------------------------------------------------------- #
def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def set_request_id(value: str | None) -> str:
    rid = value or new_request_id()
    _request_id.set(rid)
    return rid


def get_request_id() -> str:
    return _request_id.get() or new_request_id()


# --------------------------------------------------------------------------- #
# 统一响应
# --------------------------------------------------------------------------- #
def error_body(
    code: str,
    message: str,
    *,
    detail: Any = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "detail": detail,
        "request_id": request_id or get_request_id(),
    }


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    detail: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    rid = get_request_id()
    resp = JSONResponse(
        status_code=status_code,
        content=error_body(code, message, detail=detail, request_id=rid),
        headers={REQUEST_ID_HEADER: rid, **(headers or {})},
    )
    return resp


def http_exception_response(exc: HTTPException) -> JSONResponse:
    """把 FastAPI/Starlette 的 HTTPException 转成统一错误体。

    兼容约定：``detail`` 保留原始载荷（旧的 HTTPException 语义，前端与既有测试
    读 ``detail``），``message`` 是新增的人类可读字段，``code``/``request_id``
    是新增的结构化字段。
    """
    detail = exc.detail
    message = detail if isinstance(detail, str) else "请求失败"
    return error_response(
        exc.status_code,
        ErrorCode.from_status(exc.status_code),
        message,
        detail=detail,
        headers=getattr(exc, "headers", None),
    )
