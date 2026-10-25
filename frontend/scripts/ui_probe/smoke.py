#!/usr/bin/env python3
"""
v3 工作台端到端冒烟（阶段 0 / 1 / 2 / 3 验收）。

依赖：backend/.venv 内已安装的 playwright + chromium。
运行：cd backend && .venv/bin/python ../frontend/scripts/ui_probe/smoke.py
"""
import asyncio
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _browser import new_page

# BASE 可用环境变量覆盖：5185=开发形态(Vite)，18040=单端口形态(后端托管 dist)
BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5185")
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
        page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}")
                if m.type == "error" else None)

        # ---------- 1. 根路径重定向到工作台 ----------
        await page.goto(BASE, wait_until="networkidle", timeout=45000)
        await page.wait_for_timeout(1200)
        check("根路径重定向到 /workspace", "/workspace" in page.url, page.url)

        # ---------- 2. 侧栏结构 ----------
        check("左侧栏存在", await page.locator("aside.sidenav").count() > 0)
        check("左栏含「新建任务」入口",
              await page.locator("aside.sidenav").get_by_text("新建任务").count() > 0)
        check("左栏含「任务 (N)」分组",
              await page.locator("aside.sidenav").get_by_text("任务 (").count() > 0)
        check("左栏含账号区", await page.locator("aside.sidenav .account").count() > 0)

        # ---------- 3. 空态 hero + 场景/能力 Chip ----------
        check("空态大标题存在", await page.locator("h1.hero").count() > 0,
              (await page.locator("h1.hero").first.inner_text()) if await page.locator("h1.hero").count() else "")
        check("场景 Chip 存在（日报办公）",
              await page.locator(".chip.scene").count() >= 3,
              f"count={await page.locator('.chip.scene').count()}")
        check("能力 Chip 存在（RAG）",
              await page.get_by_text("知识库检索").count() > 0)

        # ---------- 4. 输入区 ----------
        ta = page.locator(".composer .composer-ta")
        check("输入框存在", await ta.count() > 0)
        ph = await ta.get_attribute("placeholder") if await ta.count() else ""
        check("占位符含 @ 与 /", "@" in (ph or "") and "/" in (ph or ""), ph or "")
        check("输入框右下有模式切换器", await page.locator(".composer .switcher").count() > 0)
        check("圆形发送按钮存在", await page.locator(".composer .send-btn").count() > 0)
        check("框外工具条（工作空间/权限）存在",
              await page.locator(".context-bar").count() > 0)

        # ---------- 5. 模式切换（Ask/Plan/Craft）----------
        await page.locator(".composer .switcher").click()
        await page.wait_for_timeout(500)
        check("模式菜单含 计划 Plan", await page.get_by_text("计划 Plan").count() > 0)
        await page.get_by_text("计划 Plan").click()
        await page.wait_for_timeout(600)
        check("切换后 URL 带 mode=plan", "mode=plan" in page.url, page.url)
        await page.locator(".composer .switcher").click()
        await page.wait_for_timeout(400)
        await page.get_by_text("对话 Ask").click()
        await page.wait_for_timeout(500)
        check("切回 mode=chat", "mode=chat" in page.url, page.url)

        # ---------- 6. "/" 命令面板 ----------
        await ta.click()
        await ta.type("/")
        await page.wait_for_timeout(700)
        check("命令面板已打开", await page.locator(".cmd-dialog").count() > 0)
        check("命令面板含「深度研究」", await page.get_by_text("发起深度研究").count() > 0)
        await page.screenshot(path=str(OUT / "01_command_palette.png"))
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(400)

        # ---------- 7. "@" 上下文选择 ----------
        await ta.click()
        await ta.type("@")
        await page.wait_for_timeout(700)
        check("上下文选择面板已打开", await page.locator(".at-dialog").count() > 0)
        await page.screenshot(path=str(OUT / "02_at_picker.png"))
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(400)

        # ---------- 8. 发送一条消息（真实流式）----------
        await ta.fill("用一句话介绍你能做什么")
        await page.locator(".composer .send-btn").click()
        await page.wait_for_timeout(2500)
        check("用户气泡已渲染", await page.locator(".user-bubble").count() > 0)
        has_assistant = await page.locator(".assistant-msg").count() > 0
        check("助手消息已渲染", has_assistant)
        await page.screenshot(path=str(OUT / "03_after_send.png"))
        # 等待流式结束（最长 90s）
        for _ in range(90):
            if await page.locator(".status-done").count() > 0 or await page.locator(".status-error").count() > 0:
                break
            await page.wait_for_timeout(1000)
        done = await page.locator(".status-done").count() > 0
        err = await page.locator(".status-error").count() > 0
        check("流式执行完成（有完成或错误标记）", done or err,
              "done" if done else ("error" if err else "timeout"))

        # ---------- 9. 执行轨迹 ----------
        check("执行轨迹区存在", await page.locator(".timeline").count() > 0)

        # ---------- 10. 旧路径保留 ----------
        await page.goto(f"{BASE}/skills", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(900)
        check("旧路径 /skills → /admin/capabilities?tab=skills",
              "/admin/capabilities" in page.url and "tab=skills" in page.url, page.url)
        check("合并页含 三个 Tab",
              await page.get_by_text("连接器（MCP）").count() > 0)
        await page.screenshot(path=str(OUT / "04_admin_capabilities.png"))

        await page.goto(f"{BASE}/chat", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(900)
        check("旧路径 /chat 仍可访问", "/chat" in page.url, page.url)
        await page.screenshot(path=str(OUT / "05_legacy_chat.png"))

        # ---------- 11. 灰度开关回退 ----------
        await page.goto(BASE, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(600)
        await page.locator("aside.sidenav .icon-btn.on").click()
        await page.wait_for_timeout(500)
        await page.goto(BASE, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(800)
        check("关闭 v3 开关后根路径回退到 /chat", "/chat" in page.url, page.url)
        # 恢复开启
        await page.evaluate("localStorage.setItem('__ws_v3','1')")

        # ---------- 12. 无 JS 运行时错误 ----------
        real_errors = [e for e in errors if "favicon" not in e.lower()]
        check("无未捕获的 JS 错误", len(real_errors) == 0, "; ".join(real_errors[:3]))

        await browser.close()

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n=== 冒烟结果：{passed}/{total} 通过 ===")
    for name, ok, detail in results:
        if not ok:
            print(f"  FAILED: {name}  {detail}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
