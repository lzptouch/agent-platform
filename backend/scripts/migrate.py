"""数据库迁移入口：``python -m scripts.migrate``。

幂等；失败返回非零退出码（容器 entrypoint 据此中止启动，不静默降级）。
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def main() -> int:
    from alembic import command
    from alembic.config import Config

    from app.core.config import settings

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "app" / "db" / "migrations"))
    # **E11**：此前打印**完整**数据库 URL —— 切到 PostgreSQL 后口令会明文进 docker logs。
    _safe = settings.database_url_abs
    try:
        from sqlalchemy.engine import make_url

        _safe = make_url(settings.database_url_abs).render_as_string(hide_password=True)
    except Exception:  # noqa: BLE001 —— 脱敏失败也要继续（不能因日志而中断迁移）
        pass
    print(f"[migrate] database: {_safe}")
    command.upgrade(cfg, "head")
    print("[migrate] upgrade head ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
