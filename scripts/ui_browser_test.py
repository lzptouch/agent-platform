"""浏览器端到端测试 + 截图（Playwright headless Chromium）。

覆盖场景：
1. 对话模式：发消息 → 真实回答 → 截图
2. 会话抽屉：会话列表 → 截图
3. 工作模式：plan_first → 审批卡片 → 确认执行 → 完成 → 截图 ×3
4. 团队页：列表 + 预览 → 截图 ×2
5. 定时任务页：列表 + 新建抽屉 → 截图 ×2
6. Skill 管理页：含启停用开关 → 截图
"""
from __future__ import annotations

import os

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

# **E9**：此前硬编码 8000，而 backend/.env 是 18040 → 按现状运行必然全部失败。
# 改为读环境变量（与 backend/scripts/ui_smoke_test.py 的 AP_UI_BASE_URL 一致）。
BASE = os.getenv("AP_UI_BASE_URL", "http://127.0.0.1:18040")
SHOT_DIR = Path(__file__).resolve().parent.parent / "doc" / "workbuddy" / "screenshots"
SHOT_DIR.mkdir(parents=True, exist_ok=True)

passed: list[str] = []
failed: list[tuple[str, str]] = []


def shot(page, name: str) -> None:
    page.screenshot(path=str(SHOT_DIR / f"{name}.png"), full_page=False)
    print(f"[shot] {name}.png")


def step(name: str, fn) -> None:
    try:
        fn()
        passed.append(name)
        print(f"[PASS] {name}")
    except Exception as exc:  # noqa: BLE001
        failed.append((name, str(exc)))
        print(f"[FAIL] {name}: {exc}")


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        # ---------- 1. 对话模式 ----------
        def _chat():
            page.goto(f"{BASE}/chat")
            page.wait_for_selector(".chat-view", timeout=10000)
            shot(page, "01_chat_empty")
            # 发送消息
            page.fill(".chat-input textarea", "你好，用一句话介绍你自己")
            page.click(".input-actions button:has-text('发送')")
            # 等待回答完成（完成标记或等待文本出现）
            page.wait_for_selector(".status-done", timeout=60000)
            time.sleep(0.5)
            shot(page, "02_chat_answer")
            assert page.locator(".assistant-msg .texts").count() > 0

        step("对话模式：发送并收到回答", _chat)

        # ---------- 2. 会话抽屉 ----------
        def _drawer():
            page.click("button:has-text('会话')")
            page.wait_for_selector(".el-drawer", timeout=5000)
            page.wait_for_selector(".session-item", timeout=5000)
            shot(page, "03_session_drawer")

        step("会话抽屉：历史会话列表", _drawer)

        # ---------- 3. 工作模式 + Plan 审批 ----------
        def _work():
            # 抽屉可能还开着，先关闭
            page.keyboard.press("Escape")
            page.click(".el-segmented__item:has-text('工作模式')")
            page.wait_for_selector(".work-view", timeout=10000)
            shot(page, "04_work_empty")
            # 发送 plan_first 任务（文件名带时间戳，避免与历史产物重名）
            fname = f"sea_{int(time.time())}.txt"
            page.check("text=先规划后执行（Plan）")
            page.fill(".work-input textarea", f"写一句关于大海的话并保存为 {fname}")
            page.click(".input-actions button:has-text('执行')")
            page.wait_for_selector(".approval-card", timeout=60000)
            shot(page, "05_work_plan_approval")

        step("工作模式：Plan 审批卡片出现", _work)

        def _approve():
            page.click(".plan-actions button:has-text('确认执行')")
            # 等待执行完成（DB tail SSE 回放）
            page.wait_for_selector(".status-done", timeout=120000)
            time.sleep(0.5)
            shot(page, "06_work_done")
            # 产物文件 chip 应出现
            assert page.locator(".file-chip").count() > 0, "应出现产物文件"

        step("工作模式：批准后执行完成并产出文件", _approve)

        # ---------- 4. 团队页 ----------
        def _teams():
            page.goto(f"{BASE}/teams")
            page.wait_for_selector(".teams-view table", timeout=10000)
            shot(page, "07_teams_list")

        step("团队页：列表渲染", _teams)

        def _team_preview():
            page.click("button:has-text('预览')")
            page.wait_for_selector(".el-dialog", timeout=10000)
            shot(page, "08_team_preview")
            page.keyboard.press("Escape")

        step("团队页：resolve 预览", _team_preview)

        # ---------- 5. 定时任务页 ----------
        def _schedules():
            page.goto(f"{BASE}/schedules")
            page.wait_for_selector(".schedules-view table", timeout=10000)
            shot(page, "09_schedules_list")

        step("定时任务页：列表渲染", _schedules)

        def _schedule_drawer():
            page.click("button:has-text('新建任务')")
            page.wait_for_selector(".el-drawer", timeout=5000)
            # cron 校验预览
            page.click(".el-radio:has-text('cron 表达式')")
            page.fill(".el-drawer input[placeholder*='每天 09:00']", "0 9 * * *")
            time.sleep(1.2)
            shot(page, "10_schedule_create")
            page.keyboard.press("Escape")

        step("定时任务页：新建抽屉 + cron 预览", _schedule_drawer)

        def _schedule_runs():
            page.goto(f"{BASE}/schedules")
            page.wait_for_selector(".schedules-view table", timeout=10000)
            # 展开第一行运行历史
            page.locator(".el-table__expand-icon").first.click()
            page.wait_for_selector(".run-history table", timeout=10000)
            time.sleep(0.5)
            shot(page, "11_schedule_runs")

        step("定时任务页：运行历史展开", _schedule_runs)

        # ---------- 6. Skill 管理 ----------
        def _skills():
            page.goto(f"{BASE}/skills")
            page.wait_for_selector(".skill-table", timeout=10000)
            shot(page, "12_skills")

        step("Skill 管理页：含启停用开关与内置标签", _skills)

        browser.close()

    print("\n===== 结果 =====")
    print(f"通过 {len(passed)} / {len(passed) + len(failed)}")
    for name, err in failed:
        print(f"  FAIL {name}: {err}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
