/**
 * LLM 端到端验收（Playwright 驱动**真实 Electron 应用**）。
 *
 * **做���**：
 * 1. 拉起**安装包**（`apps/desktop/release/mac-arm64/Agent Desktop.app`）；
 * 2. 用真实鼠标/键盘事件在界面上**输入任务**、**点击发送**；
 * 3. 等待大模型返回，**断言**结果符合预期；
 * 4. 逐页截图，产出 L3 视觉证据。
 *
 * **证据**：`doc/test-runs/P9-final/screenshots/*.png` + `doc/test-runs/P9-final/raw/e2e-llm.log`
 *
 * 用法：
 *   cd apps/desktop && node ../../tests/e2e/llm-e2e.mjs
 */
import { _electron as electron } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const REPO = path.resolve(HERE, '..', '..')
const SHOTS = path.join(REPO, 'doc/test-runs/P9-final/screenshots')
const RAW = path.join(REPO, 'doc/test-runs/P9-final/raw')

fs.mkdirSync(SHOTS, { recursive: true })
fs.mkdirSync(RAW, { recursive: true })

/** 找安装包可执行文件（macOS / Linux / Windows）。 */
function findApp() {
  const release = path.join(REPO, 'apps/desktop/release')
  const candidates = [
    'mac-arm64/Agent Desktop.app/Contents/MacOS/Agent Desktop',
    'mac/Agent Desktop.app/Contents/MacOS/Agent Desktop',
    'linux-unpacked/agent-desktop',
    'win-unpacked/Agent Desktop.exe',
  ]
  for (const c of candidates) {
    const p = path.join(release, c)
    if (fs.existsSync(p)) return p
  }
  return ''
}

const APP = findApp()
if (!APP) {
  console.error('[e2e] 未找到安装包 —— 先跑 `node scripts/build-desktop.mjs --platform mac --arch arm64`')
  process.exit(2)
}

/** 大模型用的环境变量（安装包内读不到仓库根的 .env → 显式注入）。 */
function llmEnv() {
  const dotenv = path.join(REPO, '.env')
  const out = {}
  if (fs.existsSync(dotenv)) {
    for (const line of fs.readFileSync(dotenv, 'utf-8').split(/\r?\n/)) {
      const t = line.trim()
      if (!t || t.startsWith('#')) continue
      const i = t.indexOf('=')
      if (i <= 0) continue
      out[t.slice(0, i).trim()] = t.slice(i + 1).trim()
    }
  }
  const env = { ...process.env, ...out }
  return {
    DASHSCOPE_API_KEY: env.DASHSCOPE_API_KEY || '',
    DASHSCOPE_BASE_URL: env.DASHSCOPE_BASE_URL || '',
    LLM_API_KEY: env.LLM_API_KEY || '',
    LLM_BASE_URL: env.LLM_BASE_URL || '',
    DEFAULT_MODEL: env.DEFAULT_MODEL || 'qwen-plus',
    RAG_MODEL: env.RAG_MODEL || 'qwen-plus',
    ANSWER_MODEL: env.ANSWER_MODEL || 'qwen-plus',
  }
}

const log = []
function say(...a) {
  const line = a.join(' ')
  console.log(line)
  log.push(line)
}

let step = 0
async function shot(page, name) {
  step += 1
  const file = path.join(SHOTS, `${String(step).padStart(2, '0')}-${name}.png`)
  await page.screenshot({ path: file, fullPage: false })
  say(`    📸 ${path.relative(REPO, file)}`)
  return file
}

const results = []
function record(name, ok, detail) {
  results.push({ name, ok, detail })
  say(`  ${ok ? '✅' : '❌'} ${name}${detail ? ` —— ${detail}` : ''}`)
}

/**
 * 生成一个最小但**合法**的 PDF（内含可被抽取的文本）。
 *
 * 后端 RAG 入库只扫 `pdf_dir` 下的 `*.pdf`，并用 `(... ) Tj` 抽取文本 →
 * 这个 PDF 能真正走通「抽取 → 切块 → Embedding → 入库 → 检索」全链路。
 */
function makePdf(lines) {
  const content = lines
    .map((t, i) => `BT /F1 14 Tf 60 ${740 - i * 20} Td (${t}) Tj ET`)
    .join('\n')
  const objs = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${content.length} >>\nstream\n${content}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ]
  let pdf = '%PDF-1.4\n'
  const offsets = []
  objs.forEach((body, i) => {
    offsets.push(pdf.length)
    pdf += `${i + 1} 0 obj\n${body}\nendobj\n`
  })
  const xrefPos = pdf.length
  pdf += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n`
  for (const off of offsets) pdf += `${String(off).padStart(10, '0')} 00000 n \n`
  pdf += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${xrefPos}\n%%EOF\n`
  return Buffer.from(pdf, 'latin1')
}

async function main() {
  const userData = path.join('/tmp', `agent-e2e-${Date.now()}`)
  say(`[e2e] 启动安装包：${path.relative(REPO, APP)}`)
  say(`[e2e] 独立 userData：${userData}`)

  const app = await electron.launch({
    executablePath: APP,
    args: [`--user-data-dir=${userData}`],
    env: { ...process.env, ...llmEnv() },
    timeout: 60000,
  })

  // 首屏是**启动页**（file://…/splash.html）；主窗口要等后端握手完成后才出现
  // → 轮询窗口列表，认出 URL 为 http://127.0.0.1:<port>/ 的那个
  let page = null
  const t0 = Date.now()
  while (Date.now() - t0 < 90000 && !page) {
    for (const w of app.windows()) {
      const u = w.url()
      if (u.startsWith('http://127.0.0.1')) {
        page = w
        break
      }
    }
    if (!page) await new Promise((r) => setTimeout(r, 800))
  }
  if (!page) {
    const urls = app.windows().map((w) => w.url())
    throw new Error(`未等到主窗口（现有窗口：${urls.join(' | ')}）`)
  }
  say(`[e2e] 主窗口就绪：${page.url()}（等待 ${((Date.now() - t0) / 1000).toFixed(1)}s）`)

  page.on('console', (m) => {
    if (m.type() === 'error') say(`    [renderer error] ${m.text().slice(0, 200)}`)
  })
  page.on('pageerror', (e) => say(`    [pageerror] ${String(e).slice(0, 200)}`))

  await page.setViewportSize({ width: 1440, height: 900 })
  await page.waitForLoadState('domcontentloaded')

  // ---- 步骤 1：工作台就绪 ----
  await page.waitForSelector('textarea', { timeout: 45000 })
  await page.waitForTimeout(1200)
  await shot(page, 'workspace-empty')
  record('工作台渲染（输入框可见）', true, page.url())

  // ---- 步骤 2：大模型对话（核心）----
  const PROMPT = '用一句话回答：中国的首都是哪里？只回答城市名。'
  const box = page.locator('textarea').first()
  await box.click()
  await box.fill(PROMPT)
  await shot(page, 'workspace-typed')
  await box.press('Enter')

  say('[e2e] 已发送，等待模型返回…')
  const tStart = Date.now()
  let answered = false
  try {
    // 助手气泡：等出现「非用户」角色的消息内容
    await page.waitForFunction(
      () => {
        const txt = document.body.innerText || ''
        return /北京/.test(txt)
      },
      { timeout: 120000 },
    )
    answered = true
  } catch {
    /* 落到下面的兜底判定 */
  }
  const cost = ((Date.now() - tStart) / 1000).toFixed(1)
  await page.waitForTimeout(800)
  await shot(page, 'workspace-answer')

  const bodyText = await page.evaluate(() => document.body.innerText)
  const hasAnswer = /北京/.test(bodyText)
  record('大模型问答返回正确内容', answered && hasAnswer, `耗时 ${cost}s，包含「北京」=${hasAnswer}`)

  // ---- 步骤 3：多轮追问（会话上下文）----
  const Q2 = '我刚才问的是哪个城市？只回答城市名。'
  await box.click()
  await box.fill(Q2)
  await box.press('Enter')
  say('[e2e] 已发送追问，等待…')
  let ctxOk = false
  try {
    await page.waitForFunction(
      () => {
        const t = document.body.innerText || ''
        return (t.match(/北京/g) || []).length >= 2
      },
      { timeout: 90000 },
    )
    ctxOk = true
  } catch {
    /* 忽略 */
  }
  await page.waitForTimeout(600)
  await shot(page, 'workspace-followup')
  record('多轮上下文（能记住上一轮）', ctxOk)

  // ---- 步骤 4：新建任务（会话隔离）----
  const newTask = page.getByText('新建任务', { exact: true }).first()
  if (await newTask.count()) {
    await newTask.click()
    await page.waitForTimeout(900)
    await shot(page, 'workspace-new-task')
    record('新建任务按钮可用', true)
  } else {
    record('新建任务按钮可用', false, '未找到按钮')
  }

  // ---- 步骤 5：Skill 选择（走大模型做技能匹配）----
  try {
    const skillChip = page.getByText('更多', { exact: false }).first()
    if (await skillChip.count()) {
      await skillChip.click()
      await page.waitForTimeout(800)
      await shot(page, 'workspace-command-panel')
      record('命令/技能面板可打开', true)
      await page.keyboard.press('Escape')
      await page.waitForTimeout(400)
    } else {
      record('命令/技能面板可打开', false, '未找到入口')
    }
  } catch (err) {
    record('命令/技能面板可打开', false, String(err).slice(0, 100))
  }

  // ---- 步骤 6：任务模式切换（plan / work）----
  try {
    const modeSel = page.getByText('对话', { exact: true }).first()
    if (await modeSel.count()) {
      await modeSel.click()
      await page.waitForTimeout(700)
      await shot(page, 'workspace-mode-menu')
      record('任务模式菜单可打开', true)
      await page.keyboard.press('Escape')
    } else {
      record('任务模式菜单可打开', false, '未找到模式选择')
    }
  } catch (err) {
    record('任务模式菜单可打开', false, String(err).slice(0, 100))
  }

  // ---- 步骤 7：RAG 链路（Embedding + 混合检索）----
  // 页面上的「RAG 知识库」也是同一后端 → 直接调 API 验证 LLM 链路
  try {
    const origin = new URL(page.url()).origin
    // 造一份真实 PDF 放进应用的 pdf 目录（后端入库只扫 *.pdf）
    const pdfDir = path.join(userData, 'data', 'pdf')
    fs.mkdirSync(pdfDir, { recursive: true })
    fs.writeFileSync(
      path.join(pdfDir, 'agent-e2e-rag.pdf'),
      makePdf([
        'Agent Platform runs space binding is locked when a run is created.',
        'The run workspace id is written into meta and never changes.',
        'Current working directory switching does not affect running tasks.',
      ]),
    )
    const ingest = await page.evaluate(async (o) => {
      const res = await fetch(o + '/api/v1/rag/ingest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recreate: true }),
      })
      return { status: res.status, body: (await res.text()).slice(0, 200) }
    }, origin)
    say(`    · RAG 入库 → HTTP ${ingest.status}`)

    const retrieval = await page.evaluate(async (o) => {
      const res = await fetch(o + '/api/v1/rag/retrieval', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: 'run workspace binding locked when created', limit: 3 }),
      })
      return { status: res.status, body: (await res.text()).slice(0, 400) }
    }, origin)
    let hits = []
    try {
      const parsed = JSON.parse(retrieval.body)
      hits = parsed.chunks || parsed.items || parsed.results || []
    } catch { /* 忽略 */ }
    await shot(page, 'rag-ingest-retrieval')
    record(
      'RAG 入库 + 检索（Embedding 链路）',
      ingest.status === 200 && retrieval.status === 200,
      `ingest=${ingest.status} retrieval=${retrieval.status} 命中 ${hits.length} 条`,
    )
  } catch (err) {
    record('RAG 入库 + 检索（Embedding 链路）', false, String(err).slice(0, 140))
  }

  // ---- 步骤 8：逐页巡检（功能面）----
  const PAGES = [
    ['/admin/capabilities', 'capabilities'],
    ['/admin/capabilities?tab=skills', 'skills'],
    ['/admin/knowledge', 'rag'],
    ['/admin/research', 'research'],
    ['/admin/web', 'web-research'],
    ['/admin/schedules', 'schedules'],
    ['/admin/status', 'system-status'],
    ['/admin/artifacts', 'files'],
    ['/admin/roles', 'roles'],
    ['/admin/plugins', 'plugins'],
    ['/admin/settings', 'settings'],
    ['/admin/desktop', 'desktop-settings'],
    ['/spaces', 'spaces'],
  ]
  for (const [route, name] of PAGES) {
    try {
      await page.goto(`http://127.0.0.1:${new URL(page.url()).port}${route}`, {
        waitUntil: 'domcontentloaded',
        timeout: 20000,
      })
      await page.waitForTimeout(1400)
      const txt = (await page.evaluate(() => document.body.innerText)) || ''
      const blank = txt.trim().length < 20
      await shot(page, `page-${name}`)
      record(`页面 ${route}`, !blank, blank ? '**白屏**（内容 < 20 字符）' : `内容 ${txt.trim().length} 字符`)
    } catch (err) {
      await shot(page, `page-${name}-error`)
      record(`页面 ${route}`, false, String(err).slice(0, 120))
    }
  }

  // ---- 收尾 ----
  await app.close()
  fs.writeFileSync(path.join(RAW, 'e2e-llm.log'), log.join('\n') + '\n', 'utf-8')

  const ok = results.filter((r) => r.ok).length
  say('')
  say('════════════════════════════════════════')
  say(`  E2E 结果：${ok} / ${results.length} 通过`)
  for (const r of results.filter((x) => !x.ok)) say(`    ❌ ${r.name} ${r.detail || ''}`)
  say('════════════════════════════════════════')
  fs.writeFileSync(
    path.join(RAW, 'e2e-llm.json'),
    JSON.stringify(results, null, 2),
    'utf-8',
  )
  process.exit(results.every((r) => r.ok) ? 0 : 1)
}

main().catch((err) => {
  console.error('[e2e] 失败：', err)
  fs.writeFileSync(path.join(RAW, 'e2e-llm.log'), log.join('\n') + `\n[e2e] FAILED: ${err}\n`, 'utf-8')
  process.exit(1)
})
