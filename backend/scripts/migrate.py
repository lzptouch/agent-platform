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
    print(f"[migrate] database: {settings.database_url_abs}")
    command.upgrade(cfg, "head")
    print("[migrate] upgrade head ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
