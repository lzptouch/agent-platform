"""agent 前后端联调测试（Playwright）。

用法::

    .venv/bin/python -m scripts.ui_smoke_test          # 需先启动后端 :8000

环境变量::

    AP_UI_SHOT_DIR   截图输出目录（默认 /tmp/ap-shots）
    AP_UI_BASE_URL   被测地址（默认 http://127.0.0.1:8000/）

覆盖：
1. 聊天视图加载 + Skill 多选控件
2. 截获 /agent/run 请求，断言 skills 字段随选择变化（不触发真实 LLM）
3. 深度研究 Tab 切换 + 无检索 Key 的提示条
4. 提交研究任务 → 快速失败提示
5. 研究任务列表 + 详情/进度渲染
"""
from __future__ import annotations

import json
import re
import sys

from playwright.sync_api import sync_playwright

import os

BASE = os.getenv("AP_UI_BASE_URL", "http://127.0.0.1:8000/")
SHOT = os.getenv("AP_UI_SHOT_DIR", "/tmp/ap-shots")
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"  {'✅' if ok else '❌'} {name}" + (f"  [{detail}]" if detail else ""))


def main() -> int:
    import pathlib

    pathlib.Path(SHOT).mkdir(exist_ok=True)
    captured: dict = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        # ---------- 截获 /agent/run，避免真实 LLM 调用 ----------
        def handle_agent_run(route):
            try:
                captured["agent_payload"] = json.loads(route.request.post_data or "{}")
            except Exception as exc:  # noqa: BLE001
                captured["agent_payload"] = {"_error": str(exc)}
            body = "\n\n".join([
                'data: {"type":"skills_selected","skills":'
                + json.dumps(captured["agent_payload"].get("skills") or [])
                + ',"all_skills":["data-analysis","frontend-design","marketing-materials","pdf","ralph-loop","skill-creator"],"total":6}',
                'data: {"type":"system_prompt","content":"(mocked system prompt)"}',
                'data: {"type":"user_input","content":"mock"}',
                'data: {"type":"round_start","round":1}',
                'data: {"type":"model_text","content":"**联调测试回复**：已收到请求。"}',
                'data: {"type":"files","files":[]}',
                'data: {"type":"done"}',
            ]) + "\n\n"
            route.fulfill(status=200, headers={"Content-Type": "text/event-stream"}, body=body)

        page.route("**/api/v1/agent/run", handle_agent_run)

        # ============ 1. 加载首页 ============
        print("\n[1] 加载首页")
        page.goto(BASE, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1200)
        page.screenshot(path=f"{SHOT}/01-chat-view.png", full_page=True)

        check("页面标题正确", "agent" in page.title() or "Agent" in page.title(), page.title())
        check("侧边栏模式 Tab 存在", page.locator(".mode-tab").count() == 2,
              f"{page.locator('.mode-tab').count()} 个")

        # ============ 2. Skill 多选 ============
        print("\n[2] Skill 多选控件")
        chips = page.locator(".skill-chip")
        n_chips = chips.count()
        check("Skill chip 渲染", n_chips == 6, f"{n_chips} 个")
        check("每个 chip 带 checkbox", page.locator(".skill-chip input[type=checkbox]").count() == 6)

        count_text = page.locator(".skill-count").inner_text()
        check("默认全选（计数 6/6）", count_text.strip() == "6/6", count_text)

        # 清空
        page.locator(".skill-action", has_text="清空").click()
        page.wait_for_timeout(300)
        count_text = page.locator(".skill-count").inner_text()
        check("清空后计数 0/6", count_text.strip() == "0/6", count_text)

        # 选中 pdf + data-analysis（直接操作 checkbox）
        boxes = page.locator(".skill-chip input[type=checkbox]")
        names = [chips.nth(i).inner_text().strip() for i in range(n_chips)]
        idx_pdf = names.index("pdf") if "pdf" in names else 3
        idx_da = names.index("data-analysis") if "data-analysis" in names else 0
        boxes.nth(idx_pdf).check()
        page.wait_for_timeout(150)
        boxes.nth(idx_da).check()
        page.wait_for_timeout(300)
        count_text = page.locator(".skill-count").inner_text()
        check("选中 2 个后计数 2/6", count_text.strip() == "2/6", count_text)

        # 「?」按钮打开 SKILL.md 弹窗
        page.locator(".skill-chip-info").first.click()
        page.wait_for_timeout(900)
        modal_ok = page.locator(".modal-mask").count() > 0
        check("「?」打开 SKILL.md 弹窗", modal_ok)
        if modal_ok:
            page.locator(".modal-close").click()
            page.wait_for_timeout(400)
        # 弹窗关闭后，选中数应保持不变
        check("弹窗不影响选中状态", page.locator(".skill-count").inner_text().strip() == "2/6",
              page.locator(".skill-count").inner_text())
        page.screenshot(path=f"{SHOT}/02-skill-selection.png", full_page=True)

        # ============ 3. 发送消息，断言请求 payload ============
        print("\n[3] 发送消息（截获请求验证 skills 字段）")
        page.locator(".input-box textarea").fill("联调测试：请回复确认")
        page.locator(".send-btn").click()
        page.wait_for_timeout(2500)

        payload = captured.get("agent_payload", {})
        sel = payload.get("skills")
        check("请求携带 skills 字段", sel is not None, json.dumps(payload, ensure_ascii=False)[:160])
        check("skills 只含选中项（2 个）", isinstance(sel, list) and len(sel) == 2 and "pdf" in sel, str(sel))

        # 消息区显示 Skill 标签
        page.wait_for_timeout(600)
        msg_skills = page.locator(".msg-skill")
        check("消息内渲染 Skill 标签", msg_skills.count() == 6, f"{msg_skills.count()} 个")
        check("其中 2 个为「已启用」态", page.locator(".msg-skill.on").count() == 2,
              f"{page.locator('.msg-skill.on').count()} 个")
        page.screenshot(path=f"{SHOT}/03-chat-with-skills.png", full_page=True)

        # ============ 4. 切换到深度研究 ============
        print("\n[4] 深度研究 Tab")
        page.locator(".mode-tab", has_text="深度研究").click()
        page.wait_for_timeout(1200)
        check("研究视图渲染", page.locator(".research-main").count() == 1)
        check("聊天输入区已隐藏", page.locator(".input-box").count() == 0)
        check("检索源徽标存在", page.locator(".research-badge").count() == 1,
              page.locator(".research-badge").inner_text() if page.locator(".research-badge").count() else "")
        banner_txt = page.locator(".banner").inner_text() if page.locator(".banner").count() else ""
        check("无检索 Key 提示条", "未配置检索服务" in banner_txt, banner_txt[:60])
        page.screenshot(path=f"{SHOT}/04-research-view.png", full_page=True)

        # ============ 5. 无检索 Key 时提交按钮应禁用 ============
        print("\n[5] 无检索 Key 时的提交保护")
        page.locator(".research-form textarea").fill("联调测试：2026 年新能源汽车市场分析")
        page.wait_for_timeout(300)
        disabled = page.locator(".research-submit").is_disabled()
        check("提交按钮被禁用（前置校验）", disabled)
        check("表单已填入内容", page.locator(".research-form textarea").input_value() != "")

        # 任务列表应展示（含历史任务）
        page.wait_for_timeout(500)
        check("任务列表渲染", page.locator(".research-item").count() >= 1,
              f"{page.locator('.research-item').count()} 个")
        check("任务状态标签渲染", page.locator(".research-status").count() >= 1)
        page.screenshot(path=f"{SHOT}/05-research-guard.png", full_page=True)

        # ============ 6. 打开历史「已完成」任务，验证报告渲染 ============
        print("\n[6] 历史完成任务 + 报告渲染")
        completed = page.locator(".research-item", has=page.locator(".research-status.completed"))
        n_done = completed.count()
        check("存在已完成任务", n_done >= 1, f"{n_done} 个")
        if n_done:
            completed.first.click()
            page.wait_for_timeout(2500)

            check("详情头部显示 completed",
                  page.locator(".research-detail .research-status.completed").count() == 1)
            check("质量分展示", page.locator(".research-detail .research-score").count() >= 1,
                  page.locator(".research-detail .research-score").inner_text() if page.locator(".research-detail .research-score").count() else "")
            check("进度时间线渲染", page.locator(".research-event").count() >= 5,
                  f"{page.locator('.research-event').count()} 条事件")

            report_el = page.locator(".research-report")
            check("报告区域渲染", report_el.count() == 1)
            if report_el.count():
                rtxt = report_el.inner_text()
                check("报告含 Markdown 标题", "新能源汽车" in rtxt, rtxt[:60].replace("\n", " "))
                check("报告含表格内容", "星辰电动" in rtxt or "800V" in rtxt)
                check("报告含列表项", page.locator(".research-report ul li").count() >= 2,
                      f"{page.locator('.research-report ul li').count()} 个 li")
                check("报告含标题元素 h1/h2", page.locator(".research-report h1, .research-report h2").count() >= 2,
                      f"h1={page.locator('.research-report h1').count()} h2={page.locator('.research-report h2').count()}")
                check("报告表格已渲染为 <table>",
                      page.locator(".research-report table").count() >= 1,
                      f"{page.locator('.research-report table').count()} 个表格")
                check("报告表格有表头单元格",
                      page.locator(".research-report table th").count() >= 4,
                      f"{page.locator('.research-report table th').count()} 个 th")
                check("表格内容正确",
                      "星辰电动" in page.locator(".research-report table").inner_text(),
                      page.locator(".research-report table").inner_text()[:50].replace("\n", " ") if page.locator(".research-report table").count() else "")
            page.screenshot(path=f"{SHOT}/06-research-report.png", full_page=True)

        # ============ 7. 前端控制台无报错 ============
        print("\n[7] 控制台错误检查")
        real_errors = [e for e in errors if "favicon" not in e.lower()]
        check("无 JS 控制台错误", not real_errors, "; ".join(real_errors[:3]))

        browser.close()

    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"UI 联调测试: {passed}/{total} 通过")
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"  ❌ {name}  {detail}")
    print(f"截图目录: {SHOT}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
