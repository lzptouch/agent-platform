#!/usr/bin/env node
/**
 * tests/scripts/capture_desktop_shot.mjs
 *
 * 通过 CDP 给 Electron 窗口截图（Node 22 自带全局 WebSocket，无需额外依赖）。
 * 诊断桌面端启动失败时用：窗口停在错误页时，截图里就是可读的错误原因。
 *
 * 用法：
 *   node tests/scripts/capture_desktop_shot.mjs --port 9222 --out tests/report/shots/desktop.png
 */
import { writeFile, mkdir } from 'node:fs/promises'
import path from 'node:path'

function parseArgs(argv) {
  const out = { port: 9222, out: 'tests/report/shots/desktop.png', wait: 0 }
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--port') out.port = Number(argv[++i])
    else if (argv[i] === '--out') out.out = argv[++i]
    else if (argv[i] === '--wait') out.wait = Number(argv[++i])
  }
  return out
}

/** 等待出现 page 目标（窗口）；错误页同样是 page 目标。 */
async function waitForPage(port, seconds) {
  const deadline = Date.now() + seconds * 1000
  while (Date.now() < deadline) {
    try {
      const targets = await listTargets(port)
      const pages = targets.filter((t) => t.type === 'page')
      if (pages.length > 0) return pages
    } catch {
      // 调试端口未就绪
    }
    await new Promise((r) => setTimeout(r, 1000))
  }
  return []
}

const opts = parseArgs(process.argv.slice(2))

async function listTargets(port) {
  const res = await fetch(`http://127.0.0.1:${port}/json/list`)
  return res.json()
}

function capture(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl)
    const timer = setTimeout(() => {
      try { ws.close() } catch { /* ignore */ }
      reject(new Error('截图超时（15s）'))
    }, 15000)
    ws.addEventListener('open', () => {
      ws.send(JSON.stringify({ id: 1, method: 'Page.captureScreenshot', params: { format: 'png' } }))
    })
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(String(ev.data))
      if (msg.id === 1) {
        clearTimeout(timer)
        try { ws.close() } catch { /* ignore */ }
        if (msg.error) reject(new Error(JSON.stringify(msg.error)))
        else resolve(msg.result.data)
      }
    })
    ws.addEventListener('error', (e) => {
      clearTimeout(timer)
      reject(new Error(`WebSocket 错误: ${e.message ?? e}`))
    })
  })
}

const pages = opts.wait > 0
  ? await waitForPage(opts.port, opts.wait)
  : (await listTargets(opts.port)).filter((t) => t.type === 'page')
if (pages.length === 0) {
  console.error(`[capture] 无 page 目标（端口 ${opts.port}）`)
  process.exit(2)
}
console.log(`[capture] 发现 ${pages.length} 个窗口目标`)
for (const t of pages) console.log(`  - ${t.title} :: ${t.url.slice(0, 120)}`)

const target = pages[0]
const data = await capture(target.webSocketDebuggerUrl)
const outPath = path.resolve(opts.out)
await mkdir(path.dirname(outPath), { recursive: true })
await writeFile(outPath, Buffer.from(data, 'base64'))
console.log(`[capture] 已保存: ${outPath}`)
