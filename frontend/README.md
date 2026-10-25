# frontend/ · 默认前端

`apps/agent/frontend/` 只保留**一个**前端实现：

```
frontend/
├── README.md                          ← 本文件
├── docs/                              ← 接口契约、SSE 协议、设计 Token
│   ├── api-contract.md
│   ├── sse-protocol.md
│   └── design-tokens.md
├── scripts/
│   ├── build-frontend.mjs             ← 构建默认前端 → 拷贝到 frontend/dist
│   └── smoke.mjs                      ← 后端 35 端点端到端冒烟测试
├── dist/                              ← 【生成物】构建产物（gitignore）
└── web/
    └── vue-element-plus/              ← 默认前端：Vue 3 + TS + Vite + Element Plus + Pinia + Router
```

> 仓库曾是多实现（web×3 + 桌面×2 + 小程序×3 + Android×2 + iOS×2 + macOS×2 + 鸿蒙×1）集合，
> 已于 2026-10-19 收敛为唯一实现 `web/vue-element-plus`（原 Vue 标杆实现）。
> 组件结构与开发说明见 [web/vue-element-plus/README.md](./web/vue-element-plus/README.md)。

`frontend/dist/` 是后端 `app.main` 与 Nginx 唯一认可的静态产物目录。

## 快速开始

### 开发模式（Vite dev server，端口 5173）

```bash
cd frontend/web/vue-element-plus
npm install
npm run dev          # http://127.0.0.1:5173/ ，代理 /api → http://127.0.0.1:8000
```

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

## 契约与同步

- 接口契约：[`docs/api-contract.md`](./docs/api-contract.md)
- SSE 协议：[`docs/sse-protocol.md`](./docs/sse-protocol.md)
- 设计 Token：[`docs/design-tokens.md`](./docs/design-tokens.md)

后端接口变更时，按 [web/vue-element-plus/README.md](./web/vue-element-plus/README.md) 的「后端接口同步清单」人工同步
（端点表 / SSE 事件类型 / Research stage / Types 四处）。
