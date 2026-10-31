"""桌面守卫的 DNS-rebinding 防御用例（**F-ENG-07 / W11-07**）。

**AUD2-C07 / W11-07**：``app/desktop/bootstrap.py`` 的 ``host_allowed()`` /
``request_authorized()`` / ``guard()`` 是**唯一的 DNS-rebinding 防线**，
但此前**全仓零测试覆盖**（``grep host_allowed backend/tests/`` → 0）。

本文件补齐该覆盖：
- ``host_allowed`` 的真/假表驱动用例（含 ``Host: 127.0.0.1.evil.com:port`` 这类构造）；
- ``request_authorized`` 的 header / cookie / 过期 / 非 ASCII 路径；
- ``guard()`` 的 421（非法 Host）与 401（无会话）两条出口。
"""
from __future__ import annotations

import pytest
from starlette.requests import Request

from app.desktop import bootstrap as bs


def _request(headers: dict[str, str], *, path: str = "/api/v1/health") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": raw,
            "client": ("127.0.0.1", 51234),
            "server": ("127.0.0.1", 8080),
            "scheme": "http",
        }
    )


# --------------------------------------------------------------------------- #
# host_allowed —— Host 白名单
# --------------------------------------------------------------------------- #
#: 白名单要求 **loopback + 与配置一致的端口**（``host_allowed`` 的真实语义）
_PORT = str(bs.settings.port)


@pytest.mark.parametrize(
    "host_template,expected",
    [
        ("127.0.0.1:{p}", True),
        ("localhost:{p}", True),
        # IPv6 不在白名单（fail-closed）：壳侧只用 127.0.0.1
        ("[::1]:{p}", False),
        # 无端口 → 拒绝（无法确认端口）
        ("127.0.0.1", False),
        # **前缀相同但不是本机** → 必须拒绝
        ("127.0.0.1.evil.com:{p}", False),
        ("127.0.0.1.evil.com", False),
        ("localhost.evil.com:{p}", False),
        ("evil.com:{p}", False),
        ("10.0.0.5:{p}", False),
        ("192.168.1.10:{p}", False),
        # 端口不对 → 拒绝
        ("127.0.0.1:1", False),
        ("", False),
    ],
)
def test_host_allowed_表驱动(host_template, expected):
    """**F-ENG-07**：Host 白名单必须有真/假两组用例（此前零覆盖）。"""
    req = _request({"host": host_template.format(p=_PORT)})
    assert bs.host_allowed(req) is expected, f"Host={host_template!r} 判定不符预期"


def test_host_allowed_拒绝前缀构造攻击():
    """``127.0.0.1.evil.com:<port>`` 必须被拒（DNS rebinding 的经典构造）。"""
    req = _request({"host": f"127.0.0.1.evil.com:{_PORT}"})
    assert not bs.host_allowed(req)


# --------------------------------------------------------------------------- #
# request_authorized —— 会话校验
# --------------------------------------------------------------------------- #
def test_request_authorized_无凭据拒绝(monkeypatch):
    monkeypatch.setenv("AGENT_DESKTOP_TOKEN", "tok-123")
    assert bs.request_authorized(_request({"host": f"127.0.0.1:{_PORT}"})) is False


def test_request_authorized_正确头通过(monkeypatch):
    monkeypatch.setenv("AGENT_DESKTOP_TOKEN", "tok-123")
    req = _request({"host": f"127.0.0.1:{_PORT}", bs.HEADER_NAME: "tok-123"})
    assert bs.request_authorized(req) is True


def test_request_authorized_错误头拒绝(monkeypatch):
    monkeypatch.setenv("AGENT_DESKTOP_TOKEN", "tok-123")
    req = _request({"host": f"127.0.0.1:{_PORT}", bs.HEADER_NAME: "tok-999"})
    assert bs.request_authorized(req) is False


def test_request_authorized_非ASCII头不抛异常(monkeypatch):
    """非 ASCII 头此前会让 ``hmac.compare_digest`` 抛 TypeError → 稳定 500。

    **AUD2-L11 / W7-07**：畸形头必须**判定失败**，而不是把服务打成 500。
    """
    monkeypatch.setenv("AGENT_DESKTOP_TOKEN", "tok-123")
    req = _request({"host": f"127.0.0.1:{_PORT}", bs.HEADER_NAME: "tok-é"})
    assert bs.request_authorized(req) is False


def test_request_authorized_有效Cookie通过(monkeypatch):
    monkeypatch.setenv("AGENT_DESKTOP_TOKEN", "tok-123")
    session = bs.issue_session()
    req = _request({"host": f"127.0.0.1:{_PORT}", "cookie": f"{bs.COOKIE_NAME}={session}"})
    assert bs.request_authorized(req) is True


def test_会话ID_与令牌不可互相推导(monkeypatch):
    """**AUD2-M13**：会话 ID 此前是 ``sha256(token)[:32]``（无盐确定性派生）
    → 拿到 Cookie 即等价于拿到常驻令牌。现在必须是**独立随机**的。"""
    monkeypatch.setenv("AGENT_DESKTOP_TOKEN", "tok-123")
    session = bs.issue_session()
    import hashlib

    assert session != hashlib.sha256(b"tok-123").hexdigest()[:32]
    assert "tok-123" not in session
    # 两次签发应当不同
    assert bs.issue_session() != session


def test_会话过期后拒绝(monkeypatch):
    """**W7-07**：会话有 TTL，过期必须重新引导。"""
    monkeypatch.setenv("AGENT_DESKTOP_TOKEN", "tok-123")
    session = bs.issue_session()
    req = _request({"host": f"127.0.0.1:{_PORT}", "cookie": f"{bs.COOKIE_NAME}={session}"})
    assert bs.request_authorized(req) is True

    # 把签发时间推到 TTL 之前
    with bs._lock:
        bs._state["session_issued_at"] = 0.0
    assert bs.request_authorized(req) is False


# --------------------------------------------------------------------------- #
# guard —— 出口码
# --------------------------------------------------------------------------- #
def test_guard_非法Host返回421(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setenv("AGENT_DESKTOP", "1")
    monkeypatch.setenv("AGENT_DESKTOP_TOKEN", "tok-123")
    req = _request({"host": f"evil.com:{_PORT}"})
    with pytest.raises(HTTPException) as exc:
        bs.guard(req)
    assert exc.value.status_code == 421


def test_guard_无会话返回401(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setenv("AGENT_DESKTOP", "1")
    monkeypatch.setenv("AGENT_DESKTOP_TOKEN", "tok-123")
    req = _request({"host": f"127.0.0.1:{_PORT}"})
    with pytest.raises(HTTPException) as exc:
        bs.guard(req)
    assert exc.value.status_code == 401


def test_guard_非桌面模式直接放行(monkeypatch):
    monkeypatch.setenv("AGENT_DESKTOP", "0")
    req = _request({"host": f"evil.com:{_PORT}"})
    bs.guard(req)  # 不抛异常即通过
