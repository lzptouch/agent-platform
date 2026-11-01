# 发布手册（Agent Desktop · 单运行时版）

> **改造要点（design/16 §9.1 / §11.10）**：原 `deploy/` 下有 `docker-compose.yml`、
> `nginx/`、`backend/`、`frontend/` 与「部署文件分析与操作手册.md」——**全部随
> Web / Docker 形态退场而删除**。本文件取代它们，成为**唯一的发布手册**。
>
> **软件现在只有一个形态**：一个桌面软件（Electron 壳 + 内嵌 TypeScript 后端）。

---

## [1] 前置条件

| 依赖 | 版本 | 说明 |
| --- | --- | --- |
| Node.js | ≥ 20（推荐 22） | **唯一运行时**（开发与打包同用） |
| npm | ≥ 10 | 依赖安装 |
| Python | ≥ 3.9（可选） | **仅**供根级 E2E（Playwright）使用；软件本身不需要 |
| macOS 签名证书 | 可选 | 无证书时可出**未签名**包（本地自测可用） |

> **不再需要**：Python 运行时（portable）、Docker、Docker Compose、Nginx、Milvus 容器。

---

## [2] 一次命令打包

```bash
# 全流程：前端 → TS 后端 → 暂存 → 壳 → electron-builder → 体积预算
node scripts/build-desktop.mjs --platform mac --arch arm64 --publish never
```

| 参数 | 取值 | 说明 |
| --- | --- | --- |
| `--platform` | `mac` / `win` / `linux` | 目标平台 |
| `--arch` | `arm64` / `x64` | 目标架构 |
| `--publish` | `never` / `always` | 是否自动发布（本地一律 `never`） |
| `--skip-self-check` | 开关 | 跳过打包后自检（CI 里用） |
| `--strict` | 开关 | 体积预算**超限即失败**（默认仅告警） |

### 2.1 内部步骤

| # | 步骤 | 产物 |
| --- | --- | --- |
| 1 | 构建前端 | `apps/ui/dist/`（含 `splash.html`） |
| 2 | 构建 TS 后端 | `apps/server/dist/` |
| 3 | **暂存后端** | `apps/server/.pack/` = dist 内容 + `package.json`（`type: module`）+ **生产依赖** + `.native/abi-<ABI>/` |
| 4 | 构建 Electron 壳 | `apps/desktop/dist-main/` |
| 5 | electron-builder | `apps/desktop/release/`（dmg / zip / AppImage / nsis） |
| 6 | 体积预算 | 见 §4 |
| 7 | 打包态自检 | `node tests/scripts/verify-desktop-package.mjs` |

### 2.2 ⚠️ 原生模块的**双 ABI**（必做）

`better-sqlite3` 是原生模块，**Node 与 Electron 的 ABI 不同**：

| 运行时 | ABI | 用途 |
| --- | --- | --- |
| 系统 Node（v22+） | 137 | 开发态测试（vitest） |
| Electron 33（内含 Node 20.18） | 130 | 桌面应用 |

**同一份 `node_modules` 无法同时满足两者** → 用 `scripts/rebuild-native.mjs` 生成两套：

```bash
node scripts/rebuild-native.mjs
# → apps/server/.native/abi-137/better_sqlite3.node   （Node）
# → apps/server/.native/abi-130/better_sqlite3.node   （Electron）
```

运行时由 `apps/server/src/db/native.ts` 按 `process.versions.modules` **自动选择**。

> **漏了这步的症状**：开发态测试全绿，但**安装包启动即退出**（sidecar 静默
> `ERR_DLOPEN_FAILED`）。CI 的 L4 层已把该步骤固化。

---

## [3] 产物布局（安装包内）

```
Agent Desktop.app/Contents/Resources/
├── app.asar              # 壳主进程 + preload（不含后端）
├── server/               # ★ TS 后端（不进 asar —— 由 utilityProcess.fork 加载）
│   ├── main.js           #   入口
│   ├── db/ domain/ http/ mcp/ shared/ workers/
│   ├── package.json      #   {"type":"module"}
│   ├── node_modules/     #   生产依赖
│   └── .native/abi-130/  #   Electron ABI 原生模块
├── frontend/             #   Vue 渲染层产物（index.html + assets + splash.html）
└── skills/               #   6 个内置 Skill（只读）
```

> **为什么后端不进 asar**：`utilityProcess.fork()` 需要**真实的文件路径**
> （`process.resourcesPath/server/main.js`），asar 内的虚拟路径无法被
> Node 的 ESM 加载器解析。

---

## [4] 体积预算

| 项 | 预算 | 实测（macOS arm64） |
| --- | ---: | ---: |
| TS 后端产物（`dist` + 生产依赖 + 原生模块） | ≤ 80 MB | ~28 MB |
| 前端 `dist` | ≤ 30 MB | ~1.8 MB |
| 壳产物（`dist-main`） | ≤ 120 MB | ~2 MB |
| **安装包（dmg）** | — | **~151 MB**（Electron 运行时占大头） |

> 对比改造前：安装包需额外携带 **987MB portable Python** → 现已**归零**。

---

## [5] 打包态自检

```bash
node tests/scripts/verify-desktop-package.mjs
```

自检项：

| # | 检查 |
| --- | --- |
| 1 | 安装包内 `server/main.js` / `frontend/index.html` / `skills/` 均存在 |
| 2 | `.native/abi-130/` 原生模块存在且可加载 |
| 3 | 启动安装包 → sidecar 握手 → 端口可达 → 优雅退出 |

---

## [6] 实机验收清单（P8-02）

| # | 步骤 | 期望 |
| --- | --- | --- |
| 1 | 双击 `Agent Desktop.app` | 窗口出现，启动页 → 主界面 |
| 2 | `~/Library/Application Support/Agent Desktop/run-state.json` | 写入 `pid` / `port` / `exe` |
| 3 | 首次启动 | **建库**：`<userData>/data/app.db`（23 表 = 22 业务表 + `__migrations`） |
| 4 | `GET /__desktop/ping` | `{"ok":true}` |
| 5 | 打开主界面 | 会话列表为空、可新建会话 |
| 6 | 旧版安装包覆盖升级 | **自动备份** `app.db.bak-<ts>` → **原地升级** → 旧数据保留 |
| 7 | `GET /api/v1/health`（无会话） | `401` |
| 8 | 非法 `Host` 头 | `421` |

---

## [7] 发布渠道

| 平台 | 产物 | 说明 |
| --- | --- | --- |
| macOS | `Agent Desktop-<ver>-mac-<arch>.dmg` / `.zip` | 需 **Developer ID** 签名 + 公证（`notarize: true`） |
| Windows | `Agent Desktop Setup <ver>.exe` | 需代码签名证书 |
| Linux | `Agent Desktop-<ver>.AppImage` | 无需签名 |

### 7.1 自动更新

`electron-builder.yml` 的 `publish` 段为空 → **自动更新未启用**（启动日志会提示）。
启用方式：填入 `publish` 配置（如 GitHub Releases）并配置签名。

---

## [8] 常见问题

| 现象 | 原因 | 处置 |
| --- | --- | --- |
| 安装包启动后**秒退**，无日志 | 入口判定失败（路径含**空格** → `import.meta.url` 编码 `%20`） | 已修复（`main.ts` 的 `isEntryPoint`），回归用例见 `tests/unit/server/packaging.test.ts` |
| sidecar 报 `ERR_DLOPEN_FAILED` | 原生模块 ABI 不匹配 | `node scripts/rebuild-native.mjs` 后重新打包 |
| 启动报「表已存在」 | 旧库升级路径未走「标记基线 + 补列」 | 已修复；确认 `__migrations` 表存在且基线已标记 |
| `[tray] 托盘图标缺失` | `Resources/icon.icns` 未打进包 | 补 `build/icon.icns` 后重新打包 |
| `[updater] 自动更新未启用` | 未配置 `publish` 段 | 属预期，按需配置 |

---

## [9] 相关文档

| 文档 | 内容 |
| --- | --- |
| `doc/design/16-桌面一体化改造方案与实施计划.md` | 改造方案与实施计划（依据） |
| `tests/docs/test-runs/P9-final/README.md` | 改造后全量回归与验收报告 |
| `tests/docs/test-runs/P0-baseline/README.md` | 改造前全量基线 |
| `baseline/features.csv` | 功能基线清单（185 项） |
| `contract/` | 契约冻结产物（98 路径 / 126 操作 / 26 事件 / 22 表） |
