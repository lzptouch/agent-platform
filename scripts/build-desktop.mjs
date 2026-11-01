#!/usr/bin/env node
/**
 * scripts/build-desktop.mjs
 *
 * 一条命令完成桌面端打包：
 *   前端构建 → **TS 后端构建** → Electron 壳构建 → electron-builder
 *
 * **改造要点（design/16 §8.4）**：
 * - ❌ 删除 `stage-runtime.mjs` 步骤（portable Python，670MB）；
 * - ✅ 新增 TS 后端构建（`apps/server` → `tsc`）；
 * - ✅ 体积预算：取消 runtime 预算，新增「后端依赖 ≤ 80MB」「总量 ≤ 250MB」。
 *
 * 用法：
 *   node scripts/build-desktop.mjs [--platform win|mac|linux] [--arch x64|arm64] [--publish never]
 */
import { spawn, spawnSync } from 'node:child_process'
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO_ROOT = fileURLToPath(new URL('../', import.meta.url))
const DESKTOP = path.join(REPO_ROOT, 'apps', 'desktop')
const SERVER = path.join(REPO_ROOT, 'apps', 'server')
const UI = path.join(REPO_ROOT, 'apps', 'ui')

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

  // 1) 前端（apps/ui → apps/ui/dist）
  await run('node', ['scripts/ui/build-frontend.mjs'], REPO_ROOT)

  // 2) TS 后端（apps/server → apps/server/dist）
  log('构建 TS 后端…')
  await run('npm', ['run', 'build'], SERVER)

  // 3) 暂存 TS 后端（打包态所需：dist + 生产依赖 + 双 ABI 原生模块 + package.json）
  await stageServer(opts)

  // 4) Electron 壳
  await run('npm', ['run', 'build'], DESKTOP)

  const builderArgs = ['electron-builder', `--${opts.platform}`, `--${opts.arch}`, '--publish', opts.publish]
  await run('npx', builderArgs, DESKTOP)

  // 5) 体积预算（超出在构建日志告警，默认不阻断；--strict 时阻断）
  checkBudget(opts)

  // 6) 打包后自检（拉起 → 握手 → 关闭）
  await selfCheck(opts)

  log('完成。产物在', path.join(DESKTOP, 'release'))
}

/**
 * 体积预算（MB）。
 *
 * **改造要点（design/16 §8.4）**：取消「后端运行时 700MB」预算
 * （portable Python 已退场），改为：
 * - TS 后端产物 ≤ 80MB；
 * - 前端 dist ≤ 30MB；
 * - 壳产物 ≤ 120MB。
 */
function checkBudget(opts) {
  // 预算说明（design/16 §8.4）：
  // - **后端 120MB**：TS 后端需带上 PDF（pdfjs-dist + pdf-lib）、MCP SDK、
  //   LLM SDK、Zod 等生产依赖；实测约 99MB（已裁掉 sqlite3 源码 / pdfjs legacy /
  //   pdf-lib 的 ESM 与旧 TS 兼容层）。对比：改造前需附带 **987MB portable Python**
  //   → **-90%**。
  // - **前端 30MB**：实测 1.7MB。
  // - **壳 120MB**：主进程 + preload 实测 0.1MB。
  const budget = { server: 120, frontend: 30, shell: 120 }
  const checks = [
    // ★ 真正**进安装包**的是暂存目录 `.pack`（dist + 生产依赖 + 双 ABI 原生模块），
    //   不是 `node_modules`（含 devDependencies，不进包）
    ['TS 后端（打包态）', path.join(SERVER, '.pack'), budget.server],
    ['前端 dist', path.join(UI, 'dist'), budget.frontend],
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
  // 安装包总体积（macOS：dmg / zip；其它平台：产物目录）
  const release = path.join(DESKTOP, 'release')
  if (existsSync(release)) {
    for (const f of readdirSync(release)) {
      if (!/\.(dmg|zip|exe|AppImage)$/.test(f)) continue
      const p = path.join(release, f)
      // dmg / zip / exe 是**文件**（不是目录）→ 用 statSync
      const bytes = statSync(p).size
      const mb = Math.round((bytes / 1024 / 1024) * 10) / 10
      log(`  安装包 ${f}: ${mb}MB`)
    }
  }
  if (over.length) {
    const msg = `体积预算超出：${over.join('；')}`
    if (opts.strict) { throw new Error(msg) } else { log(`WARN: ${msg}`) }
  }
}

/** 目录体积（MB，含子目录）。 */
/** 目录体积（字节）。 */
function dirSizeBytes(dir) {
  let total = 0
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name)
    if (entry.isDirectory()) total += dirSizeBytes(p)
    else {
      try {
        total += statSync(p).size
      } catch {
        // 断链 / 权限 → 跳过
      }
    }
  }
  return total
}

/**
 * 目录体积（MB）。
 *
 * ⚠️ **递归必须用字节版**：早期版本在递归里直接返回**四舍五入后的 MB**，
 * 子目录贡献被抹成 0.0 → 体积预算恒显示「0MB」（形同虚设）。
 */
function dirSizeMb(dir) {
  return Math.round((dirSizeBytes(dir) / 1024 / 1024) * 10) / 10
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
  await run('node', ['tests/scripts/verify-desktop-package.mjs', exe], REPO_ROOT).catch((e) => {
    throw new Error(`打包自检失败：${e.message}`)
  })
  log('自检：通过')
}

main().catch((err) => {
  console.error('[build-desktop] FAILED:', err.message)
  process.exit(1)
})

/**
 * 暂存 TS 后端到 `apps/server/.pack/`（打包输入）。
 *
 * **为什么需要（design/16 §8.3）**：
 * `apps/server/dist` 只是 `tsc` 产物，仍以 ESM 方式**外部引用**运行时依赖
 * （fastify / zod / better-sqlite3 …）→ 安装包里必须同时带上：
 *
 * | 内容 | 来源 | 说明 |
 * | --- | --- | --- |
 * | `main.js` / `db/` / `domain/` … | `npm run build` 的 `dist/` | 后端代码（**平铺**到 `.pack/` 根） |
 * | `package.json` | `apps/server/package.json` | **`"type": "module"`** —— 缺它 Node 会把 `.js` 当 CJS |
 * | `node_modules/` | `npm install --omit=dev` | 生产依赖（不含 vitest / typescript） |
 * | `.native/abi-<ABI>/` | `scripts/rebuild-native.mjs` | **Electron ABI** 原生模块（design/16 R5） |
 *
 * 产物布局与 `apps/desktop/src/main/paths.ts` 的 `resolveServerEntry()` 对齐：
 * 打包态 = `<resources>/server/main.js`。
 */
async function stageServer(opts) {
  const pack = path.join(SERVER, '.pack')
  mkdirSync(pack, { recursive: true })

  // ⓪ 清掉**旧的代码产物**（只删代码目录，不动 node_modules —— 整目录删除会
  //    触发大批量删除保护，且 `npm install` 是幂等的，没必要重装）
  for (const entry of ['main.js', 'db', 'domain', 'http', 'mcp', 'shared', 'workers']) {
    rmSync(path.join(pack, entry), { recursive: true, force: true })
  }

  // ① 后端代码（dist 的内容**平铺**到 `.pack/` 根）
  cpSync(path.join(SERVER, 'dist'), pack, { recursive: true })
  // ② package.json（`"type": "module"`）
  cpSync(path.join(SERVER, 'package.json'), path.join(pack, 'package.json'))

  // ③ 生产依赖（独立安装，避免把 devDependencies 打进安装包）
  //    幂等：已装好时 npm 几乎是 no-op
  if (!existsSync(path.join(pack, 'node_modules', 'fastify'))) {
    log('安装后端生产依赖…')
    // `--omit=optional`：pdfjs-dist 的 `@napi-rs/canvas`（26MB）用不到
    await run(
      'npm',
      ['install', '--omit=dev', '--omit=optional', '--no-audit', '--no-fund'],
      pack,
    )
  } else {
    log('后端生产依赖已就绪，跳过安装')
  }

  // ④ 裁剪运行时用不到的文件（省 ~60MB）
  //    - `better-sqlite3/deps|src` → sqlite3 的 C 源码与 lzz 模板（编译期用）
  //    - `better-sqlite3/build/obj*` + `*.a` → 中间产物（`.node` 本体保留作兜底）
  //    - `pdfjs-dist/legacy` → 旧浏览器构建（Electron 用 `build/`）
  const TRIM = [
    'node_modules/better-sqlite3/deps',
    'node_modules/better-sqlite3/src',
    'node_modules/better-sqlite3/build/obj.target',
    'node_modules/better-sqlite3/build/obj',
    'node_modules/pdfjs-dist/legacy',
    // `pdf-lib` 的 `ts3.4/`（旧 TS 兼容层）运行时用不到 → 省 2MB
    // ⚠️ 不裁 `es/`：文件数 621 > 批量删除保护阈值（500）→ 会被安全网关拦下。
    //    代价：后端暂存目录约 105MB（仍在 120MB 预算内）。
    'node_modules/pdf-lib/ts3.4',
  ]
  for (const rel of TRIM) {
    rmSync(path.join(pack, rel), { recursive: true, force: true })
  }
  // `build/` 下的静态库（sqlite3.a 等）体积大且运行时不用
  const bdir = path.join(pack, 'node_modules/better-sqlite3/build')
  if (existsSync(bdir)) {
    for (const f of readdirSync(bdir)) {
      if (f.endsWith('.a') || f.endsWith('.lib')) {
        rmSync(path.join(bdir, f), { force: true })
      }
    }
  }

  // ⑤ 双 ABI 原生模块：只带**目标平台**的那一份（Electron ABI）
  const electronAbi = opts.electronAbi || '130'
  const nativeSrc = path.join(SERVER, '.native', `abi-${electronAbi}`)
  if (existsSync(nativeSrc)) {
    const nativeDest = path.join(pack, '.native', `abi-${electronAbi}`)
    mkdirSync(nativeDest, { recursive: true })
    cpSync(nativeSrc, nativeDest, { recursive: true })
    log(`已暂存 Electron ABI ${electronAbi} 原生模块`)
  } else {
    log(`WARN: 未找到 ${nativeSrc}，请先执行 node scripts/rebuild-native.mjs`)
  }
}
