"""`tests/` 的全局钩子（P5-03 · 分层 marker 自动打标）。

**改造要点（design/16 §11.10 · P8-04）**：旧 Python 后端（`backend/`）已退场，
本目录不再需要把 `backend/` 加进 `sys.path`，也不再提供基于 `starlette` 的
`client` fixture —— **保留的用例全部走「真实进程 + HTTP / Playwright」**，
不依赖任何后端内部导入。

**为什么自动打标**：用例分散在 `desktop/` `packaged/` `visual/` 三个目录里，
逐个文件加 ``@pytest.mark.xxx`` 会漏、也会与目录语义脱节。这里按**目录**兜底
打标，保证：

- ``pytest -m unit`` 只跑单元测试（不含 e2e）；
- ``pytest -m e2e`` 只跑端到端；
- **无未打标用例**（每个用例至少有一个层标记）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

#: 仓库根（让 ``common.*`` 可被导入）。
REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT / "tests"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)


#: 目录 → 层标记
_DIR_MARKERS: dict[str, str] = {
    "desktop": "e2e",
    "packaged": "e2e",
    "visual": "e2e",
}

#: 文件名特征 → 额外标记
_NAME_MARKERS: list[tuple[str, str]] = [
    ("live_", "real_llm"),
    ("real_llm", "real_llm"),
    ("research", "slow"),
    ("orchestration", "slow"),
    ("p2_batch", "slow"),
    ("p3_batch", "slow"),
]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """按目录/文件名给每个用例打层标记（兜底：保证无未打标用例）。"""
    for item in items:
        path = Path(str(item.fspath))
        parts = set(path.parts)
        markers = {m for d, m in _DIR_MARKERS.items() if d in parts}
        name = path.stem.lower()
        for token, marker in _NAME_MARKERS:
            if token in name:
                markers.add(marker)
        if not markers:
            markers.add("integration")
        for marker in sorted(markers):
            item.add_marker(getattr(pytest.mark, marker))
