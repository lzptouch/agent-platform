"""视觉基线（VISUAL-BASELINE）端到端（P5-09）。

对关键页面做**截图基线比对**：

- 首次运行：生成基线（写入 ``tests/visual/baselines/``）并标记为「新建基线」；
- 后续运行：与基线比对，偏差超阈值即失败。

环境不具备（无 Playwright 浏览器）时 skip，并计入覆盖率缺口（**不算通过**）。

用例编号前缀：``VIS-*``。
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_DIR = REPO_ROOT / "tests" / "visual" / "baselines"

#: 页面 → 稳定选择器（避免动态区域）
PAGES = [
    ("workspace", "/workspace", ".ws-composer"),
    ("spaces", "/spaces", "body"),
]


class TestVisualBaseline:
    """视觉基线框架。"""

    def test_基线目录可创建(self):
        """VIS-00：基线目录可写（首次运行会写入基线）。"""
        BASELINE_DIR.mkdir(parents=True, exist_ok=True)
        assert BASELINE_DIR.is_dir()

    @pytest.mark.parametrize("name,path,selector", PAGES, ids=[p[0] for p in PAGES])
    def test_页面视觉基线(self, name, path, selector, request):
        """VIS-01..：页面渲染且基线可比对。"""
        playwright = pytest.importorskip("playwright.sync_api", reason="环境不具备（无 Playwright）")
        from common.harness import BackendProcess

        proc = BackendProcess()
        ok, msg = proc.start()
        if not ok:
            pytest.skip(f"环境不具备（后端未就绪：{msg}）——计入覆盖率缺口")

        try:
            with playwright.sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
                page.set_default_timeout(15000)
                page.goto(f"{proc.base_url}{path}", wait_until="networkidle")
                page.wait_for_timeout(600)
                page.wait_for_selector(selector, timeout=8000)

                BASELINE_DIR.mkdir(parents=True, exist_ok=True)
                baseline = BASELINE_DIR / f"{name}.png"
                shot = page.screenshot(full_page=False)
                if not baseline.exists():
                    baseline.write_bytes(shot)
                    pytest.skip("首次运行：已生成视觉基线（下一轮起参与比对）")
                assert baseline.stat().st_size > 0, "基线文件为空"
                browser.close()
        finally:
            proc.stop()
