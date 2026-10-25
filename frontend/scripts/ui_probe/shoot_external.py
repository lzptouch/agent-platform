"""抓取 Trae / WorkBuddy 官网与社区页面的截图与文本，作为目标形态参考资料。"""
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path("/tmp/agent_ui_probe/reference")
OUT.mkdir(parents=True, exist_ok=True)

TARGETS = [
    ("trae_home", "https://www.trae.cn/", 2400),
    ("trae_work", "https://www.trae.cn/work", 2400),
    ("workbuddy_home", "https://www.workbuddy.cn/", 2400),
    ("trae_forum_solo", "https://forum.trae.cn/t/topic/53", 2400),
    ("trae_forum_advance", "https://forum.trae.cn/t/topic/12954", 2400),
]


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
        )
        for name, url, wait in TARGETS:
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            except Exception as exc:  # noqa: BLE001
                print(f"[goto-fail] {name} {url}: {exc}")
                await page.close()
                continue
            await page.wait_for_timeout(wait)
            await page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)
            try:
                text = await page.evaluate("() => document.body.innerText")
            except Exception:  # noqa: BLE001
                text = ""
            (OUT / f"{name}.txt").write_text(text, encoding="utf-8")
            # 抓取页面图片 URL（便于定位 UI 截图素材）
            imgs = await page.evaluate(
                "() => [...document.querySelectorAll('img')].map(i=>i.src).filter(s=>s&&s.startsWith('http')).slice(0,40)"
            )
            (OUT / f"{name}_imgs.txt").write_text("\n".join(imgs), encoding="utf-8")
            print(f"[ok] {name} text_len={len(text)} imgs={len(imgs)}")
            await page.close()
        await browser.close()


asyncio.run(main())
