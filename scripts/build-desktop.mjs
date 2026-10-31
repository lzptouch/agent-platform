#!/usr/bin/env node
/**
 * scripts/build-desktop.mjs
 *
 * 一条命令完成桌面端打包：
 *   前端构建 → portable 运行时组装 → electron-builder
 *
 * 用法：
 *   node scripts/build-desktop.mjs [--platform win|mac|linux] [--arch x64|arm64] [--publish never]
 */
import { spawn, spawnSync } from 'node:child_process'
import { existsSync, readdirSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO_ROOT = fileURLToPath(new URL('../', import.meta.url))
const DESKTOP = path.join(REPO_ROOT, 'frontend', 'desktop')

function parseArgs(argv) {
  const out = { platform: process.platform === 'win32' ? 'win' : process.platform, arch: 'x64', publish: 'never', strict: false, skipSelfCheck: false }
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--platform') out.platform = argv[++i]
    else if (argv[i] === '--arch') out.arch = argv[++i]
    else if (argv[i] === '--publish') out.publish = argv[++i]
    else if (argv[i] === '--strict') out.strict = true
    else if (argv[i] === '--skip-self-check') out.skipSelfCheck = true
  }
  return out
}

function log(...a) { console.log('[build-desktop]', ...a) }

/** 系统里是否存在该可执行文件（用于 python3 → python 回退探测）。 */
function hasBinary(name) {
  try {
    const probe = process.platform === 'win32' ? 'where' : 'command'
    const res = spawnSync(probe, process.platform === 'win32' ? [name] : ['-v', name], {
      stdio: 'ignore',
      shell: process.platform === 'win32',
    })
    return res.status === 0
  } catch {
    return false
  }
}

function run(cmd, args, cwd) {
  return new Promise((resolve, reject) => {
    log('RUN', cmd, args.join(' '), '(cwd:', cwd, ')')
    const child = spawn(cmd, args, { cwd, stdio: 'inherit', shell: process.platform === 'win32' })
    child.on('exit', (code) => (code === 0 ? resolve() : reject(new Error(`${cmd} exited ${code}`))))
  })
}

async function main() {
  const opts = parseArgs(process.argv.slice(2))
  log('平台:', opts.platform, '架构:', opts.arch)

  // 1) 前端
  await run('node', ['frontend/scripts/build-frontend.mjs'], REPO_ROOT)

  // 2) portable 运行时（若 STAGE 不存在则提示；运行时体积大，由专门步骤准备）
  const stage = path.join(DESKTOP, '.stage', 'runtime')
  if (!existsSync(stage)) {
    log('未检测到 portable 运行时，执行 stage-runtime …')
    await run('node', ['scripts/stage-runtime.mjs', '--platform', opts.platform], REPO_ROOT)
  }

  // 3) Electron 壳
  await run('npm', ['run', 'build'], DESKTOP)

  const builderArgs = ['electron-builder', `--${opts.platform}`, `--${opts.arch}`, '--publish', opts.publish]
  await run('npx', builderArgs, DESKTOP)

  // 4) 体积预算（超出在构建日志告警，默认不阻断；--strict 时阻断）
  checkBudget(opts)

  // 5) 打包后自检（拉起 → 握手 → 关闭）
  await selfCheck(opts)

  log('完成。产物在', path.join(DESKTOP, 'release'))
}

/**
 * 体积预算（MB）：后端运行时 · 前端 dist · 壳。
 *
 * **P6-01 决策（2026-10-30）**：运行时预算由 **350 → 700**。
 *
 * 依据：经 `stage-runtime.mjs` 的确定性裁剪（剔除 Playwright 177MB、
 * ``__pycache__``/``*.pyc`` 70MB、kubernetes、tests/notebooks）后，
 * 实测运行时 **670MB**；剩余主体是**三个真功能**的依赖——
 * PDF 解析（pymupdf 110MB）、向量库（milvus_lite 82MB + chromadb 49MB）、
 * 嵌入推理（onnxruntime 75MB）。**在不裁功能的前提下 350MB 不可达**。
 *
 * 若要回到 350MB，必须**裁功能**（桌面端不提供 PDF 解析 / 不内置向量库）
 * —— 属产品决策，已登记在 `doc/design/09` §五。
 */
function checkBudget(opts) {
  const budget = { runtime: 700, frontend: 30, shell: 120 }
  const checks = [
    ['后端运行时', path.join(DESKTOP, '.stage', 'runtime'), budget.runtime],
    ['前端 dist', path.join(REPO_ROOT, 'frontend', 'dist'), budget.frontend],
    ['壳产物', path.join(DESKTOP, 'dist-main'), budget.shell],
  ]
  let over = []
  for (const [name, dir, limit] of checks) {
    if (!existsSync(dir)) continue
    const mb = dirSizeMb(dir)
    const ok = mb <= limit
    log(`  ${name}: ${mb}MB / 预算 ${limit}MB ${ok ? '✓' : '✗ 超出'}`)
    if (!ok) over.push(`${name} ${mb}MB > ${limit}MB`)
  }
  if (over.length) {
    const msg = `体积预算超出：${over.join('；')}`
    if (opts.strict) { throw new Error(msg) } else { log(`WARN: ${msg}`) }
  }
}

/** 目录体积（MB，含子目录）。 */
function dirSizeMb(dir) {
  let total = 0
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name)
    if (entry.isDirectory()) total += dirSizeMb(p)
    else total += statSync(p).size
  }
  return Math.round(total / 1024 / 1024 * 10) / 10
}

/** 找到打包产物的可执行文件（按平台/架构）；找不到返回空串。 */
function findExecutable(platform, arch) {
  const release = path.join(DESKTOP, 'release')
  if (platform === 'win') {
    const exe = path.join(release, 'win-unpacked', 'Agent Desktop.exe')
    return existsSync(exe) ? exe : ''
  }
  if (platform === 'mac') {
    // macOS 的可执行文件在 .app 包内部：Contents/MacOS/<CFBundleExecutable>
    const exe = path.join(release, `mac-${arch}`, 'Agent Desktop.app', 'Contents', 'MacOS', 'Agent Desktop')
    return existsSync(exe) ? exe : ''
  }
  const exe = path.join(release, 'linux-unpacked', 'agent-desktop')
  return existsSync(exe) ? exe : ''
}

/** 打包后自检：拉起 → 握手 → 关闭（失败则非零退出）。 */
async function selfCheck(opts) {
  if (opts.skipSelfCheck) return
  const exe = findExecutable(opts.platform, opts.arch)
  if (!exe) {
    log(`自检：未找到 ${opts.platform}/${opts.arch} 的可执行文件，跳过`)
    log('  （提示：macOS 产物在 release/mac-<arch>/Agent Desktop.app/Contents/MacOS/）')
    return
  }
  log(`自检：启动打包产物并验证握手…（${path.relative(REPO_ROOT, exe)}）`)
  // **E9**：macOS/Linux 通常只有 python3（没有 python）→ ENOENT 自检失败。
  // 探测 python3 → python 回退，并允许用 PYTHON 环境变量覆盖。
  const pythonBin = process.env.PYTHON || (hasBinary('python3') ? 'python3' : 'python')
  await run(pythonBin, ['scripts/verify_desktop_package.py'], REPO_ROOT).catch((e) => {
    throw new Error(`打包自检失败：${e.message}`)
  })
  log('自检：通过')
}

main().catch((err) => {
  console.error('[build-desktop] FAILED:', err.message)
  process.exit(1)
})
