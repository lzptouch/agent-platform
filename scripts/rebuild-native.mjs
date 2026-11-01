#!/usr/bin/env node
/**
 * scripts/rebuild-native.mjs
 *
 * 生成 **双 ABI** 的 better-sqlite3 原生模块（design/16 R5）。
 *
 * **为什么需要**：
 * - 桌面壳用 **Electron 33**（内含 Node 20.18 → `NODE_MODULE_VERSION 130`）；
 * - 开发态测试用 **系统 Node**（v22+ → `NODE_MODULE_VERSION 127/137`）；
 * - 两者 ABI 不同，同一份 `node_modules` 只能满足其一。
 *
 * **做法**：分别构建两遍，把产物**复制**到 `apps/server/.native/abi-<ABI>/`，
 * 运行时由 `apps/server/src/db/native.ts` 按 `process.versions.modules` 选择。
 *
 * 用法：
 *   node scripts/rebuild-native.mjs [--electron-version 33.4.11]
 */
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO_ROOT = fileURLToPath(new URL('../', import.meta.url))
const SERVER = path.join(REPO_ROOT, 'apps', 'server')
const NATIVE_DIR = path.join(SERVER, '.native')

function arg(name, fallback) {
  const i = process.argv.indexOf(name)
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback
}

const ELECTRON_VERSION = arg('--electron-version', '33.4.11')

function log(...a) { console.log('[rebuild-native]', ...a) }

function run(cmd, args, cwd) {
  log('RUN', cmd, args.join(' '), '(cwd:', cwd, ')')
  const r = spawnSync(cmd, args, { cwd, stdio: 'inherit', shell: process.platform === 'win32' })
  if (r.status !== 0) throw new Error(`${cmd} exited ${r.status}`)
}

/** Node ABI（当前 node 的 `process.versions.modules`）。 */
function nodeAbi() {
  return spawnSync(process.execPath, ['-p', 'process.versions.modules'], { encoding: 'utf-8' }).stdout.trim()
}

/** Electron ABI（Electron 33 → Node 20.18 → ABI 130）。 */
function electronAbi() {
  // Electron 主版本 → Node 版本 → ABI 的稳定映射（仅覆盖本项目支持的 Electron 33）
  const map = { 33: 130, 34: 133, 35: 133, 36: 136, 37: 136 }
  const major = Number(ELECTRON_VERSION.split('.')[0])
  return String(map[major] ?? 130)
}

const BUILT = path.join(SERVER, 'node_modules', 'better-sqlite3', 'build', 'Release', 'better_sqlite3.node')

function copyTo(abi) {
  const dir = path.join(NATIVE_DIR, `abi-${abi}`)
  fs.mkdirSync(dir, { recursive: true })
  const dest = path.join(dir, 'better_sqlite3.node')
  fs.copyFileSync(BUILT, dest)
  log(`已保存 ABI ${abi} → ${path.relative(REPO_ROOT, dest)}`)
  return dest
}

function main() {
  log('① 构建 Node 版…')
  run('npm', ['rebuild', 'better-sqlite3'], SERVER)
  const nAbi = nodeAbi()
  copyTo(nAbi)

  log('② 构建 Electron 版…')
  run('npx', ['@electron/rebuild', '-f', '-w', 'better-sqlite3', '-v', ELECTRON_VERSION], SERVER)
  const eAbi = electronAbi()
  copyTo(eAbi)

  log('③ 还原 Node 版到 build/Release（保证 vitest 可用）…')
  run('npm', ['rebuild', 'better-sqlite3'], SERVER)

  log(`完成：Node ABI=${nAbi} · Electron ABI=${eAbi} → ${path.relative(REPO_ROOT, NATIVE_DIR)}`)
}

try {
  main()
} catch (err) {
  console.error('[rebuild-native] FAILED:', err.message)
  process.exit(1)
}
