#!/usr/bin/env python3
"""
浏览器启动器（供 smoke / smoke_plan / func_test 共用）。

策略：
  1. 优先使用 Playwright 自带 Chromium（headless shell）；
  2. 自带版本缺失或与缓存 revision 不匹配时，回退系统已安装的 Google Chrome。

避免因 Playwright 包版本与已缓存浏览器 revision 不一致导致整条测试链无法运行。
"""
from __future__ import annotations

from playwright.async_api import async_playwright

CHANNELS = ("chrome", "msedge", "chromium")


async def launch_browser(p):
    """返回一个可用的 Browser 实例。"""
    try:
        return await p.chromium.launch(headless=True)
    except Exception as first_err:  # noqa: BLE001
        last = first_err
        for ch in CHANNELS:
            try:
                return await p.chromium.launch(headless=True, channel=ch)
            except Exception as e:  # noqa: BLE001
                last = e
        raise RuntimeError(f"无可用浏览器（内置 Chromium 与系统浏览器均失败）：{last}") from last


async def new_page(p, *, viewport: dict | None = None, locale: str = "zh-CN"):
    """新建浏览器 + 上下文 + 页面。"""
    browser = await launch_browser(p)
    ctx = await browser.new_context(viewport=viewport or {"width": 1600, "height": 1000}, locale=locale)
    return browser, ctx, await ctx.new_page()


if __name__ == "__main__":
    import asyncio

    async def _probe() -> None:
        async with async_playwright() as p:
            b = await launch_browser(p)
            print("browser ok:", b.browser_type.name, b.version)
            await b.close()

    asyncio.run(_probe())
