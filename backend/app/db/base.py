"""数据库连接基座。

- 默认 SQLite（WAL 模式），可通过 ``DATABASE_URL`` 切换 PostgreSQL。
- 全项目复用同一个 engine；Session 按线程/请求创建，**不跨线程共享**。
- 测试通过 ``configure_engine()`` 指向临时库，``reset_engine()`` 复位。
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, TypeVar

from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.pool import NullPool

from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _create_engine(url: str) -> Engine:
    kwargs: dict[str, Any] = {"echo": settings.db_echo, "pool_pre_ping": True, "future": True}
    if _is_sqlite(url):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine = create_engine_wrapper(url, **kwargs)

    if _is_sqlite(url):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _record):  # noqa: ANN001, ANN202
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine


def create_engine_wrapper(url: str, **kwargs) -> Engine:
    """独立函数便于测试替换。"""
    from sqlalchemy import create_engine

    if _is_sqlite(url) and ":memory:" in url:
        # 内存库在多线程下会各自独立；使用 NullPool 无济于事，这里强制单连接共享
        from sqlalchemy.pool import StaticPool

        kwargs["poolclass"] = StaticPool
    return create_engine(url, **kwargs)


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = _create_engine(settings.database_url_abs)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_session_factory() -> sessionmaker:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def configure_engine(url: str) -> Engine:
    """重建 engine（测试用：指向临时 SQLite 文件）。"""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = _create_engine(url)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def reset_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


@contextmanager
def db_session() -> Iterator[Session]:
    """短事务上下文：commit / rollback / close。"""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def retry_on_locked(fn: Callable[[], T], attempts: int = 3) -> T:
    """SQLite 写锁 / 乐观锁冲突重试：指数退避 50/100/200ms。

    **W2-03**：此前只捕获 ``OperationalError``（且只认文本里含 "locked"）→
    乐观锁版本冲突抛的 ``StaleDataError`` **直接冒泡** → 端点返回 500。
    现在一并捕获并重试（重试会重新取行、拿到新版本）。
    """
    delay = 0.05
    for i in range(attempts):
        try:
            return fn()
        except StaleDataError:
            # 乐观锁版本冲突：重试（``fn`` 内部会重新读行）
            if i < attempts - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
        except OperationalError as exc:
            if "locked" in str(exc).lower() and i < attempts - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise RuntimeError("unreachable")


def init_db() -> None:
    """开发兜底：确保表存在（生产走 Alembic 迁移）。"""
    from app.db import models  # noqa: F401 - 注册表

    models.Base.metadata.create_all(get_engine())


def check_db() -> bool:
    try:
        with db_session() as db:
            db.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("数据库不可用")
        return False
