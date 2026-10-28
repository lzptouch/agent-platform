#!/usr/bin/env node
/**
 * scripts/stage-runtime.mjs
 *
 * 组装 portable Python 运行时到 frontend/desktop/.stage/runtime/：
 *   1. 下载/解压 python-build-standalone
 *   2. pip install --target <site-packages> -r backend/requirements.txt
 *   3. 复制 backend/app、backend/skills、backend/scripts 到 runtime/agent/
 *   4. 生成 runtime/agent/desktop.json（版本、构建时间、依赖清单 hash）
 *
 * 用法：
 *   node scripts/stage-runtime.mjs [--platform win] [--python-version 3.11]
 *   node scripts/stage-runtime.mjs --from-venv     # 用仓库 backend/.venv 兜底组装（离线可用）
 *
 * 平台目录差异：Windows site-packages 在 Lib/，macOS/Linux 在 lib/pythonX.Y/。
 */
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { cp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import crypto from 'node:crypto'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO_ROOT = fileURLToPath(new URL('../', import.meta.url))
const STAGE = path.join(REPO_ROOT, 'frontend', 'desktop', '.stage', 'runtime')
const REQ = path.join(REPO_ROOT, 'backend', 'requirements.txt')

function parseArgs(argv) {
  const out = {
    platform: process.platform === 'win32' ? 'win' : process.platform,
    pythonVersion: '3.11',
    fromVenv: false,
  }
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--platform') out.platform = argv[++i]
    else if (argv[i] === '--python-version') out.pythonVersion = argv[++i]
    else if (argv[i] === '--from-venv') out.fromVenv = true
  }
  return out
}

function log(...a) { console.log('[stage-runtime]', ...a) }

function run(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    log('RUN', cmd, args.join(' '))
    const child = spawn(cmd, args, { stdio: 'inherit', shell: process.platform === 'win32', ...opts })
    child.on('exit', (code) => (code === 0 ? resolve() : reject(new Error(`${cmd} exited ${code}`))))
  })
}

/** 目标平台的 site-packages 相对路径。 */
function sitePackagesDir(platform, pythonVersion) {
  return platform === 'win'
    ? path.join(STAGE, 'Lib', 'site-packages')
    : path.join(STAGE, 'lib', `python${pythonVersion}`, 'site-packages')
}

function runtimePythonBin(platform) {
  return platform === 'win'
    ? path.join(STAGE, 'python.exe')
    : path.join(STAGE, 'bin', 'python3')
}

/**
 * 离线兜底：用仓库 backend/.venv 组装**standalone 布局**的运行时。
 *
 * 背景：portable Python 官方发布在 GitHub（astral-sh/python-build-standalone），
 * 受限网络下不可达。本模式改为：
 *   1) 从 ``backend/.venv/pyvenv.cfg`` 的 ``home`` 找到**基础解释器**，复制
 *      ``python.exe`` + 标准库（``Lib`` / ``DLLs`` / ``python3*.dll``）；
 *   2) 把 venv 的 ``site-packages`` 覆盖到运行时的 site-packages 位置；
 *   3) 复制后端代码到 ``runtime/agent/``。
 *
 * 产出的目录布局与 python-build-standalone 一致，应用侧无需改动：
 *   ``runtime/python.exe`` · ``runtime/Lib/site-packages`` · ``runtime/agent``
 *
 * 代价：体积更大（本机 site-packages 约 745MB），且绑定本机 Python 小版本。
 * 生产发布应回到官方 portable Python + 依赖裁剪（见 doc/roadmap/12 §6）。
 */
async function stageFromVenv(platform, pythonVersion) {
  const venv = path.join(REPO_ROOT, 'backend', '.venv')
  const venvPy = platform === 'win'
    ? path.join(venv, 'Scripts', 'python.exe')
    : path.join(venv, 'bin', 'python3')
  if (!existsSync(venvPy)) {
    throw new Error(`未找到仓库虚拟环境：${venvPy}（请先创建 backend/.venv）`)
  }
  const cfg = await readFile(path.join(venv, 'pyvenv.cfg'), 'utf-8')
  const home = (/^home\s*=\s*(.+)$/m.exec(cfg) || [])[1]
  if (!home || !existsSync(home)) {
    throw new Error('无法从 backend/.venv/pyvenv.cfg 解析基础解释器目录（home 缺失）')
  }
  log('从本地虚拟环境组装：', venvPy, '→ 基础解释器', home)

  await rm(STAGE, { recursive: true, force: true })
  await mkdir(STAGE, { recursive: true })

  // 1) 基础解释器 + 标准库
  if (platform === 'win') {
    await cp(path.join(home, 'python.exe'), path.join(STAGE, 'python.exe'))
    for (const dll of ['python311.dll', 'python3.dll']) {
      const src = path.join(home, dll)
      if (existsSync(src)) await cp(src, path.join(STAGE, dll))
    }
    await cp(path.join(home, 'DLLs'), path.join(STAGE, 'DLLs'), { recursive: true })
    await cp(path.join(home, 'Lib'), path.join(STAGE, 'Lib'), { recursive: true })
  } else {
    await cp(path.join(home, 'bin'), path.join(STAGE, 'bin'), { recursive: true })
    await cp(path.join(home, 'lib'), path.join(STAGE, 'lib'), { recursive: true })
  }

  // 2) 依赖：venv 的 site-packages 覆盖到运行时位置
  const spSrc = platform === 'win'
    ? path.join(venv, 'Lib', 'site-packages')
    : path.join(venv, 'lib', `python${pythonVersion}`, 'site-packages')
  const spDst = sitePackagesDir(platform, pythonVersion)
  await mkdir(spDst, { recursive: true })
  log('复制依赖：', spSrc, '→', spDst)
  await cp(spSrc, spDst, { recursive: true })

  // 3) 后端代码与技能（alembic.ini 必须一起复制：scripts/migrate.py 依赖它，
  //    缺失会导致打包态启动时迁移失败 → 直接中止）
  const agentDir = path.join(STAGE, 'agent')
  await mkdir(agentDir, { recursive: true })
  for (const item of ['app', 'skills', 'scripts']) {
    await cp(path.join(REPO_ROOT, 'backend', item), path.join(agentDir, item), { recursive: true })
  }
  for (const file of ['alembic.ini']) {
    const src = path.join(REPO_ROOT, 'backend', file)
    if (existsSync(src)) await cp(src, path.join(agentDir, file))
  }

  // 4) 清单
  const reqHash = crypto.createHash('sha256').update(await readFile(REQ)).digest('hex').slice(0, 16)
  await writeFile(
    path.join(agentDir, 'desktop.json'),
    JSON.stringify(
      {
        version: '1.1.0',
        built_at: new Date().toISOString(),
        platform,
        python_version: pythonVersion,
        requirements_sha256: reqHash,
        runtime_source: 'local-venv',
      },
      null,
      2,
    ),
  )
  log('完成（离线兜底）:', STAGE)
}

async function stageRuntime(opts) {
  const { platform, pythonVersion, fromVenv } = opts
  log('目标平台:', platform, 'Python:', pythonVersion)

  // 0) 离线兜底：直接用仓库虚拟环境组装
  if (fromVenv) {
    await stageFromVenv(platform, pythonVersion)
    return
  }

  // 1) portable Python（此处约定运行时已由外部放入 STAGE；CI 中由下载步骤提供）
  if (!existsSync(runtimePythonBin(platform))) {
    throw new Error(
      `未找到 portable Python 运行时：${runtimePythonBin(platform)}\n` +
      '请先将 python-build-standalone 解压到 frontend/desktop/.stage/runtime/（见 doc/design/02 §7.1 步骤 1）。',
    )
  }
  log('运行时存在:', runtimePythonBin(platform))

  // 2) 依赖
  const sitePackages = sitePackagesDir(platform, pythonVersion)
  await mkdir(sitePackages, { recursive: true })
  const pipCmd = platform === 'win' ? runtimePythonBin(platform) : runtimePythonBin(platform)
  await run(pipCmd, ['-m', 'pip', 'install', '--target', sitePackages, '-r', REQ, '--no-warn-script-location'])

  // 3) 校验关键依赖
  await run(pipCmd, ['-c', 'import fastapi, pymilvus, chromadb, mcp, apscheduler'], {
    env: { ...process.env, PYTHONPATH: sitePackages },
  })

  // 4) 复制后端代码与 Skill
  const agentDir = path.join(STAGE, 'agent')
  await mkdir(agentDir, { recursive: true })
  for (const item of ['app', 'skills', 'scripts']) {
    await cp(path.join(REPO_ROOT, 'backend', item), path.join(agentDir, item), { recursive: true })
  }

  // 5) desktop.json 清单
  const reqHash = crypto.createHash('sha256').update(await readFile(REQ)).digest('hex').slice(0, 16)
  await writeFile(
    path.join(agentDir, 'desktop.json'),
    JSON.stringify(
      {
        version: '1.1.0',
        built_at: new Date().toISOString(),
        platform,
        python_version: pythonVersion,
        requirements_sha256: reqHash,
      },
      null,
      2,
    ),
  )
  log('完成:', STAGE)
}

stageRuntime(parseArgs(process.argv.slice(2))).catch((err) => {
  console.error('[stage-runtime] FAILED:', err.message)
  process.exit(1)
})
