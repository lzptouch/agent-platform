"""桌面会话引导与访问边界。

安全模型（见 ``doc/design/04-本地数据与安全边界设计.md`` §5.2）：

- **一次性引导 nonce**：``GET /__desktop/bootstrap?t=<nonce>`` 校验通过即作废，
  下发 HttpOnly + SameSite=Strict 的会话 Cookie 后 302 回 ``/``；
- **常驻会话令牌**：``X-Agent-Desktop-Token`` header，供壳自身的 Node 侧请求使用，
  **永不出现在 URL**；
- **Host 头白名单**：只接受 ``127.0.0.1`` / ``localhost`` 且端口等于本进程端口，
  防 DNS rebinding。

以上校验**只在桌面模式（``AGENT_DESKTOP=1``）下启用**；Web 形态行为零变化。
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import threading

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

from app.core.config import settings

logger = logging.getLogger(__name__)

COOKIE_NAME = "agent_desktop_session"
HEADER_NAME = "X-Agent-Desktop-Token"

#: 允许的 Host 主机名（端口必须与本进程一致）
ALLOWED_HOSTNAMES = frozenset({"127.0.0.1", "localhost"})

_lock = threading.Lock()
_state: dict[str, object] = {"session_id": None, "nonce_consumed": False}


# ---------------------------------------------------------------------- #
# 会话
# ---------------------------------------------------------------------- #
def _derive(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]


def issue_session() -> str:
    """基于当前常驻令牌派发会话 ID（进程内有效，重启即失效）。"""
    token = settings.desktop_token
    if not token:
        raise RuntimeError("桌面模式未注入 AGENT_DESKTOP_TOKEN")
    session_id = _derive(token)
    with _lock:
        _state["session_id"] = session_id
    return session_id


def current_session_id() -> str | None:
    with _lock:
        value = _state["session_id"]
    return value if isinstance(value, str) else None


def reset_state() -> None:
    """清空会话状态（测试用）。"""
    with _lock:
        _state["session_id"] = None
        _state["nonce_consumed"] = False


# ---------------------------------------------------------------------- #
# 引导
# ---------------------------------------------------------------------- #
def consume_nonce(candidate: str) -> bool:
    """校验并作废一次性引导 nonce。"""
    expected = settings.desktop_bootstrap_nonce
    if not expected or not candidate:
        return False
    with _lock:
        if _state["nonce_consumed"]:
            return False
        if not hmac.compare_digest(candidate, expected):
            return False
        _state["nonce_consumed"] = True
    return True


def bootstrap_response(request: Request) -> RedirectResponse:
    """处理引导请求：校验 nonce → 下发 Cookie → 302 回首页。"""
    nonce = request.query_params.get("t", "")
    if not consume_nonce(nonce):
        logger.warning("桌面引导令牌无效或已使用")
        raise HTTPException(status_code=401, detail="引导令牌无效或已使用")

    session_id = issue_session()
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        COOKIE_NAME,
        session_id,
        httponly=True,
        samesite="strict",
        path="/",
    )
    return response


# ---------------------------------------------------------------------- #
# 访问边界
# ---------------------------------------------------------------------- #
def host_allowed(request: Request) -> bool:
    """Host 头白名单：仅接受 loopback + 正确端口。"""
    raw = request.headers.get("host", "").strip()
    if not raw:
        return False
    if raw.startswith("["):  # IPv6 字面量
        host, _, port = raw.rpartition("]:")
        host = host.lstrip("[")
    else:
        host, _, port = raw.rpartition(":")
        if not port:  # 无端口
            host, port = raw, ""
    if host not in ALLOWED_HOSTNAMES:
        return False
    if not port:
        return False
    return port == str(settings.port)


def request_authorized(request: Request) -> bool:
    """校验会话：Cookie 或 Header 令牌任一通过即可。"""
    token = settings.desktop_token
    if not token:
        return False

    header_value = request.headers.get(HEADER_NAME, "")
    if header_value and hmac.compare_digest(header_value, token):
        return True

    cookie_value = request.cookies.get(COOKIE_NAME, "")
    session_id = current_session_id()
    if cookie_value and session_id and hmac.compare_digest(cookie_value, session_id):
        return True
    return False


def guard(request: Request) -> None:
    """桌面模式下的访问守卫；不通过则抛 HTTP 异常。"""
    if not settings.desktop_mode:
        return
    if not host_allowed(request):
        raise HTTPException(status_code=421, detail="非法 Host")
    if not request_authorized(request):
        raise HTTPException(status_code=401, detail="桌面会话未建立，请重启应用")
