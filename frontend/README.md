# frontend/ · 默认前端 + 桌面壳

`apps/agent/frontend/` 只保留**一个**前端实现，另含桌面壳：

```
frontend/
├── README.md                          ← 本文件
├── scripts/
│   ├── build-frontend.mjs             ← 构建默认前端 → 拷贝到 frontend/dist
│   └── smoke.mjs                      ← 后端 35 端点端到端冒烟测试
├── desktop/                           ← 桌面壳（Electron 主进程 + 内嵌 FastAPI sidecar）
│   ├── src/                           ←   main / preload / shared
│   ├── resources/                     ←   图标 / NSIS 脚本 / macOS entitlements
│   ├── electron-builder.yml           ←   打包配置
│   └── package.json                   ←   壳的依赖与脚本（npm run build / pack / test）
├── dist/                              ← 【生成物】构建产物（gitignore）
└── web/
    └── vue-element-plus/              ← 默认前端：Vue 3 + TS + Vite + Element Plus + Pinia + Router
```

> 仓库曾是多实现（web×3 + 桌面×2 + 小程序×3 + Android×2 + iOS×2 + macOS×2 + 鸿蒙×1）集合，
> 已于 2026-10-19 收敛为唯一实现 `web/vue-element-plus`（原 Vue 标杆实现）。
> 组件结构与开发说明见 [web/vue-element-plus/README.md](./web/vue-element-plus/README.md)。
> 桌面壳于 2026-10-28 由仓库根 `desktop/` 迁入本目录（现为 `frontend/desktop/`）。

`frontend/dist/` 是后端 `app.main` 与 Nginx 唯一认可的静态产物目录。

## 快速开始

### 开发模式（Vite dev server，端口 5185）

```bash
cd frontend/web/vue-element-plus
npm install
npm run dev          # http://127.0.0.1:5185/ ，代理 /api → http://127.0.0.1:18040
```

> 注意：Vite proxy 目标由 `web/vue-element-plus/vite.config.ts` 的 `server.proxy['/api'].target` 决定，当前为 `http://127.0.0.1:18040`。**开发时请确保后端跑在 18040**，或按需修改该 target。

### 构建 → 拷贝到 `frontend/dist`（供后端单端口托管）

```bash
node frontend/scripts/build-frontend.mjs
```

等价于在 `frontend/web/vue-element-plus/` 内执行 `npm run build`，再把 `dist/` 拷到 `frontend/dist/`。

### 单端口联调（后端托管静态资源）

```bash
node frontend/scripts/build-frontend.mjs
cd backend && .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# 浏览器访问 http://127.0.0.1:8000/ ，后端检测到 frontend/dist 后自动托管
```

## 容器化部署

前端在 Docker 中由 `deploy/frontend/Dockerfile` 两段式构建（`node:22-alpine` 构建 → `nginx:1.27-alpine` 运行），
镜像内构建的就是 `frontend/web/vue-element-plus`：

```bash
docker compose build web
docker compose up -d
# 访问 http://localhost:8080/
```

## 端到端冒烟测试

```bash
# 终端 1：启动后端
cd backend && .venv/bin/python -m uvicorn app.main:app --port 8000

# 终端 2：跑 35 端点冒烟
node frontend/scripts/smoke.mjs                        # 默认 http://127.0.0.1:8000
node frontend/scripts/smoke.mjs http://127.0.0.1:8000  # 也可显式指定
```

## 桌面壳（`frontend/desktop/`）

桌面壳是独立 npm 工程（Electron 主进程 + 内嵌 FastAPI sidecar），2026-10-28 由仓库根 `desktop/` 迁入本目录。

```bash
# 开发态：拉起壳（自动以仓库 backend/.venv 拉起 sidecar）
cd frontend/desktop
npm install
npm run build && npm start

# 单测 / 类型检查
npm test
npm run typecheck

# 一条命令打包（前端构建 → portable 运行时 → electron-builder → 打包后自检）
node scripts/build-desktop.mjs
```

> 打包产物在 `frontend/desktop/release/`；portable Python 运行时由 `scripts/stage-runtime.mjs`
> 组装到 `frontend/desktop/.stage/runtime/`。壳与后端的编排契约见
> [`../doc/design/03-桌面壳与后端进程编排设计.md`](../doc/design/03-桌面壳与后端进程编排设计.md)。

## 契约与同步

契约的唯一事实源在项目文档集 `doc/analysis/`（原 `frontend/docs/` 已于 2026-10-28 删除）：

- HTTP 接口总览：[`../doc/analysis/05_HTTP接口总览.md`](../doc/analysis/05_HTTP接口总览.md)
- 前端架构与接口契约：[`../doc/analysis/06_前端架构与接口契约.md`](../doc/analysis/06_前端架构与接口契约.md)
- SSE 事件协议：[`../doc/analysis/03_Agent执行引擎与事件协议.md`](../doc/analysis/03_Agent执行引擎与事件协议.md)

后端接口变更时，按 [web/vue-element-plus/README.md](./web/vue-element-plus/README.md) 的「后端接口同步清单」人工同步
（端点表 / SSE 事件类型 / Research stage / Types 四处）。
