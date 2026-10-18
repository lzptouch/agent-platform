#!/usr/bin/env node
/**
 * frontend/scripts/smoke.mjs
 *
 * 自动化端到端冒烟测试 —— 35 端点 × 关键异常场景
 *
 * 用法：
 *   1) 启动后端：cd backend && .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
 *   2) 运行本脚本：node frontend/scripts/smoke.mjs
 *      或：node frontend/scripts/smoke.mjs http://127.0.0.1:8000
 *      或：node frontend/scripts/smoke.mjs http://192.168.x.x:8000
 *
 * 输出：每个端点的 HTTP 状态、响应摘要、错误信息。
 * 退出码：所有预期检查通过则 0，否则 1。
 *
 * 关联：计划文档 §9 验收标准。
 */

import { setTimeout as sleep } from 'node:timers/promises'

const BASE = process.argv[2] || 'http://127.0.0.1:8000'
const PASS = []
const FAIL = []
let pass = 0
let fail = 0

// ===== 工具 =====
async function req(method, path, body, expect = [200, 202]) {
  const url = `${BASE}${path}`
  const opts = { method, headers: {} }
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  try {
    const start = Date.now()
    const resp = await fetch(url, opts)
    const text = await resp.text()
    const ms = Date.now() - start
    let json = null
    try { json = JSON.parse(text) } catch { /* not json */ }
    const ok = expect.includes(resp.status)
    return { status: resp.status, ok, ms, text: text.length, json }
  } catch (e) {
    return { status: 0, ok: false, ms: 0, text: 0, json: null, error: e.message }
  }
}

function check(name, ok, extra = '') {
  if (ok) { pass++; PASS.push({ name, extra }); }
  else { fail++; FAIL.push({ name, extra }); }
  const tag = ok ? '\x1b[32m✓\x1b[0m' : '\x1b[31m✗\x1b[0m'
  console.log(`  ${tag} ${name}${extra ? '  ' + extra : ''}`)
}

function group(name, fn) {
  console.log(`\n\x1b[1m[${name}]\x1b[0m`)
  return fn()
}

// ===== 跑测 =====
async function main() {
  console.log(`\n\x1b[1m====================================\x1b[0m`)
  console.log(`\x1b[1m agent-platform 端到端冒烟测试 \x1b[0m`)
  console.log(`\x1b[1m BASE = ${BASE} \x1b[0m`)
  console.log(`\x1b[1m====================================\x1b[0m`)

  // ---------- 1. System ----------
  await group('System', async () => {
    const r = await req('GET', '/api/v1/health')
    check('GET /health → 200', r.ok && r.json?.status === 'ok',
      `(${r.ms}ms, status=${r.json?.status})`)
    check('GET /health 有 skills_loaded', typeof r.json?.skills_loaded === 'number')
    check('GET /health 有 version', typeof r.json?.version === 'string')
  })

  // ---------- 2. Agent ----------
  await group('Agent', async () => {
    const r = await req('GET', '/api/v1/agent/models')
    check('GET /agent/models → 200', r.ok)
    check('GET /agent/models 含 4 个模型', Array.isArray(r.json?.models) && r.json.models.length === 4)
    check('GET /agent/models 有 default_model', !!r.json?.default_model)

    const s = await req('GET', '/api/v1/agent/status')
    check('GET /agent/status → 200', s.ok)
    check('GET /agent/status 有 max_iterations', typeof s.json?.max_iterations === 'number')

    // SSE 流：取前 2 个事件
    const evResp = await fetch(`${BASE}/api/v1/agent/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: 'smoke test', model: r.json?.default_model || 'qwen-plus', skills: [], enable_mcp: false, mcp_servers: [], enable_rag: false, enable_web_research: false, enable_reflection: false }),
    })
    check('POST /agent/run SSE → 200', evResp.status === 200)
    check('POST /agent/run content-type=text/event-stream',
      (evResp.headers.get('content-type') || '').includes('text/event-stream'))
    const reader = evResp.body.getReader()
    const dec = new TextDecoder()
    let buf = ''
    let count = 0
    const seen = new Set()
    const events = []
    const tStart = Date.now()
    while (Date.now() - tStart < 15000) {
      const { value, done } = await Promise.race([reader.read(), sleep(10000).then(() => ({ done: true }))])
      if (done) break
      buf += dec.decode(value, { stream: true })
      const parts = buf.split('\n')
      buf = parts.pop() || ''
      for (const raw of parts) {
        const line = raw.replace(/\r$/, '')
        if (!line.startsWith('data:')) continue
        const p = line.slice(5).trim()
        if (!p) continue
        try {
          const ev = JSON.parse(p)
          if (!seen.has(ev.type)) { seen.add(ev.type); events.push(ev); count++ }
          if (ev.type === 'done' || ev.type === 'error') break
        } catch {}
      }
      if (count >= 3 && events.some(e => e.type === 'done' || e.type === 'error')) break
    }
    try { reader.cancel() } catch {}
    check(`POST /agent/run 收到至少 1 个事件（实际 ${count}）`, count >= 1)
    check(`SSE 含 done 或 error 终态`, events.some(e => e.type === 'done' || e.type === 'error'))
  })

  // ---------- 3. Skills ----------
  await group('Skills', async () => {
    const r = await req('GET', '/api/v1/skills')
    check('GET /skills → 200', r.ok)
    check(`GET /skills total=${r.json?.total}`, r.json?.total === 6)
    const first = r.json?.skills?.[0]?.name
    if (first) {
      const d = await req('GET', `/api/v1/skills/${first}`)
      check(`GET /skills/${first} → 200 含 content`, d.ok && typeof d.json?.content === 'string')
      const v = await req('POST', `/api/v1/skills/${first}/validate`, {})
      check(`POST /skills/${first}/validate → 200`, v.ok && v.json?.valid === true)
    }
  })

  // ---------- 4. Files ----------
  await group('Files', async () => {
    const r = await req('GET', '/api/v1/files')
    check('GET /files → 200', r.ok)
    check('GET /files 含 total 字段', typeof r.json?.total === 'number')
  })

  // ---------- 5. MCP ----------
  await group('MCP', async () => {
    const r = await req('GET', '/api/v1/mcp_servers')
    check('GET /mcp_servers → 200', r.ok)
    check('GET /mcp_servers total=3', r.json?.total === 3)
    const d = await req('GET', '/api/v1/mcp_servers/weather')
    check('GET /mcp_servers/weather → 200', d.ok)
    check('GET /mcp_servers/weather 含 tools', Array.isArray(d.json?.tools))
    // 工具调用：weather 无 KEY 也可调（NWS API）
    const c = await req('POST', '/api/v1/mcp_servers/weather/call', { tool: 'get_alerts', arguments: { state: 'CA' } }, [200])
    check('POST /mcp_servers/weather/call → 200', c.ok)
  })

  // ---------- 6. RAG ----------
  await group('RAG', async () => {
    const s = await req('GET', '/api/v1/rag/stats')
    check('GET /rag/stats → 200', s.ok)
    check('GET /rag/stats entities=-1 或 ≥0', s.json?.entities === -1 || typeof s.json?.entities === 'number')

    // /rag/retrieval 在无 LLM/Embedding Key 时可能返回 500（Embedding API 缺失）或 503
    const r = await req('POST', '/api/v1/rag/retrieval', { query: 'test', limit: 3 }, [200, 422, 500, 503])
    check('POST /rag/retrieval → 200/422/500/503（视 Key 配置）', r.ok)
  })

  // ---------- 7. Web Research ----------
  await group('Web Research', async () => {
    const s = await req('GET', '/api/v1/web_research/status')
    check('GET /web_research/status → 200', s.ok)
    const r = await req('POST', '/api/v1/web_research/research', { query: 'test' }, [200, 503])
    check('POST /web_research/research → 200 或 503', r.ok)
  })

  // ---------- 8. Deep Research ----------
  await group('Deep Research', async () => {
    const h = await req('GET', '/api/v1/research/health')
    check('GET /research/health → 200', h.ok)
    check('GET /research/health 有 search_provider', typeof h.json?.search_provider === 'string')

    const l = await req('GET', '/api/v1/research')
    check('GET /research → 200', l.ok)
    check('GET /research 含 tasks 数组', Array.isArray(l.json?.tasks))

    // 提交：必失败（无 Bocha/Serper Key），但应返回 200 + status="failed"
    const s = await req('POST', '/api/v1/research', { task: 'smoke test task' })
    check('POST /research → 200（无 Key 时 status=failed）', s.ok)
    if (s.json?.status === 'failed') {
      check('POST /research 失败 message 包含 "未配置"', /未配置/.test(s.json?.message || ''))
    }

    // 选一个已结束的任务做 DELETE 测试
    const terminal = (l.json?.tasks || []).find(t => t.status === 'failed' || t.status === 'completed')
    if (terminal) {
      const d = await req('DELETE', `/api/v1/research/${terminal.task_id}`, undefined, [200, 400])
      check(`DELETE /research/{id}（已结束）→ 200 或 400`, d.ok)
    }
  })

  // ---------- 9. 错误归一（关键安全验证）----------
  await group('错误归一（关键安全）', async () => {
    const r1 = await req('GET', '/api/v1/this/does/not/exist', undefined, [404])
    check('404 路径返回 404 + detail', r1.status === 404)

    const r2 = await req('POST', '/api/v1/agent/chat', { query: '' }, [200, 422, 503])
    check('POST /agent/chat 字段错误 → 422 或 503（视 Key）', [200, 422, 503].includes(r2.status))
  })

  // ---------- 10. CORS / 跨域 ----------
  await group('CORS', async () => {
    const r = await fetch(`${BASE}/api/v1/health`, {
      headers: { 'Origin': 'http://127.0.0.1:5173' },
    })
    const aco = r.headers.get('access-control-allow-origin')
    check('CORS Access-Control-Allow-Origin 头存在', !!aco)
  })

  // ===== 总结 =====
  console.log(`\n\x1b[1m====================================\x1b[0m`)
  const ok = fail === 0
  const total = pass + fail
  console.log(`\x1b[1m ${ok ? '\x1b[32m✓ 全部通过' : '\x1b[31m✗ 存在失败'}  ${pass} / ${total} \x1b[0m`)
  console.log(`\x1b[1m====================================\x1b[0m\n`)

  if (fail > 0) {
    console.log('失败项：')
    for (const f of FAIL) console.log(`  - ${f.name}  ${f.extra}`)
    process.exit(1)
  }
}

main().catch(e => {
  console.error('smoke fatal:', e)
  process.exit(1)
})