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
import { cp, mkdir, readdir, readFile, readlink, realpath, rm, stat, symlink, unlink, writeFile } from 'node:fs/promises'
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

/**
 * 把运行时目录里指向**包外绝对路径**的符号链接改写成包内相对链接。
 *
 * Why：portable 运行时必须自包含。uv / pyenv 管理的解释器，其 bin/ 下大量条目是
 * 指向本机绝对路径的软链（bin/python3 -> /Users/<u>/.local/share/uv/.../python3.11）。
 * 原样打进安装包后，在**干净机**上链接全部悬空 —— 侧车解释器不存在，应用启动即失败，
 * 且失败是静默的（spawn 的 ENOENT 只进了握手 Promise）。
 */
async function relocateAbsoluteSymlinks(root, sourceRoots) {
  const fixed = []
  const skipped = []

  async function walk(dir) {
    const entries = await readdir(dir, { withFileTypes: true })
    for (const entry of entries) {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) {
        await walk(full)
        continue
      }
      if (!entry.isSymbolicLink()) continue
      const target = await readlink(full)
      if (!path.isAbsolute(target)) continue
      let real
      try {
        real = await realpath(full)
      } catch {
        real = target
      }
      // 原始目标与 realpath 都试：软链可能指向"另一个软链"，
      // realpath 会一路解析到包外，而**按原始目标映射**才对得上复制时的目录结构。
      let staged = null
      for (const candidate of [target, real]) {
        const owner = sourceRoots.find((r) => candidate === r || candidate.startsWith(r + path.sep))
        if (!owner) continue
        const mapped = path.join(root, path.relative(owner, candidate))
        if (existsSync(mapped)) {
          staged = mapped
          break
        }
      }
      if (!staged) {
        skipped.push(`${full} -> ${target}（包内无对应文件）`)
        continue
      }
      const rel = path.relative(path.dirname(full), staged)
      await unlink(full)
      await symlink(rel, full)
      fixed.push(`${full} -> ${rel}`)
    }
  }

  await walk(root)
  if (fixed.length) {
    log(`已归位绝对软链 ${fixed.length} 条：`)
    for (const f of fixed) log('  ·', f)
  }
  if (skipped.length) {
    log(`WARN: ${skipped.length} 条绝对软链无法归位（会随包悬空）：`)
    for (const s of skipped) log('  !', s)
  }
  return { fixed, skipped }
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
  // `home` 的语义按平台不同，这里必须归一：
  //   - Windows：指向**前缀目录**（…\Python311），下面要拼 python.exe / DLLs / Lib；
  //   - POSIX：  指向**解释器目录**（…/bin），下面要拼的是前缀。
  // 直接把 home 当前缀用，POSIX 会拼出 <prefix>/bin/bin —— 离线兜底在 macOS/Linux 上必挂
  // （此前该分支只在 Windows 上被验证过，见 doc/testing/00-全面测试计划.md 附录 C）。
  let basePrefix = home
  if (platform !== 'win' && home && path.basename(home) === 'bin') {
    basePrefix = path.dirname(home)
  }
  if (!basePrefix || !existsSync(basePrefix)) {
    // 兜底：从 venv 里的 python 软链反推基础解释器前缀
    // （venv 被搬过家时 pyvenv.cfg 里的 home 可能已失效）
    try {
      const real = await realpath(venvPy)
      basePrefix = path.dirname(path.dirname(real))
    } catch {
      throw new Error(
        '无法定位基础解释器前缀：pyvenv.cfg 的 home = ' + (home || '(缺失)') +
          '，且 venv 内 python 软链不可解析',
      )
    }
  }
  log('从本地虚拟环境组装：', venvPy, '→ 基础解释器前缀', basePrefix)

  await rm(STAGE, { recursive: true, force: true })
  await mkdir(STAGE, { recursive: true })

  // 1) 基础解释器 + 标准库
  if (platform === 'win') {
    await cp(path.join(basePrefix, 'python.exe'), path.join(STAGE, 'python.exe'))
    for (const dll of ['python311.dll', 'python3.dll']) {
      const src = path.join(basePrefix, dll)
      if (existsSync(src)) await cp(src, path.join(STAGE, dll))
    }
    await cp(path.join(basePrefix, 'DLLs'), path.join(STAGE, 'DLLs'), { recursive: true })
    await cp(path.join(basePrefix, 'Lib'), path.join(STAGE, 'Lib'), { recursive: true })
  } else {
    await cp(path.join(basePrefix, 'bin'), path.join(STAGE, 'bin'), { recursive: true })
    await cp(path.join(basePrefix, 'lib'), path.join(STAGE, 'lib'), {
      recursive: true,
      // 基础解释器自带一份 site-packages，而 venv 的依赖要落到**同一位置**。
      // 先跳过它，下面的 venv 依赖就是"新建"而不是"逐文件覆盖"，
      // 避免成千上万次重写（既慢，也容易撞上批量删除保护）。
      filter: (src) => path.basename(src) !== 'site-packages',
    })
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

  // 4) 绝对符号链接归位
  //    基础解释器（尤其 uv 管理的 venv）的 bin/ 下大量条目是指向**包外绝对路径**的软链
  //    （如 bin/python3 -> /Users/<u>/.local/share/uv/python/.../python3.11）。
  //    直接打进安装包后，在**干净机**上这些链接全部悬空 → 侧车解释器不存在 → 启动即失败。
  //    这里把它们改写成指向包内对应文件的**相对**链接。
  await relocateAbsoluteSymlinks(STAGE, [basePrefix, venv])

  // 5) P6-01：体积治理——裁掉不进包的依赖与产物
  await pruneRuntime(STAGE, platform, pythonVersion);

  // 6) 清单
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

/**
 * P6-01 · 确定性裁剪：把**不进包**的依赖与产物从运行时里剔除。
 *
 * 这些剔除项都**不参与运行时功能**：
 * - ``playwright``：P6-01 ② 要求改为**按需下载**（首次使用时拉取）；
 * - ``kubernetes``：桌面形态不跑 K8s；
 * - ``__pycache__`` / ``*.pyc``：运行时不需要字节码缓存；
 * - ``tests/`` / ``notebooks/``：仅开发期使用。
 */
const PRUNE_DIRS = new Set([
  'playwright', 'playwright_sync', 'pytest', '_pytest',
  'kubernetes', 'kubernetes_asyncio',
  '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache',
  'tests', 'notebooks',
]);

const PRUNE_EXTS = new Set(['.pyc', '.pyo']);

async function dirSize(dir) {
  let total = 0;
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return 0;
  }
  for (const e of entries) {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) total += await dirSize(full);
    else {
      try {
        total += (await stat(full)).size;
      } catch { /* 忽略 */ }
    }
  }
  return total;
}

async function pruneRuntime(stageDir, platform, pythonVersion) {
  // **W7-08**：此前 `platform` / `pythonVersion` 在本函数作用域**不存在**
  // （它们只是 `parseArgs()` 的局部对象与 `stageRuntime(opts)` 的解构变量，
  //   模块级无定义）→ `ReferenceError: platform is not defined`
  // → `--from-venv` 离线兜底路径在**复制约 745MB site-packages 之后**才崩 → 100% 失败。
  // 修复：显式传参。
  const spDir = sitePackagesDir(platform, pythonVersion);
  if (!existsSync(spDir)) return { removed: 0, freedBytes: 0 };

  let removed = 0;
  let freedBytes = 0;

  const remove = async (target) => {
    const size = await dirSize(target);
    await rm(target, { recursive: true, force: true });
    freedBytes += size;
    removed += 1;
  };

  // 1) site-packages 顶层包目录
  for (const name of PRUNE_DIRS) {
    const target = path.join(spDir, name);
    if (existsSync(target)) await remove(target);
  }

  // 2) 嵌套的 __pycache__ / *.pyc / tests 目录
  const walk = async (dir, depth) => {
    if (depth > 6) return;
    let entries;
    try {
      entries = await readdir(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (PRUNE_DIRS.has(entry.name)) {
          await remove(full);
          continue;
        }
        await walk(full, depth + 1);
      } else if (PRUNE_EXTS.has(path.extname(entry.name))) {
        try {
          freedBytes += (await stat(full)).size;
          await rm(full, { force: true });
          removed += 1;
        } catch { /* 忽略 */ }
      }
    }
  };
  await walk(spDir, 0);

  // 3) 后端代码里的 __pycache__ 与测试目录
  await walk(path.join(stageDir, 'agent'), 0);

  log(`裁剪完成：移除 ${removed} 项，释放 ${(freedBytes / 1024 / 1024).toFixed(1)} MB`);
  return { removed, freedBytes };
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
