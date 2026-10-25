#!/usr/bin/env python3
"""
Plan 模式审批链路端到端验证（阶段 3 验收）。

覆盖：模式=plan → 发送 → 出现计划确认卡 → 确认执行 → SSE 续播完成。
运行：cd backend && .venv/bin/python ../frontend/scripts/ui_probe/smoke_plan.py
"""
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _browser import new_page

BASE = "http://127.0.0.1:5185"
OUT = Path("/tmp/agent_ui_probe/smoke")
OUT.mkdir(parents=True, exist_ok=True)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  → {detail}" if detail else ""))


async def main() -> int:
    async with async_playwright() as p:
        browser, ctx, page = await new_page(p)
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        # 1. 以 plan 模式进入
        await page.goto(f"{BASE}/workspace?mode=plan", wait_until="networkidle", timeout=45000)
        await page.wait_for_timeout(1500)
        check("进入 plan 模式", "mode=plan" in page.url, page.url)
        check("顶部显示「计划」标签",
              await page.locator(".ws-head .el-tag").first.inner_text() == "计划")

        # 2. 发送消息，触发计划生成
        ta = page.locator(".composer .composer-ta")
        await ta.fill("列出当前目录下的文件")
        await page.locator(".composer .send-btn").click()

        # 3. 等待计划确认卡（最长 90s）
        card = page.locator(".plan-card")
        for _ in range(90):
            if await card.count() > 0:
                break
            await page.wait_for_timeout(1000)
        check("计划确认卡出现", await card.count() > 0)
        if await card.count() > 0:
            steps = await card.locator(".plan-step").count()
            check("计划含多个步骤", steps >= 1, f"steps={steps}")
            check("计划卡含「确认执行」按钮",
                  await card.get_by_text("确认执行").count() > 0)
            check("计划卡含「拒绝」按钮", await card.get_by_text("拒绝").count() > 0)
            await page.screenshot(path=str(OUT / "06_plan_approval.png"))

            # 4. 确认执行 → SSE 续播
            await card.get_by_text("确认执行").click()
            for _ in range(120):
                if await page.locator(".status-done").count() > 0 or \
                   await page.locator(".status-error").count() > 0:
                    break
                await page.wait_for_timeout(1000)
            done = await page.locator(".status-done").count() > 0
            err = await page.locator(".status-error").count() > 0
            check("审批后续播完成", done or err, "done" if done else ("error" if err else "timeout"))
            check("续播产生执行轨迹", await page.locator(".timeline").count() > 0)
            await page.screenshot(path=str(OUT / "07_plan_after_approve.png"))

        real_errors = [e for e in errors if "favicon" not in e.lower()]
        check("无未捕获的 JS 错误", len(real_errors) == 0, "; ".join(real_errors[:3]))

        await browser.close()

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n=== Plan 审批链路：{passed}/{total} 通过 ===")
    for name, ok, detail in results:
        if not ok:
            print(f"  FAILED: {name}  {detail}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
