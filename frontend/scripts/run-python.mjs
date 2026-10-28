#!/usr/bin/env node
/**
 * frontend/scripts/run-python.mjs
 *
 * 跨平台调用后端虚拟环境里的 Python。
 *
 * 背景：此前 package.json 里的 e2e 脚本写死了 `backend/.venv/bin/python`（Linux 路径），
 * 在 Windows 上必然失败。这里统一做解释器解析：
 *   1) backend/.venv/Scripts/python.exe（Windows）
 *   2) backend/.venv/bin/python（POSIX）
 *   3) 系统 PATH 上的 python / python3
 *
 * 用法：
 *   node frontend/scripts/run-python.mjs backend/scripts/api_test.py [args...]
 */
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const FRONTEND_ROOT = fileURLToPath(new URL('../', import.meta.url))
const REPO_ROOT = path.resolve(FRONTEND_ROOT, '..')

function resolvePython() {
  const candidates = [
    path.join(REPO_ROOT, 'backend', '.venv', 'Scripts', 'python.exe'),
    path.join(REPO_ROOT, 'backend', '.venv', 'bin', 'python'),
    path.join(REPO_ROOT, 'backend', '.venv', 'bin', 'python3'),
  ]
  for (const c of candidates) if (existsSync(c)) return c
  return process.platform === 'win32' ? 'python' : 'python3'
}

const python = resolvePython()
const args = process.argv.slice(2)
if (args.length === 0) {
  console.error('[run-python] 用法: node run-python.mjs <script.py> [args...]')
  process.exit(2)
}

console.log('[run-python] 解释器:', python, '脚本:', args[0])
const child = spawn(python, args, {
  cwd: REPO_ROOT,
  stdio: 'inherit',
  shell: process.platform === 'win32',
})
child.on('exit', (code) => process.exit(code ?? 0))
child.on('error', (err) => {
  console.error('[run-python] 启动失败:', err.message)
  process.exit(127)
})
