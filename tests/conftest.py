"""`tests/` 的全局钩子（P5-03 · 分层 marker 自动打标）。

**为什么自动打标**：用例分散在 `web/` `desktop/` `packaged/` `native/` `deploy/` `visual/`
六个目录里，逐个文件加 ``@pytest.mark.xxx`` 会漏、也会与目录语义脱节。
这里按**目录**兜底打标，保证：

- ``pytest -m unit`` 只跑单元测试（不含 e2e）；
- ``pytest -m e2e`` 只跑端到端；
- **无未打标用例**（每个用例至少有一个层标记）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

#: 让 ``app.*``（后端包）可被导入——本目录的测试从**仓库根**运行，
#: 与 backend/tests 的导入路径不同。
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
for _p in (str(BACKEND_ROOT), str(REPO_ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture()
def client():
    """TestClient（触发 app lifespan → 迁移 + 应用状态初始化）。"""
    from starlette.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c

#: 目录 → 层标记
_DIR_MARKERS: dict[str, str] = {
    "web": "e2e",
    "desktop": "e2e",
    "packaged": "e2e",
    "native": "e2e",
    "deploy": "e2e",
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
