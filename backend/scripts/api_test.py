#!/usr/bin/env python3
"""
后端全接口测试（覆盖 OpenAPI 全部 69 个 operation）。

按依赖顺序执行写操作，动态 id 透传；每个接口记录状态码、耗时与判定。
用法：cd backend && .venv/bin/python scripts/api_test.py [base_url]
"""
from __future__ import annotations

import asyncio
import io
import json
import sys
from urllib.parse import urlparse
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18040").rstrip("/")
API = f"{BASE}/api/v1"

results: list[dict[str, Any]] = []
C: dict[str, Any] = {}


async def call(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    expect: int | list[int] = 200,
    label: str = "",
    json_body: Any = None,
    params: dict | None = None,
    files: Any = None,
    content: bytes | None = None,
    headers: dict | None = None,
    timeout: float = 60.0,
    stream: bool = False,
) -> Any:
    url = path if path.startswith("http") else f"{API}{path}"
    t0 = time.perf_counter()
    status = 0
    detail = ""
    data: Any = None
    try:
        if stream:
            async with client.stream(method, url, json=json_body, params=params,
                                     files=files, content=content, headers=headers,
                                     timeout=timeout) as r:
                status = r.status_code
                chunks: list[str] = []
                async for line in r.aiter_lines():
                    if line.startswith("data:"):
                        chunks.append(line[5:].strip())
                data = chunks
                if status == 200:
                    types = []
                    for c in chunks:
                        try:
                            types.append(json.loads(c).get("type"))
                        except Exception:
                            pass
                    detail = f"events={len(chunks)} types={sorted(set(t for t in types if t))}"
                else:
                    detail = (await r.aread()).decode()[:160]
        else:
            r = await client.request(method, url, json=json_body, params=params,
                                     files=files, content=content, headers=headers, timeout=timeout)
            status = r.status_code
            try:
                data = r.json()
            except Exception:
                data = r.text[:200]
            detail = ""
            if status >= 400:
                detail = json.dumps(data, ensure_ascii=False)[:180] if not isinstance(data, str) else data[:180]
            elif isinstance(data, dict):
                detail = ",".join(list(data.keys())[:6])
    except Exception as e:  # 网络层异常
        detail = f"{type(e).__name__}: {e}"
    dt = (time.perf_counter() - t0) * 1000
    exp = expect if isinstance(expect, list) else [expect]
    ok = status in exp
    results.append({
        "ok": ok, "method": method, "path": path, "label": label,
        "status": status, "expect": exp, "ms": round(dt), "detail": detail[:150],
    })
    print(f"{'PASS' if ok else 'FAIL'} {method:6} {path:44} {status:>3} ({dt:6.0f}ms) {label} {'' if ok else detail[:120]}")
    return data


#: 需要显式确认才允许执行破坏性请求的路径前缀
DESTRUCTIVE_PREFIXES = ("/api/v1/skills", "/api/v1/files", "/api/v1/research",
                        "/api/v1/rag", "/api/v1/memories")


def _confirm_destructive(base: str) -> bool:
    """破坏性操作前的护栏。

    **E10**：此前脚本接受 ``sys.argv[1]`` 作为 base_url 后**无条件**执行
    DELETE / PUT / POST ingest 等写操作 → **误传生产地址即造成数据损毁**。

    现在：打印目标并要求显式 ``--yes-i-know``；非回环地址**即使带旗标也要二次确认**。
    """
    if "--yes-i-know" in sys.argv:
        host = urlparse(base).hostname or ""
        if host not in ("127.0.0.1", "localhost", "::1", ""):
            print(f"[api_test] ⚠ 目标 {base} **不是**本机地址 —— 请再次输入该地址以确认：", end="")
            try:
                answer = input().strip()
            except EOFError:
                return False
            if answer != base:
                print("[api_test] ✗ 目标不匹配，已中止")
                return False
        return True
    print(f"[api_test] ✗ 该脚本会对 **{base}** 执行破坏性操作（DELETE / PUT / ingest）。")
    print("[api_test]   确认无误后追加 --yes-i-know 重新运行。")
    return False


async def main() -> int:
    # **E10**：破坏性操作护栏（必须在任何请求之前）
    if not _confirm_destructive(BASE):
        print("[api_test] ✗ 已中止")
        return 2

    timeout = httpx.Timeout(200.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:

        # ============ 1. 系统与模型 ============
        print("\n--- 系统 / 模型 / 状态 ---")
        h = await call(client, "GET", "/health", label="健康检查")
        await call(client, "GET", "/agent/models", label="模型列表")
        st = await call(client, "GET", "/agent/status", label="Agent 状态")

        # ============ 2. 会话 CRUD ============
        print("\n--- 会话 CRUD ---")
        sess = await call(client, "POST", "/sessions",
                          json_body={"mode": "chat", "title": "api-test 会话"},
                          label="创建会话", expect=201)
        C["sid"] = sess.get("id") if isinstance(sess, dict) else None
        await call(client, "GET", "/sessions", params={"page": 1, "page_size": 5}, label="会话列表")
        await call(client, "GET", "/sessions", params={"mode": "work"}, label="按 mode 过滤")
        await call(client, "GET", "/sessions", params={"include_archived": "true"}, label="含归档")
        if C["sid"]:
            await call(client, "GET", f"/sessions/{C['sid']}", params={"message_limit": 10}, label="会话详情(含消息)")
            await call(client, "PATCH", f"/sessions/{C['sid']}",
                       json_body={"title": "api-test 已改名"}, label="重命名会话")

        # ============ 3. Agent 运行 ============
        print("\n--- Agent 运行 ---")
        ch = await call(client, "POST", "/agent/chat",
                        json_body={"query": "用一句话说你好", "reflection": False},
                        label="非流式问答", timeout=120)
        if isinstance(ch, dict):
            C["chat_answer_len"] = len(str(ch.get("answer", "")))
        ev = await call(client, "POST", "/agent/run",
                        json_body={"prompt": "用一句话说你好", "model": "", "mode": "chat",
                                   "session_id": C.get("sid"), "skills": None,
                                   "enable_mcp": False, "mcp_servers": [], "enable_rag": False,
                                   "enable_web_research": False, "enable_reflection": False},
                        label="流式运行 SSE", stream=True, timeout=150)
        C["run_events"] = ev if isinstance(ev, list) else []

        # sync 运行（较慢）
        rs = await call(client, "POST", "/agent/run/sync",
                        json_body={"prompt": "回复两个字：好的", "model": "", "mode": "chat",
                                   "skills": None, "enable_rag": False},
                        label="同步运行", timeout=200)
        C["run_id"] = rs.get("run_id") if isinstance(rs, dict) else None

        # ============ 4. 运行账本 ============
        print("\n--- 运行账本 / 事件回放 ---")
        await call(client, "GET", "/runs", params={"page": 1, "page_size": 5}, label="运行列表")
        if C.get("run_id"):
            await call(client, "GET", f"/runs/{C['run_id']}", label="运行详情")
            await call(client, "GET", f"/runs/{C['run_id']}/events",
                       params={"after_seq": 0, "limit": 50}, label="事件回放")
            await call(client, "GET", f"/runs/{C['run_id']}/stream",
                       params={"after_seq": 0}, label="事件流 SSE", stream=True, timeout=60)

        # ============ 5. Plan 审批 ============
        print("\n--- Plan 人工审批 ---")
        pev = await call(client, "POST", "/agent/run",
                         json_body={"prompt": "列出当前目录下的文件", "model": "", "mode": "work",
                                    "plan_first": True, "skills": None, "enable_rag": False},
                         label="Plan 运行（触发审批）", stream=True, timeout=150)
        plan_run_id = None
        plan_items = None
        for c in (pev if isinstance(pev, list) else []):
            try:
                o = json.loads(c)
            except Exception:
                continue
            if o.get("type") == "approval_required":
                plan_run_id = o.get("run_id")
                plan_items = o.get("plan")
        if plan_run_id:
            await call(client, "POST", f"/agent/runs/{plan_run_id}/approve",
                       json_body={"edited_plan": plan_items}, label="审批通过(带编辑计划)", timeout=180)
            await call(client, "GET", f"/runs/{plan_run_id}/events",
                       params={"after_seq": 0, "limit": 200}, label="审批后事件回放")
        # 拒绝分支
        pev2 = await call(client, "POST", "/agent/run",
                          json_body={"prompt": "读取 README.md 的前 3 行", "model": "", "mode": "work",
                                     "plan_first": True, "skills": None, "enable_rag": False},
                          label="Plan 运行（拒绝分支）", stream=True, timeout=150)
        rej_id = None
        for c in (pev2 if isinstance(pev2, list) else []):
            try:
                o = json.loads(c)
            except Exception:
                continue
            if o.get("type") == "approval_required":
                rej_id = o.get("run_id")
        if rej_id:
            await call(client, "POST", f"/agent/runs/{rej_id}/reject",
                       json_body={"reason": "api-test 拒绝"}, label="审批拒绝")

        # ============ 6. Skills ============
        print("\n--- Skills ---")
        sk = await call(client, "GET", "/skills", label="技能列表")
        skill_name = "api-test-skill"
        if isinstance(sk, dict) and sk.get("skills"):
            skill_name = sk["skills"][0]["name"]
        C["skill"] = skill_name
        await call(client, "GET", f"/skills/{skill_name}", label="技能详情")
        await call(client, "POST", f"/skills/{skill_name}/validate", label="技能校验")
        await call(client, "GET", f"/skills/{skill_name}/export", label="技能导出")
        await call(client, "GET", f"/skills/{skill_name}/files/SKILL.md", label="技能资源读取")
        await call(client, "POST", f"/skills/{skill_name}/toggle",
                   json_body={"enabled": False}, label="技能停用")
        await call(client, "POST", f"/skills/{skill_name}/toggle",
                   json_body={"enabled": True}, label="技能启用")
        await call(client, "PUT", f"/skills/{skill_name}",
                   json_body={"description": "api-test 修改的描述"}, label="技能更新")
        # 新建 → 改 → 删
        new_skill = await call(client, "POST", "/skills",
                               json_body={"name": "api-test-tmp-skill",
                                          "description": "临时技能",
                                          "content": "---\nname: api-test-tmp-skill\ndescription: 临时技能\n---\n\n# tmp\n"},
                               label="技能创建", expect=201)
        if isinstance(new_skill, dict) and new_skill.get("name"):
            await call(client, "PUT", "/skills/api-test-tmp-skill",
                       json_body={"description": "已更新"}, label="临时技能更新")
            await call(client, "DELETE", "/skills/api-test-tmp-skill", label="临时技能删除")
        # 导入
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("api-test-import/SKILL.md",
                       "---\nname: api-test-import\ndescription: 导入测试\n---\n\n# import\n")
        buf.seek(0)
        await call(client, "POST", "/skills/import", params={"overwrite": "true"},
                   files={"file": ("api-test-import.zip", buf.getvalue(), "application/zip")},
                   label="技能导入(zip)")
        await call(client, "DELETE", "/skills/api-test-import", label="清理导入技能")
        await call(client, "POST", "/skills/reload", label="技能重载")

        # ============ 7. MCP ============
        print("\n--- MCP ---")
        mc = await call(client, "GET", "/mcp_servers", label="MCP 列表")
        mcp_name = "weather"
        if isinstance(mc, dict) and mc.get("servers"):
            mcp_name = mc["servers"][0]["name"]
        C["mcp"] = mcp_name
        await call(client, "GET", f"/mcp_servers/{mcp_name}", label="MCP 详情")
        tools = await call(client, "GET", f"/mcp_servers/{mcp_name}/tools", label="MCP 工具列表")
        tool_name = None
        if isinstance(tools, dict) and tools.get("tools"):
            tool_name = tools["tools"][0]["name"]
        if tool_name:
            await call(client, "POST", f"/mcp_servers/{mcp_name}/call",
                       json_body={"tool": tool_name, "arguments": {}},
                       label=f"MCP 调用({tool_name})", timeout=90)
        await call(client, "POST", f"/mcp_servers/{mcp_name}/stop", label="MCP 停止")
        await call(client, "POST", f"/mcp_servers/{mcp_name}/start", label="MCP 启动", timeout=90)
        await call(client, "POST", "/mcp_servers/reload", label="MCP 重载")

        # ============ 8. RAG ============
        print("\n--- RAG ---")
        await call(client, "GET", "/rag/stats", label="RAG 统计")
        await call(client, "POST", "/rag/query",
                   json_body={"query": "这个项目是做什么的", "limit": 3}, label="RAG 问答", timeout=150)
        await call(client, "POST", "/rag/retrieval",
                   json_body={"query": "Agent 平台", "limit": 3}, label="RAG 检索", timeout=120)
        await call(client, "POST", "/rag/ingest", params={"recreate": "false"},
                   label="RAG 入库(recreate=false)", timeout=240)

        # ============ 9. Files ============
        print("\n--- 文件 ---")
        await call(client, "GET", "/files", label="文件列表")
        up = await call(client, "POST", "/files/upload",
                        files={"file": ("api-test.txt", b"hello api test\n", "text/plain")},
                        label="文件上传")
        fname = None
        if isinstance(up, dict):
            fname = up.get("name") or (up.get("files") or [{}])[0].get("name")
        C["fname"] = fname
        if fname:
            await call(client, "GET", f"/files/{fname}", label="文件下载/预览")
            await call(client, "DELETE", f"/files/{fname}", label="文件删除")

        # ============ 10. Schedules ============
        print("\n--- 定时任务 ---")
        await call(client, "GET", "/schedules", label="定时任务列表")
        await call(client, "GET", "/schedules/health", label="调度健康")
        await call(client, "POST", "/schedules/validate",
                   json_body={"cron_expr": "0 9 * * *", "timezone": "Asia/Shanghai"},
                   label="Cron 校验(合法)")
        await call(client, "POST", "/schedules/validate",
                   json_body={"cron_expr": "not-a-cron", "timezone": "Asia/Shanghai"},
                   label="Cron 校验(非法)", expect=[200, 400, 422])
        sch = await call(client, "POST", "/schedules",
                         json_body={"name": "api-test-定时", "prompt": "回复 OK", "mode": "chat",
                                    "schedule_kind": "cron", "cron_expr": "0 3 * * *",
                                    "enabled": False, "skills": None},
                         label="创建定时任务", expect=201)
        C["sch"] = sch.get("task_id") or sch.get("id") if isinstance(sch, dict) else None
        if C["sch"]:
            await call(client, "GET", f"/schedules/{C['sch']}", label="定时任务详情")
            await call(client, "PUT", f"/schedules/{C['sch']}",
                       json_body={"name": "api-test-定时-改"}, label="更新定时任务")
            await call(client, "POST", f"/schedules/{C['sch']}/toggle",
                       json_body={"enabled": True}, label="启用定时任务")
            await call(client, "POST", f"/schedules/{C['sch']}/toggle",
                       json_body={"enabled": False}, label="停用定时任务")
            await call(client, "GET", f"/schedules/{C['sch']}/runs",
                       params={"page": 1, "page_size": 5}, label="定时任务运行历史")
            await call(client, "POST", f"/schedules/{C['sch']}/run-now",
                       params={"wait_seconds": 0}, label="立即执行")
            await call(client, "DELETE", f"/schedules/{C['sch']}", label="删除定时任务", expect=204)

        # ============ 11. Teams ============
        print("\n--- 技能团队 ---")
        await call(client, "GET", "/teams", params={"include_disabled": "true"}, label="团队列表")
        tm = await call(client, "POST", "/teams",
                        json_body={"name": "api-test-团队", "skill_names": [C["skill"]],
                                   "description": "临时团队", "strategy": "none"},
                        label="创建团队", expect=201)
        tid = tm.get("id") if isinstance(tm, dict) else None
        C["team"] = tid
        if tid:
            await call(client, "GET", f"/teams/{tid}", label="团队详情")
            await call(client, "PUT", f"/teams/{tid}",
                       json_body={"name": "api-test-团队-改"}, label="更新团队")
            await call(client, "POST", f"/teams/{tid}/toggle",
                       json_body={"enabled": False}, label="团队停用")
            await call(client, "POST", f"/teams/{tid}/toggle",
                       json_body={"enabled": True}, label="团队启用")
            await call(client, "POST", f"/teams/{tid}/resolve",
                       json_body={"query": "帮我总结一下资料", "mode": "work"},
                       label="团队能力解析", timeout=90)
            await call(client, "DELETE", f"/teams/{tid}", label="删除团队", expect=204)

        # ============ 12. Deep Research ============
        print("\n--- 深度研究 ---")
        await call(client, "GET", "/research/health", label="研究健康")
        rl = await call(client, "GET", "/research", label="研究任务列表")
        rid = None
        if isinstance(rl, dict) and rl.get("tasks"):
            rid = rl["tasks"][0].get("task_id")
        if rid:
            await call(client, "GET", f"/research/{rid}", label="研究任务状态")
            await call(client, "GET", f"/research/{rid}/result", label="研究结果",
                       expect=[200, 202, 400, 404, 409])
            await call(client, "GET", f"/research/{rid}/stream", label="研究进度流 SSE",
                       stream=True, timeout=45, expect=[200, 404])
        sub = await call(client, "POST", "/research",
                         json_body={"task": "api-test 深度研究：FastAPI 与 SSE"},
                         label="提交研究任务", timeout=120)
        nrid = sub.get("task_id") if isinstance(sub, dict) else None
        if nrid:
            await call(client, "DELETE", f"/research/{nrid}", label="删除研究任务")

        # ============ 13. Web Research（缺密钥，预期失败）============
        print("\n--- Web Research（预期因缺密钥失败）---")
        await call(client, "GET", "/web_research/status", label="Web 检索状态")
        wr = await call(client, "POST", "/web_research/research",
                        json_body={"query": "2026 最新 AI 新闻", "profile": "standard"},
                        label="Web 检索", expect=[200, 400, 503], timeout=90)
        if isinstance(wr, dict) and not wr.get("success", True):
            results.append({"ok": True, "method": "POST", "path": "/web_research/research",
                            "label": "Web 检索（预期失败：未配置搜索密钥）", "status": 0,
                            "expect": "预期失败", "ms": 0, "detail": str(wr)[:120]})

        # ============ 14. 清理会话 ============
        if C.get("sid"):
            await call(client, "DELETE", f"/sessions/{C['sid']}", label="删除会话", expect=204)

    # ============ 汇总 ============
    total = len(results)
    passed = sum(1 for r in results if r["ok"])
    # operation 覆盖：把实测路径按 spec 模板匹配（避免路径参数名不同导致误判）
    import re as _re
    spec_ops: set[str] = set()
    spec_paths: list[tuple[str, str]] = []
    try:
        async with httpx.AsyncClient(timeout=15) as sc:
            spec = (await sc.get(f"{BASE}/openapi.json")).json()
        for sp, oo in spec.get("paths", {}).items():
            for mm in oo:
                spec_ops.add(f"{mm.upper()} {sp}")
                spec_paths.append((mm.upper(), sp))
    except Exception:
        pass

    def matched_ops() -> set[str]:
        hit: set[str] = set()
        for r in results:
            full = f"/api/v1{r['path']}" if not r["path"].startswith("/api") else r["path"]
            for mm, sp in spec_paths:
                if mm != r["method"]:
                    continue
                pattern = "^" + _re.sub(r"\{[^}]+\}", r"[^/]+", sp) + "$"
                if _re.match(pattern, full):
                    hit.add(f"{mm} {sp}")
                    break
        return hit

    ops = matched_ops()
    failed = [r for r in results if not r["ok"]]
    slow = sorted(results, key=lambda r: -r["ms"])[:5]
    print("\n" + "=" * 96)
    print(f"断言总数：{total} 项    通过：{passed}    失败：{len(failed)}")
    if spec_ops:
        covered = len(spec_ops & ops)
        missed = sorted(spec_ops - ops)
        print(f"OpenAPI operation 覆盖：{covered}/{len(spec_ops)}  ({covered / len(spec_ops) * 100:.1f}%)")
        for m in missed:
            print(f"    未覆盖：{m}")
    print(f"断言通过率：{passed / total * 100:.1f}%")
    print("-" * 96)
    if failed:
        print("失败明细：")
        for r in failed:
            print(f"  FAIL {r['method']:6} {r['path']:44} status={r['status']} expect={r['expect']} | {r['detail'][:110]}")
    print("-" * 96)
    print("最慢 5 项：")
    for r in slow:
        print(f"  {r['ms']:>6}ms  {r['method']:6} {r['path']:44} {r['label']}")
    print("=" * 96)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
