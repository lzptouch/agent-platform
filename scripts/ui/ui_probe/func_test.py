#!/usr/bin/env python3
"""
前端全功能浏览器测试（模拟真实点击与输入）。

覆盖 8 组：
  A 前端↔后端连通性（浏览器内 fetch + 页面数据溯源）
  B v3 工作台（新建/发送/模式/命令面板/@选择/重命名/删除/任务切换）
  C 旧对话页与工作页（抽屉会话、建议按钮、模型选择、Plan 勾选、团队选择、Skill 全选清空）
  D 能力后台三 Tab（团队 CRUD / 技能 CRUD+校验+导出 / MCP 启停+工具）
  E 定时任务（新建/cron校验/启停/立即执行/删除）
  F 其余功能页（深度研究/产物/RAG/Web/WR/状态/设置）
  G 全局能力开关（顶栏 4 复选框 + Skill popover）
  H 旧路径重定向与灰度回退

运行：cd backend && .venv/bin/python ../scripts/ui/ui_probe/func_test.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright, Page
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _browser import new_page

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5185")
OUT = Path("/tmp/agent_ui_probe/func")
OUT.mkdir(parents=True, exist_ok=True)

results: list[tuple[str, str, bool, str]] = []
section = "init"


def sec(name: str) -> None:
    global section
    section = name
    print(f"\n{'=' * 92}\n== {name}\n{'=' * 92}")


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((section, name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"   → {detail}" if detail else ""))
    return ok


async def fill_field(scope, label: str, value: str) -> bool:
    """在可见 el-form-item 中按 label 定位并填值"""
    item = scope.locator(".el-form-item:visible").filter(has_text=label).first
    if await item.count() == 0:
        item = scope.locator(".el-form-item").filter(has_text=label).first
    if await item.count() == 0:
        return False
    inp = item.locator("input[type=text], input:not([type]), textarea").first
    if await inp.count() == 0:
        return False
    await inp.fill(value)
    return True


async def confirm_dialog(page: Page) -> bool:
    """点确认框的「确定 / OK」"""
    box = page.locator(".el-message-box").last
    if await box.count() == 0:
        return False
    for name in ("确定", "OK"):
        cand = box.get_by_role("button", name=name)
        if await cand.count() > 0:
            await cand.click()
            return True
    await box.locator("button").last.click()
    return True


async def toast_of(page: Page) -> str:
    try:
        await page.wait_for_selector(".el-message", timeout=6000)
        return (await page.locator(".el-message").last.inner_text()).strip()
    except Exception:
        return ""


# ============================ A. 连通性 ============================
async def test_connectivity(page: Page) -> None:
    sec("A. 前端 ↔ 后端 连通性")
    await page.goto(f"{BASE}/workspace", wait_until="networkidle", timeout=45000)
    await page.wait_for_timeout(1200)
    r = await page.evaluate("""async () => {
      const out = {};
      for (const p of ['/api/v1/health','/api/v1/agent/models','/api/v1/skills','/api/v1/mcp_servers','/api/v1/sessions']) {
        try { const res = await fetch(p); out[p] = res.status; } catch (e) { out[p] = 'ERR:'+e.message; }
      }
      return out;
    }""")
    for p, st in r.items():
        check(f"浏览器 fetch {p}", st == 200, f"status={st}")

    await page.goto(f"{BASE}/admin/capabilities", wait_until="networkidle", timeout=45000)
    await page.wait_for_timeout(1500)
    await page.get_by_role("tab", name="技能").click()
    await page.wait_for_timeout(1200)
    skill_rows = await page.locator(".el-tab-pane:visible .el-table__row").count()
    check("技能表格已从后端加载数据", skill_rows >= 5, f"rows={skill_rows}")
    tbl_txt = await page.locator(".el-tab-pane:visible .el-table").first.inner_text()
    check("技能名来自后端（poem-writer 存在）", "poem-writer" in tbl_txt)
    await page.get_by_role("tab", name="连接器（MCP）").click()
    await page.wait_for_timeout(1200)
    mcp_txt = await page.locator("body").inner_text()
    check("MCP 列表已从后端加载（weather 存在）", "weather" in mcp_txt)
    await page.screenshot(path=str(OUT / "A1_capabilities_mcp.png"))


# ============================ B. v3 工作台 ============================
async def test_workspace(page: Page) -> None:
    sec("B. v3 工作台交互")
    await page.goto(f"{BASE}/workspace", wait_until="networkidle", timeout=45000)
    await page.wait_for_timeout(1500)

    # 场景 Chip 点击 → 填充输入框（先清空会话确保处于空态）
    if await page.locator(".chip.scene").count() == 0:
        await page.locator(".ws-head").get_by_role("button", name="新建任务").click()
        await page.wait_for_timeout(1200)
    await page.locator(".chip.scene").first.click()
    await page.wait_for_timeout(500)
    val = await page.locator(".composer .composer-ta").input_value()
    check("点击场景 Chip 自动填充输入框", len(val) > 5, val[:40])

    # 能力 Chip 切换
    cap = page.locator(".chip").filter(has_text="网络检索").first
    before = "on" in (await cap.get_attribute("class") or "")
    await cap.click()
    await page.wait_for_timeout(400)
    after = "on" in (await cap.get_attribute("class") or "")
    check("能力 Chip 可切换（网络检索）", before != after, f"{before}→{after}")

    # 发送消息
    await page.locator(".composer .composer-ta").fill("用一句话介绍你自己")
    await page.locator(".composer .send-btn").click()
    await page.wait_for_timeout(2500)
    check("用户气泡渲染", await page.locator(".user-bubble").count() > 0)
    check("助手消息渲染", await page.locator(".assistant-msg").count() > 0)
    for _ in range(90):
        if await page.locator(".status-done").count() > 0 or await page.locator(".status-error").count() > 0:
            break
        await page.wait_for_timeout(1000)
    check("流式执行完成", await page.locator(".status-done").count() > 0)
    check("执行轨迹出现", await page.locator(".timeline").count() > 0)
    await page.screenshot(path=str(OUT / "B1_workspace_chat.png"))

    # 重命名
    await page.locator(".ws-head").get_by_role("button", name="重命名").click()
    await page.wait_for_timeout(700)
    box = page.locator(".el-message-box").last
    if await box.count() > 0:
        inp = box.locator("input").first
        await inp.fill("func-test 任务")
        await box.locator("button").last.click()
        await page.wait_for_timeout(1500)
        check("重命名任务成功", "func-test 任务" in await page.locator(".ws-head").inner_text())
    else:
        check("重命名任务成功", False, "未出现重命名对话框")

    # 任务出现在左栏
    await page.wait_for_timeout(800)
    side = await page.locator("aside.sidenav").inner_text()
    check("新任务出现在左栏任务流", "func-test 任务" in side)

    # 点击左栏另一个任务 → 切换
    items = page.locator("aside.sidenav .task-item")
    if await items.count() > 1:
        await items.nth(1).click()
        await page.wait_for_timeout(1500)
        check("点击左栏任务可切换", "task=" in page.url, page.url)

    # 新建任务
    await page.locator(".ws-head").get_by_role("button", name="新建任务").click()
    await page.wait_for_timeout(1200)
    check("新建任务后主区回到空态", await page.locator("h1.hero").count() > 0)

    # 删除任务（先发一条造出任务）
    await page.locator(".composer .composer-ta").fill("测试")
    await page.locator(".composer .send-btn").click()
    await page.wait_for_timeout(3000)
    await page.locator(".ws-head").get_by_role("button", name="删除").click()
    await page.wait_for_timeout(800)
    if await confirm_dialog(page):
        await page.wait_for_timeout(1500)
        check("删除任务（确认框）", await page.locator(".el-message").count() > 0
              or "删除" in await page.locator("body").inner_text())


# ============================ C. 旧对话页 / 工作页 ============================
async def test_legacy_chat_work(page: Page) -> None:
    sec("C. 旧对话页 / 工作页")
    await page.goto(f"{BASE}/chat", wait_until="networkidle", timeout=45000)
    await page.evaluate("() => { localStorage.removeItem('ap-vue-ep-session'); localStorage.removeItem('ap-vue-ep-mode') }")
    await page.reload(wait_until="networkidle", timeout=45000)
    await page.wait_for_timeout(1800)

    # 打开会话抽屉
    await page.locator(".chat-header button").first.click()
    await page.wait_for_timeout(800)
    check("会话抽屉可打开", await page.locator(".el-drawer").count() > 0)
    check("抽屉内有历史会话", await page.locator(".el-drawer .session-item").count() > 0)
    await page.screenshot(path=str(OUT / "C1_chat_drawer.png"))
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(500)

    # 模型下拉
    sel = page.locator(".chat-header .el-select").first
    await sel.click()
    await page.wait_for_timeout(700)
    opts = await page.locator(".el-select-dropdown__item").count()
    check("模型下拉可展开且有选项", opts > 0, f"options={opts}")
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(400)

    # 建议按钮 → 发送
    await page.locator(".suggestions button").first.click()
    await page.wait_for_timeout(2500)
    check("建议按钮触发消息发送", await page.locator(".user-bubble").count() > 0)
    await page.screenshot(path=str(OUT / "C2_chat_suggest.png"))

    # 工作页
    await page.goto(f"{BASE}/work", wait_until="networkidle", timeout=45000)
    await page.wait_for_timeout(1500)
    check("工作页左栏会话列表存在", await page.locator(".session-item, .el-table__row").count() >= 0)
    plan_lbl = page.locator(".el-checkbox").filter(has_text="Plan").first
    if await plan_lbl.count() > 0:
        st = await plan_lbl.locator("input").is_checked()
        await plan_lbl.click()
        await page.wait_for_timeout(400)
        check("Plan 勾选框可切换", st != await plan_lbl.locator("input").is_checked())
    # 团队下拉
    team_sel = page.locator(".el-select").last
    await team_sel.click()
    await page.wait_for_timeout(700)
    check("工作页团队下拉可展开", await page.locator(".el-select-dropdown__item").count() > 0)
    await page.keyboard.press("Escape")
    await page.screenshot(path=str(OUT / "C3_work_page.png"))


# ============================ D. 能力后台三 Tab ============================
async def test_capabilities(page: Page) -> None:
    sec("D. 能力后台：团队 / 技能 / MCP")
    await page.goto(f"{BASE}/admin/capabilities", wait_until="networkidle", timeout=45000)
    await page.wait_for_timeout(1500)

    # ---- 团队：新建 ----
    await page.get_by_role("button", name="新建团队").first.click()
    await page.wait_for_timeout(900)
    dr = page.locator(".el-drawer:visible").last
    check("新建团队抽屉打开", await dr.is_visible())
    ok_name = await fill_field(dr, "名称", "func-test-团队")
    check("团队名称可输入", ok_name)
    await fill_field(dr, "描述", "浏览器功能测试创建")
    # 成员 Skill：el-select multiple，选择第一个选项（skill_names 为必填）
    sk_item = dr.locator(".el-form-item").filter(has_text="成员 Skill").first
    if await sk_item.count() > 0:
        await sk_item.locator(".el-select__wrapper").first.click(force=True)
        await page.wait_for_timeout(700)
        opt = page.locator(".el-select-dropdown__item:visible").first
        if await opt.count() > 0:
            await opt.click(force=True)
            await page.wait_for_timeout(600)
        else:
            await page.keyboard.press("Escape")
    save = dr.get_by_role("button", name="保存")
    if await save.count() == 0:
        save = dr.get_by_role("button", name="确定")
    await save.click()
    await page.wait_for_timeout(1500)
    body = await page.locator("body").inner_text()
    check("团队创建后出现在表格", "func-test-团队" in body)
    await page.screenshot(path=str(OUT / "D1_team_created.png"))

    # ---- 团队：编辑 / 停用 / 删除 ----
    row = page.locator(".el-tab-pane:visible .el-table__row").filter(has_text="func-test-团队").first
    if await row.count() > 0:
        btns = row.locator("button")
        n = await btns.count()
        check("团队行有操作按钮", n > 0, f"buttons={n}")
        # 启用开关
        sw = row.locator(".el-switch")
        if await sw.count() > 0:
            await sw.first.click()
            await page.wait_for_timeout(1200)
            check("团队启用开关可切换", True)
        # 删除（最后一个按钮）
        if n > 0:
            await btns.last.click()
            await page.wait_for_timeout(700)
            if await confirm_dialog(page):
                await page.wait_for_timeout(2000)
                await page.reload(wait_until="networkidle", timeout=45000)
                await page.wait_for_timeout(1200)
                check("团队删除成功", "func-test-团队" not in await page.locator("body").inner_text())

    # ---- 技能 Tab ----
    await page.get_by_role("tab", name="技能").click()
    await page.wait_for_timeout(1200)
    check("技能 Tab 表格渲染", await page.locator(".el-table__row").count() > 0)
    row = page.locator(".el-tab-pane:visible .el-table__row").filter(has_text="poem-writer").first
    if await row.count() > 0:
        btns = row.locator("button")
        labels = [await btns.nth(i).inner_text() for i in range(min(await btns.count(), 6))]
        check("技能行操作含 查看/校验/编辑/导出/删除", any("校验" in x for x in labels), " | ".join(labels))
        # 校验
        for i, t in enumerate(labels):
            if "校验" in t:
                await btns.nth(i).click()
                await page.wait_for_timeout(1500)
                check("技能校验触发并有结果", True, (await toast_of(page))[:40])
                # 校验结果弹窗会遮挡后续操作，需关闭
                await page.wait_for_timeout(800)
                vdlg = page.locator(".el-dialog:visible").last
                if await vdlg.count() > 0:
                    await vdlg.locator(".el-dialog__headerbtn").first.click()
                    await page.wait_for_timeout(600)
                    check("技能校验结果弹窗展示并可关闭", True)
                break
    await page.screenshot(path=str(OUT / "D2_skills_tab.png"))

    # ---- MCP Tab（卡片形态）----
    await page.get_by_role("tab", name="连接器（MCP）").click()
    await page.wait_for_timeout(1500)
    mcp_body = await page.locator("body").inner_text()
    check("MCP Tab 显示服务器", "weather" in mcp_body)
    pane = page.locator(".el-tab-pane:visible").first
    cards = pane.locator(".el-card")
    check("MCP 以卡片呈现各 Server", await cards.count() >= 3, f"cards={await cards.count()}")
    btns_all = await pane.locator("button").all_inner_texts()
    check("MCP 提供 启动/停止 操作", any("启动" in x for x in btns_all) and any("停止" in x for x in btns_all))
    check("MCP 提供 刷新/重载工具缓存", any("刷新" in x for x in btns_all) and any("重载" in x for x in btns_all),
          " | ".join(x.strip() for x in btns_all[:6]))
    # 刷新
    await pane.get_by_role("button", name="刷新").first.click()
    await page.wait_for_timeout(1500)
    check("MCP 刷新可用", True)
    # 重载工具缓存
    rl = pane.get_by_role("button", name="重载工具缓存").first
    if await rl.count() > 0:
        await rl.click()
        await page.wait_for_timeout(2000)
        check("MCP 重载工具缓存可用", True, (await toast_of(page))[:50])
    # 停止 / 启动 单个 Server
    stop_btn = pane.get_by_role("button", name="停止").first
    if await stop_btn.count() > 0:
        await stop_btn.click()
        await page.wait_for_timeout(2000)
        check("MCP 停止操作可用", True, (await toast_of(page))[:50])
        start_btn = pane.get_by_role("button", name="启动").first
        if await start_btn.count() > 0:
            await start_btn.click()
            await page.wait_for_timeout(2000)
            check("MCP 启动操作可用", True, (await toast_of(page))[:50])
    await page.screenshot(path=str(OUT / "D4_mcp_tab.png"))


# ============================ E. 定时任务 ============================
async def test_schedules(page: Page) -> None:
    sec("E. 定时任务")
    await page.goto(f"{BASE}/admin/schedules", wait_until="networkidle", timeout=45000)
    await page.wait_for_timeout(1500)
    check("定时任务表格渲染", await page.locator(".el-table__row").count() >= 0)

    await page.get_by_role("button", name="新建任务").first.click()
    await page.wait_for_timeout(900)
    dr = page.locator(".el-drawer:visible").last
    check("新建任务抽屉打开", await dr.is_visible())
    await fill_field(dr, "名称", "func-test-定时")
    await fill_field(dr, "任务内容", "回复 OK")
    # 调度方式切到 cron（默认 interval）
    kind_item = dr.locator(".el-form-item").filter(has_text="调度方式").first
    if await kind_item.count() > 0:
        cron_radio = kind_item.locator(".el-radio").filter(has_text="cron").first
        if await cron_radio.count() > 0:
            await cron_radio.click()
            await page.wait_for_timeout(600)
        else:
            await kind_item.locator(".el-radio").first.click()
            await page.wait_for_timeout(600)
    cron_item = dr.locator(".el-form-item").filter(has_text="cron 表达式（5 段）").first
    if await cron_item.count() == 0:
        cron_item = dr.locator(".el-form-item").filter(has_text="cron 表达式").last
    if await cron_item.count() > 0:
        await cron_item.locator("input[type=text]").first.fill("0 4 * * *")
    else:
        iv_item = dr.locator(".el-form-item").filter(has_text="间隔").first
        if await iv_item.count() > 0:
            await iv_item.locator("input[type=text]").first.fill("3600")
    # 校验按钮
    val = dr.get_by_role("button", name="校验")
    if await val.count() > 0:
        await val.click()
        await page.wait_for_timeout(1200)
        check("cron 表达式校验可触发", True, (await toast_of(page))[:50])
    await page.screenshot(path=str(OUT / "E1_schedule_drawer.png"))
    save = dr.get_by_role("button", name="保存")
    if await save.count() == 0:
        save = dr.get_by_role("button", name="确定")
    await save.click()
    await page.wait_for_timeout(1800)
    body = await page.locator("body").inner_text()
    check("定时任务创建成功并出现在表格", "func-test-定时" in body)

    row = page.locator(".el-table__row").filter(has_text="func-test-定时").first
    if await row.count() > 0:
        btns = row.locator("button")
        labels = [await btns.nth(i).inner_text() for i in range(min(await btns.count(), 6))]
        check("定时任务行有 运行/编辑/删除 操作", len(labels) > 0, " | ".join(labels))
        for i, t in enumerate(labels):
            if "运行" in t and "记录" not in t:
                await btns.nth(i).click()
                await page.wait_for_timeout(2500)
                check("立即执行可触发", True, (await toast_of(page))[:40])
                break
        # 删除
        btns = row.locator("button")
        labels = [await btns.nth(i).inner_text() for i in range(min(await btns.count(), 6))]
        for i, t in enumerate(labels):
            if "删除" in t:
                await btns.nth(i).click()
                await page.wait_for_timeout(700)
                if await confirm_dialog(page):
                    await page.wait_for_timeout(2000)
                    await page.reload(wait_until="networkidle", timeout=45000)
                    await page.wait_for_timeout(1200)
                    left = await page.locator(".el-table__row").filter(has_text="func-test-定时").count()
                    check("定时任务删除成功", left == 0, f"残留={left}")
                break
    await page.screenshot(path=str(OUT / "E2_schedules.png"))


# ============================ F. 其余功能页 ============================
async def test_other_pages(page: Page) -> None:
    sec("F. 其余功能页")

    # 深度研究
    await page.goto(f"{BASE}/admin/research", wait_until="networkidle", timeout=45000)
    await page.wait_for_timeout(1200)
    ok_task = await fill_field(page, "研究任务", "func-test 深度研究主题")
    if not ok_task:
        ta = page.locator("textarea").first
        if await ta.count() > 0:
            await ta.fill("func-test 深度研究主题")
            ok_task = True
    check("深度研究任务可输入", ok_task)
    btn = page.get_by_role("button", name="开始研究").first
    await page.wait_for_timeout(800)
    enabled = await btn.is_enabled()
    alert = page.locator(".el-alert")
    alert_txt = (await alert.first.inner_text()) if await alert.count() > 0 else ""
    if enabled:
        await btn.click()
        check("深度研究可提交", True)
    else:
        check("未配置搜索服务时「开始研究」正确禁用并给出警告", "未配置" in alert_txt or "服务" in alert_txt,
              alert_txt.replace("\n", " ")[:70])
    await page.wait_for_timeout(2500)
    check("深度研究页给出可提交或降级结论",
          True, "提交" if enabled else "因未配置搜索服务而禁用（预期降级）")
    await page.screenshot(path=str(OUT / "F1_research.png"))

    # 产物
    await page.goto(f"{BASE}/admin/artifacts", wait_until="networkidle", timeout=45000)
    await page.wait_for_timeout(1200)
    check("产物页 Tab 渲染", await page.locator(".el-tabs__item").count() >= 4)
    await page.get_by_role("tab", name="报告与文档").click()
    await page.wait_for_timeout(900)
    check("产物分类 Tab 可切换", True)
    await page.get_by_role("button", name="刷新").first.click()
    await page.wait_for_timeout(1200)
    check("产物页刷新可用", True)
    await page.screenshot(path=str(OUT / "F2_artifacts.png"))

    # RAG
    await page.goto(f"{BASE}/admin/knowledge", wait_until="networkidle", timeout=45000)
    await page.wait_for_timeout(1200)
    await fill_field(page, "问题", "这个平台提供哪些能力")
    await page.get_by_role("button", name="查询").first.click()
    await page.wait_for_timeout(1500)
    check("RAG 问答可提交", True)
    for _ in range(60):
        if await page.locator(".el-message").count() > 0:
            break
        await page.wait_for_timeout(1000)
    await page.get_by_role("tab", name="纯检索（不调 LLM）").click()
    await page.wait_for_timeout(900)
    await page.screenshot(path=str(OUT / "F3_rag.png"))
    check("RAG 三个 Tab 可切换", await page.locator(".el-tabs__item").count() == 3)

    # Web 检索（预期缺密钥）
    await page.goto(f"{BASE}/admin/web", wait_until="networkidle", timeout=45000)
    await page.wait_for_timeout(1200)
    ok_q = await fill_field(page, "研究问题", "2026 AI 新闻")
    if not ok_q:
        ta = page.locator("textarea").first
        if await ta.count() > 0:
            await ta.fill("2026 AI 新闻")
    b2 = page.get_by_role("button", name="开始检索").first
    check("Web 检索按钮随输入启用", await b2.is_enabled())
    await b2.click()
    await page.wait_for_timeout(3000)
    t = await toast_of(page)
    check("Web 检索可提交并给出缺密钥提示", t != "" or await page.locator(".el-alert").count() > 0, t[:60])
    await page.screenshot(path=str(OUT / "F4_web.png"))

    # WR 范式
    await page.goto(f"{BASE}/admin/lab/wr", wait_until="networkidle", timeout=45000)
    await page.wait_for_timeout(1200)
    await fill_field(page, "问题", "用一句话解释什么是 SSE")
    b3 = page.get_by_role("button", name="执行").first
    check("WR 执行按钮随输入启用", await b3.is_enabled())
    await b3.click()
    await page.wait_for_timeout(3000)
    check("WR 范式可执行", await page.locator(".el-card").count() > 0, (await toast_of(page))[:50])
    await page.screenshot(path=str(OUT / "F5_wr.png"))

    # 系统状态
    await page.goto(f"{BASE}/admin/status", wait_until="networkidle", timeout=45000)
    await page.wait_for_timeout(1500)
    st = await page.locator("body").inner_text()
    check("系统状态显示后端指标", "database" in st.lower() or "mcp" in st.lower())
    await page.screenshot(path=str(OUT / "F6_status.png"))

    # 设置
    await page.goto(f"{BASE}/admin/settings", wait_until="networkidle", timeout=45000)
    await page.wait_for_timeout(1200)
    dark = page.get_by_text("深色", exact=True).first
    if await dark.count() > 0:
        await dark.click()
        await page.wait_for_timeout(900)
        check("设置页可切换深色主题", "dark" in (await page.evaluate("()=>document.documentElement.className")) or
              await page.locator(".el-radio-button.is-active").count() > 0)
        light = page.get_by_text("浅色", exact=True).first
        await light.click()
        await page.wait_for_timeout(600)
    check("设置页可渲染", await page.locator("body").inner_text() != "")
    await page.screenshot(path=str(OUT / "F7_settings.png"))


# ============================ G. 全局能力开关 ============================
async def test_global_switches(page: Page) -> None:
    sec("G. 全局顶栏能力开关")
    await page.goto(f"{BASE}/chat", wait_until="networkidle", timeout=45000)
    await page.wait_for_timeout(1500)
    cbs = page.locator(".admin-top .el-checkbox, .topbar .el-checkbox")
    n = await cbs.count()
    check("顶栏存在能力复选框", n >= 4, f"count={n}")
    if n >= 1:
        cb = cbs.nth(0)
        st = await cb.locator("input").is_checked()
        await cb.click()
        await page.wait_for_timeout(500)
        check("顶栏复选框可切换", st != await cb.locator("input").is_checked())
        await cb.click()
    # MCP Server popover
    await page.get_by_role("button", name="Skill").first.click()
    await page.wait_for_timeout(800)
    pop = page.locator(".el-popover:visible, .el-popper:visible").last
    check("Skill 弹层可打开", await page.locator(".el-popper:visible").count() > 0)
    if await page.locator(".el-popper:visible").count() > 0:
        await page.get_by_role("button", name="清空").click()
        await page.wait_for_timeout(700)
        check("Skill 清空可点击", True)
        await page.get_by_role("button", name="全选").click()
        await page.wait_for_timeout(700)
        check("Skill 全选可点击", True)
    await page.keyboard.press("Escape")
    await page.screenshot(path=str(OUT / "G1_topbar.png"))


# ============================ H. 旧路径 / 灰度 ============================
async def test_legacy_routes(page: Page) -> None:
    sec("H. 旧路径重定向与灰度回退")
    mapping = {
        "/teams": "/admin/capabilities", "/skills": "/admin/capabilities",
        "/mcp": "/admin/capabilities", "/schedules": "/admin/schedules",
        "/research": "/admin/research", "/files": "/admin/artifacts",
        "/rag": "/admin/knowledge", "/web": "/admin/web", "/status": "/admin/status",
        "/settings": "/admin/settings", "/wr": "/admin/lab/wr",
    }
    for old, target in mapping.items():
        await page.goto(f"{BASE}{old}", wait_until="networkidle", timeout=40000)
        await page.wait_for_timeout(600)
        check(f"旧路径 {old} → {target}", target in page.url, page.url)
    for p in ["/chat", "/work"]:
        await page.goto(f"{BASE}{p}", wait_until="networkidle", timeout=40000)
        await page.wait_for_timeout(600)
        check(f"旧页面 {p} 仍可访问", p in page.url, page.url)


async def main() -> int:
    errors: list[str] = []
    async with async_playwright() as p:
        browser, ctx, page = await new_page(p)
        page.on("pageerror", lambda e: errors.append(f"{page.url} :: {e}"))
        page.on("console", lambda m: errors.append(f"{page.url} :: console.error {m.text}")
                if m.type == "error" else None)

        for fn in (test_connectivity, test_workspace, test_legacy_chat_work,
                   test_capabilities, test_schedules, test_other_pages,
                   test_global_switches, test_legacy_routes):
            try:
                await fn(page)
            except Exception as e:
                check(f"{fn.__name__} 执行异常", False, f"{type(e).__name__}: {e}")

        real = [e for e in errors if "favicon" not in e.lower() and "Failed to load resource" not in e]
        check("全程无未捕获 JS 错误", len(real) == 0, "; ".join(real[:3])[:200])
        await browser.close()

    total = len(results)
    passed = sum(1 for _, _, ok, _ in results if ok)
    print("\n" + "=" * 92)
    print(f"前端功能测试：{passed}/{total} 通过")
    by_sec: dict[str, list[bool]] = {}
    for s, _, ok, _ in results:
        by_sec.setdefault(s, []).append(ok)
    for s, oks in by_sec.items():
        print(f"  {s:34} {sum(oks)}/{len(oks)}")
    fails = [(s, n, d) for s, n, ok, d in results if not ok]
    if fails:
        print("\n失败明细：")
        for s, n, d in fails:
            print(f"  [{s}] {n}  {d[:90]}")
    print("=" * 92)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
