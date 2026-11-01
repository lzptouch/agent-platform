"""对本地运行中的前端页面批量截图，用于与目标形态（WorkBuddy / Trae 工作版）对比分析。"""
import asyncio
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:5185")
OUT = Path(os.environ.get("OUT_DIR", "/tmp/agent_ui_probe/shots"))
OUT.mkdir(parents=True, exist_ok=True)

PAGES = [
    ("01_chat", "/chat"),
    ("02_work", "/work"),
    ("03_teams", "/teams"),
    ("04_schedules", "/schedules"),
    ("05_skills", "/skills"),
    ("06_research", "/research"),
    ("07_mcp", "/mcp"),
    ("08_rag", "/rag"),
    ("09_web", "/web"),
    ("10_files", "/files"),
    ("11_wr", "/wr"),
    ("12_status", "/status"),
    ("13_settings", "/settings"),
]


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()
        errors = []
        page.on("console", lambda m: errors.append(f"[console.{m.type}] {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"[pageerror] {e}"))

        for name, path in PAGES:
            url = BASE + path
            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"[goto] {url} {exc}")
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2500)
            await page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)
            # 记录页面结构特征
            info = await page.evaluate(
                """() => {
                    const navs = [...document.querySelectorAll('.el-menu-item, .el-sub-menu__title, nav a, aside a')]
                        .map(e => (e.textContent || '').trim()).filter(Boolean);
                    const btns = [...document.querySelectorAll('button, .el-button')]
                        .map(e => (e.textContent || '').trim()).filter(Boolean);
                    const inputs = [...document.querySelectorAll('textarea, input[type=text], .el-input__inner')]
                        .map(e => e.getAttribute('placeholder') || e.tagName);
                    return {
                        title: document.title,
                        navs: [...new Set(navs)],
                        buttons: [...new Set(btns)].slice(0, 40),
                        inputs: [...new Set(inputs)].slice(0, 10),
                        hasSidebar: !!document.querySelector('.el-aside, aside, .sidebar'),
                        bodyLen: document.body.innerText.length,
                    };
                }"""
            )
            print(f"=== {name} ({path}) ===")
            print(info)
            print()

        print("--- console/page errors ---")
        for e in errors[:40]:
            print(e)
        await browser.close()


asyncio.run(main())
sys.exit(0)
