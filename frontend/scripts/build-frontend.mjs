#!/usr/bin/env node
/**
 * frontend/scripts/build-frontend.mjs
 *
 * 构建默认前端（web/vue-element-plus），并把产物拷贝到 frontend/dist/
 * 后端与 Nginx 只认 frontend/dist（参见 backend/app/main.py:30 与 deploy/frontend/Dockerfile）。
 *
 * 用法：
 *   node frontend/scripts/build-frontend.mjs
 *
 * 产物结构约束：必须是 index.html + 一级 assets/，且 index.html 中资源为 /assets/... 绝对路径
 */

import { rm, cp, mkdir, stat, readdir, readFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

// script 在 frontend/scripts/ 下 → 父目录即 frontend/
const FRONTEND_ROOT = fileURLToPath(new URL('../', import.meta.url))
// 唯一前端实现（默认前端）
const APP_REL = 'web/vue-element-plus'
const APP_ABS = path.join(FRONTEND_ROOT, APP_REL)
const DIST = path.join(FRONTEND_ROOT, 'dist')

function log(...a) { console.log('[build-frontend]', ...a) }

function run(cmd, args, cwd) {
  return new Promise((resolve, reject) => {
    log('RUN', cmd, args.join(' '), '(cwd:', cwd, ')')
    const child = spawn(cmd, args, { cwd, stdio: 'inherit', shell: process.platform === 'win32' })
    child.on('exit', code => code === 0 ? resolve() : reject(new Error(`${cmd} exited ${code}`)))
  })
}

async function assertArtifacts(distDir) {
  const indexHtml = path.join(distDir, 'index.html')
  if (!existsSync(indexHtml)) throw new Error(`产物校验失败：缺 ${indexHtml}`)
  const assetsDir = path.join(distDir, 'assets')
  const assetsStat = await stat(assetsDir).catch(() => null)
  if (!assetsStat || !assetsStat.isDirectory()) throw new Error(`产物校验失败：缺 ${assetsDir}`)
  const html = await readFile(indexHtml, 'utf8')
  if (!html.includes('/assets/')) log('WARN: index.html 中未见 /assets/ 引用，请确认 base 为 /')
  log('产物校验通过：', indexHtml, '+', assetsDir)
}

async function main() {
  const distSrc = path.join(APP_ABS, 'dist')

  log('前端实现:', APP_REL, '→', APP_ABS)

  // 1) 校验实现目录与依赖清单
  if (!existsSync(APP_ABS)) throw new Error(`实现目录不存在: ${APP_ABS}`)
  const pkgPath = path.join(APP_ABS, 'package.json')
  if (!existsSync(pkgPath)) throw new Error(`缺 package.json: ${pkgPath}`)

  // 2) 安装依赖（若 node_modules 不存在）
  const nm = path.join(APP_ABS, 'node_modules')
  if (!existsSync(nm)) {
    log('安装依赖…')
    await run('npm', ['ci', '--no-audit', '--no-fund'], APP_ABS)
  } else {
    log('node_modules 已存在，跳过安装')
  }

  // 3) 构建
  log('开始构建…')
  await run('npm', ['run', 'build'], APP_ABS)

  // 4) 校验产物
  if (!existsSync(distSrc)) throw new Error(`构建产物不存在: ${distSrc}`)
  await assertArtifacts(distSrc)

  // 5) 清空目标 dist 并拷贝
  log('拷贝到', DIST)
  await rm(DIST, { recursive: true, force: true })
  await mkdir(DIST, { recursive: true })
  await cp(distSrc, DIST, { recursive: true })

  // 6) 拷贝桌面端启动页（壳在窗口创建前加载 splash.html，缺失会导致启动失败）
  const splash = path.join(FRONTEND_ROOT, 'splash.html')
  if (existsSync(splash)) {
    await cp(splash, path.join(DIST, 'splash.html'))
    log('已拷贝启动页 →', path.join(DIST, 'splash.html'))
  } else {
    log('WARN: 未找到 frontend/splash.html，桌面端启动页将加载失败')
  }

  const files = await readdir(DIST)
  log('完成:', DIST, '含', files.length, '顶层条目')
}

main().catch(err => {
  console.error('[build-frontend] FAILED:', err.message)
  process.exit(1)
})
