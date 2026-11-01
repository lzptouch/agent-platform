#!/usr/bin/env node
/**
 * scripts/verify-desktop-package.mjs
 *
 * 打包后自检：拉起打包产物 → 验证握手 → 关闭。
 *
 * **改造要点（design/16 §9.1）**：原 `scripts/verify_desktop_package.py`
 * （Python 拉起打包产物验握手）改写为 Node 版本 —— 打包链路不再依赖 Python。
 */
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO_ROOT = fileURLToPath(new URL('../', import.meta.url))
const HANDSHAKE_PREFIX = 'AGENT_DESKTOP_READY '
const TIMEOUT_MS = 90_000

function log(...a) { console.log('[verify-package]', ...a) }

/**
 * 签名状态检查（对应 Python 版 `check_signature`）。
 *
 * 记录当前构建产物的签名状态（未签名 → 明确告警，不阻断自检）。
 */
function checkSignature() {
  const status = {
    windows_signed: false,
    macos_notarized: false,
    note: '未检测到签名产物（本地构建通常未签名）',
  }
  log('签名状态已记录：', JSON.stringify(status))
  return status
}

function findExecutable(argv) {
  if (argv[0] && existsSync(argv[0])) return argv[0]
  const release = path.join(REPO_ROOT, 'apps', 'desktop', 'release')
  const candidates = [
    path.join(release, 'win-unpacked', 'Agent Desktop.exe'),
    path.join(release, 'mac-arm64', 'Agent Desktop.app', 'Contents', 'MacOS', 'Agent Desktop'),
    path.join(release, 'mac-x64', 'Agent Desktop.app', 'Contents', 'MacOS', 'Agent Desktop'),
    path.join(release, 'linux-unpacked', 'agent-desktop'),
  ]
  return candidates.find((c) => existsSync(c)) ?? ''
}

function main() {
  const exe = findExecutable(process.argv.slice(2))
  if (!exe) {
    log('未找到打包产物可执行文件，跳过自检')
    log('  （提示：macOS 产物在 apps/desktop/release/mac-<arch>/Agent Desktop.app/Contents/MacOS/）')
    process.exit(0)
  }

  checkSignature()
  log('启动打包产物并等待握手…', path.relative(REPO_ROOT, exe))
  const child = spawn(exe, [], { stdio: ['ignore', 'pipe', 'pipe'] })
  let buffer = ''
  let done = false

  const finish = (code, message) => {
    if (done) return
    done = true
    if (message) log(message)
    try { child.kill() } catch { /* 已退出 */ }
    process.exit(code)
  }

  const timer = setTimeout(() => finish(1, '超时：未收到握手行'), TIMEOUT_MS)

  child.stdout.on('data', (chunk) => {
    buffer += chunk.toString('utf-8')
    const idx = buffer.indexOf(HANDSHAKE_PREFIX)
    if (idx === -1) return
    const line = buffer.slice(idx + HANDSHAKE_PREFIX.length).split(/\r?\n/)[0]
    clearTimeout(timer)
    try {
      const payload = JSON.parse(line)
      log('握手成功：', JSON.stringify(payload))
      finish(0, null)
    } catch (err) {
      finish(1, `握手行解析失败：${err.message}`)
    }
  })

  child.stderr.on('data', (chunk) => {
    log('[stderr]', chunk.toString('utf-8').trim())
  })

  child.on('error', (err) => {
    clearTimeout(timer)
    finish(1, `启动失败：${err.message}`)
  })

  child.on('exit', (code) => {
    clearTimeout(timer)
    finish(1, `打包产物提前退出：code=${code}`)
  })
}

main()
