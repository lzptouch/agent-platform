"""桌面端 sidecar 启动器。

职责：

1. **自绑 loopback 套接字**（``bind(("127.0.0.1", 0))``）——端口由 OS 分配，
   消除「壳先占端口再关闭、后端再绑定」的 TOCTOU 竞态；
2. **打印一行握手**：``AGENT_DESKTOP_READY {json}``，壳据此拿到真实端口与路径；
3. 以 uvicorn 的「预绑定套接字」方式启动应用。

用法（壳 spawn 时）::

    python -m app.desktop.launcher

环境变量（由壳注入）：

``AGENT_DESKTOP=1``
    开启桌面模式（会话令牌 / Host 白名单 / CORS 收窄）。
``AGENT_DESKTOP_TOKEN``
    常驻会话令牌。
``AGENT_DESKTOP_BOOTSTRAP_NONCE``
    一次性引导 nonce。
``AGENT_DATA_DIR``
    可写数据根（UserData）。
``AGENT_FRONTEND_DIST``
    前端构建产物目录。
"""
from __future__ import annotations

import json
import logging
import os
import socket
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

HANDSHAKE_PREFIX = "AGENT_DESKTOP_READY "
BIND_RETRIES = 5
BIND_RETRY_DELAY = 0.1

#: uvicorn 日志统一走 stderr，保证 stdout 只有握手行可解析
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s"},
    },
    "handlers": {
        "stderr": {"class": "logging.StreamHandler", "stream": "ext://sys.stderr"},
    },
    "root": {"handlers": ["stderr"], "level": "INFO"},
    "loggers": {
        "uvicorn": {"handlers": ["stderr"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"handlers": ["stderr"], "level": "INFO", "propagate": False},
        "uvicorn.access": {"handlers": ["stderr"], "level": "WARNING", "propagate": False},
    },
}


def bind_loopback(retries: int = BIND_RETRIES) -> socket.socket:
    """绑定一个由 OS 分配端口的 loopback 套接字。"""
    last_error: OSError | None = None
    for attempt in range(retries):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", 0))
            sock.listen(2048)
            return sock
        except OSError as exc:  # pragma: no cover - 极小概率
            last_error = exc
            sock.close()
            logger.warning("绑定本地端口失败（第 %s 次）：%s", attempt + 1, exc)
            time.sleep(BIND_RETRY_DELAY)
    raise RuntimeError(f"无法绑定本地端口（重试 {retries} 次）：{last_error}")


def build_handshake(port: int) -> dict:
    """组装握手载荷。

    **不含令牌**——令牌由壳生成后经环境变量注入，后端无需也不应回显，
    否则令牌会随后端 stdout 落入壳的日志文件。
    """
    from app.core.config import settings

    return {
        "protocol": settings.desktop_protocol,
        "port": port,
        "pid": os.getpid(),
        "data_dir": str(settings.user_data_dir),
        "workspace_dir": str(settings.default_workspace_dir),
        "app_version": settings.app_name,
        "backend_version": settings.app_version,
        "started_at": _utc_now(),
    }


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


#: uvicorn Server 实例引用（供优雅退出端点使用）
_server_ref: dict[str, object] = {"server": None}


def set_server(server: object) -> None:
    _server_ref["server"] = server


def get_server() -> object | None:
    return _server_ref.get("server")


def request_shutdown() -> bool:
    """请求 uvicorn 优雅退出。返回是否成功（未在桌面 sidecar 中时为 False）。"""
    server = _server_ref.get("server")
    if server is None:
        return False
    setattr(server, "should_exit", True)
    return True


def main() -> int:
    """启动 sidecar。"""
    import uvicorn

    from app.core.config import settings
    from app.main import app

    if not settings.desktop_mode:
        logger.warning("AGENT_DESKTOP 未开启，以普通模式启动（桌面握手仍可用）")

    sock = bind_loopback()
    port = int(sock.getsockname()[1])
    settings.port = port

    config = uvicorn.Config(
        app,
        # P1-10：桌面端的绑定地址**由 bind_loopback() 决定**（必须回环——
        # 桌面形态不对外暴露端口）。此处**不写** host 字面量：uvicorn 在
        # ``server.run(sockets=[sock])`` 下会忽略 host/port，写一个看似可配的
        # 字面量只会让人误以为改 settings.host 能改变桌面端绑定（实际不生效）。
        port=port,
        log_config=LOGGING_CONFIG,
        access_log=False,
    )
    server = uvicorn.Server(config)
    set_server(server)

    logger.info("桌面 sidecar 启动：127.0.0.1:%s（pid=%s）", port, os.getpid())
    print(HANDSHAKE_PREFIX + json.dumps(build_handshake(port), ensure_ascii=False), flush=True)

    server.run(sockets=[sock])
    return 0


if __name__ == "__main__":  # pragma: no cover - 进程入口
    sys.exit(main())
