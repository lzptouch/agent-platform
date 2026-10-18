# Agent Platform · Docker 部署说明

> 目标：把「直接 `uvicorn` + `npm run dev`」的开发态，改造成**一套 `docker compose` 启动的生产形态**。
> 全部配置文件都放在本仓库内：根目录 `docker-compose.yml` + `deploy/` 目录。

## 本目录文档

| 文档 | 回答什么 |
| --- | --- |
| [`README.md`](./README.md)（本文） | 架构分析 / 部署步骤 / 排错速查 / 本机实测记录 |
| [`部署文件分析与操作手册.md`](./部署文件分析与操作手册.md) | 部署文件全景与层级 / 两条路线（L0 直启、L1 容器化）/ 验收清单 / 端口与环境变量附录 |
| `../doc/deployment/00_导览与总览.md` | 面向读者的部署导览（形态 / 端口 / 文件地图 / 配置项） |
| `../doc/deployment/07_故障排查手册.md` | 按症状检索的排错清单 |

> 前端已收敛为唯一实现 `frontend/web/vue-element-plus`，本文涉及的 `frontend/` 路径均指该目录。

---

## 1. 现状分析（改造前）

| 组件 | 现状 | 说明 |
|---|---|---|
| 后端 | FastAPI + Uvicorn，`uvicorn app.main:app --port 8000` | 依赖 ~40 个第三方包（MCP SDK / pymilvus / chromadb / langchain / playwright） |
| 前端 | `frontend/web/vue-element-plus`（Vue 3 + TS + Vite + Element Plus），`npm run dev`（5173） | dev 模式下由 vite proxy 把 `/api` 转发到 8000 |
| 前端生产 | `node frontend/scripts/build-frontend.mjs` → `frontend/dist`，**后端用 `StaticFiles` 托管** | 即 FastAPI 同时干「API + 静态托管」两件事 |
| 向量库 | **Milvus Lite**（`data/milvus.db` 单文件） | pymilvus `connections.connect(uri=文件路径)`，嵌入式，**无外部服务** |
| Web Research 向量库 | Chroma（`Chroma.from_documents`，**进程内存态**） | 每次请求现场建库、请求结束即丢，无需持久化 |
| 深度研究 | JSON 文件 `data/research/tasks.json` + 报告 md | 进程重启后靠文件恢复 |
| 其它运行时数据 | `data/outputs`、`data/uploads`、`data/pdf`、`data/logs`、`data/browser_data` | 本地文件系统 |
| 密钥 | `backend/.env`（pydantic-settings 读取 `PROJECT_ROOT/.env`） | 不会自动带入容器 |

### 结论

1. **没有用到传统关系型数据库（MySQL / PostgreSQL）**，也没有用到 Redis。
   真正的「数据库」是嵌入式、文件级的：
   - Milvus Lite → `data/milvus.db`（**需要持久化**）
   - Chroma → 内存（无需持久化）
   - 深度研究任务 → JSON 文件（**需要持久化**）
2. 因此外部不需要额外起数据库容器，但**必须把 `data/` 持久化到数据卷**，否则容器一删，向量库和研究报告全没。
3. 同时提供了**可选的真 Milvus 集群**（etcd + MinIO + milvus standalone），见第 6 节。

---

## 2. 目标架构

```
                    ┌──────────────────────────── 浏览器 / 局域网客户端 ────────────────────────────┐
                    │                          http://<host>:8080/                                │
                    └──────────────────────────────────┬─────────────────────────────────────────┘
                                                       │
                                     ┌─────────────────▼──────────────────┐
                                     │  agent-platform-web  (nginx:alpine)│  对外唯一端口 8080→80
                                     │  ┌───────────────────────────────┐ │
                                     │  │ 静态直出：/、/assets/*        │ │  ← 前端 dist（构建期打进镜像）
                                     │  │ SPA 回退：非 /api → index.html│ │
                                     │  │ 反代：/api/v1/* → backend:8000│ │  ← SSE：proxy_buffering off
                                     │  │ 反代：/docs /redoc /openapi   │ │
                                     │  └───────────────────────────────┘ │
                                     └─────────────────┬──────────────────┘
                                        compose 内部网络 agent-platform-net
                                                       │
                                     ┌─────────────────▼──────────────────┐
                                     │  agent-platform-backend (python:3.11-slim)│
                                     │  uvicorn app.main:app 0.0.0.0:8000  │  ← 不再托管静态资源
                                     └─────────────────┬──────────────────┘
                                                       │ /app/data
                                     ┌─────────────────▼──────────────────┐
                                     │  named volume: agent-platform-data │
                                     │  ├─ milvus.db   （Milvus Lite 向量库）│
                                     │  ├─ research/   （任务 + 报告）      │
                                     │  └─ outputs|uploads|pdf|logs|browser_data│
                                     └────────────────────────────────────┘
```

设计要点：

| 决策 | 选择 | 理由 |
|---|---|---|
| 前端容器 | **多阶段构建**（node 构建 → nginx 运行） | 镜像里只有 nginx + dist，不含 node_modules，体积小、启动快、符合「Nginx 托管前端」要求 |
| 后端是否继续托管静态资源 | **否** | `app/main.py` 在容器内找不到 `../frontend/dist`，自动降级为纯 API 服务（保留原逻辑不动）；静态由 nginx 负责，职责分离 |
| 对外端口 | **只暴露 8080（nginx）**，backend 仅 `expose` | 单一入口、便于加 TLS / 限流；后端不直接暴露在宿主机 |
| SSE（流式对话 / 研究进度） | `proxy_buffering off` + `gzip off` + `X-Accel-Buffering: no` + 3600s 超时 | 否则前端收不到逐字流式，会一次性吐出或超时断开 |
| 后端健康感知 | `healthcheck` 打 `/api/v1/health`；nginx `depends_on: service_healthy` | 保证 nginx 起来时后端已就绪 |
| 服务名解析 | nginx `resolver 127.0.0.11` + 变量式 `proxy_pass` | backend 容器重建导致 IP 变化时，nginx 能重新解析，不会「启动即 502」 |
| 数据持久化 | named volume `agent-platform-data:/app/data` | 向量库/任务/上传/产出/日志跨容器重建保留 |
| 密钥 | `docker compose` 的 `env_file: ./backend/.env` | 密钥不进镜像层；镜像可安全分发 |

---

## 3. 文件清单

```
agent-platform/
├── docker-compose.yml                     # 主编排（backend + web）
├── .dockerignore                          # 构建上下文裁剪（排除 node_modules/.venv/data/.env）
├── frontend/web/vue-element-plus/        # 唯一前端实现（Dockerfile 构建的就是它）
├── deploy/
│   ├── README.md                          # 本文档
│   ├── 部署文件分析与操作手册.md           # 文件全景 / 两条路线 / 验收清单
│   ├── docker-compose.milvus.yml          # 【可选】真 Milvus 集群覆盖文件
│   ├── backend/
│   │   ├── Dockerfile                     # 后端镜像
│   │   └── entrypoint.sh                  # 启动脚本（建目录 / 可选入库 / exec uvicorn）
│   ├── frontend/
│   │   └── Dockerfile                     # 前端多阶段构建（node → nginx）
│   └── nginx/
│       ├── nginx.conf                     # 主配置（gzip / 日志 / 上传体积）
│       └── conf.d/agent-platform.conf     # 站点配置（静态 + 反代 + SSE）
└── backend/.env                           # 运行时密钥（从 .env.example 复制，已被 .gitignore 忽略）
```

> 两个 Dockerfile 的**构建上下文都是仓库根目录**，所以要用 `-f deploy/... .` 的形式；`docker-compose.yml` 已配置好 `context: .`。

---

## 4. 快速开始

### 4.1 准备密钥

```bash
cp backend/.env.example backend/.env     # 已存在则直接编辑
```

至少填写：

| 变量 | 用途 |
|---|---|
| `DASHSCOPE_API_KEY` | Agent 主链路（Skill / MCP / 代码执行） |
| `LLM_API_KEY` | RAG 链路（DeepSeek 兼容） |
| `BOCHA_API_KEY` 或 `SERPER_API_KEY` | 深度研究链路的检索引擎（二选一即可） |

### 4.2 构建并启动

```bash
# 在 docker-compose.yml 所在目录（apps/agent-platform/）
docker compose build          # 首次构建较慢：要装 playwright chromium
docker compose up -d
docker compose ps             # 观察 STATUS 是否 healthy
```

### 4.3 访问

| 地址 | 内容 |
|---|---|
| http://localhost:8080/ | 前端页面（Nginx 静态托管） |
| http://localhost:8080/api/v1/health | 后端健康检查（经 Nginx 反代） |
| http://localhost:8080/docs | 后端 Swagger |
| http://localhost:8080/nginx-healthz | Nginx 自检 |

端口可通过环境变量改：`HOST_HTTP_PORT=80 docker compose up -d`。

### 4.4 常用运维命令

```bash
docker compose logs -f backend            # 看后端日志
docker compose logs -f web                # 看 Nginx 访问/错误日志
docker compose restart backend
docker compose down                       # 停容器（数据卷保留）
docker compose down -v                    # 连数据卷一起删（=清空向量库与研究报告）

# RAG 入库（需要 API Key，PDF 放 backend/data/pdf）
docker compose exec backend python -m scripts.ingest_data

# 直接看数据卷内容
docker run --rm -v agent-platform-data:/data alpine ls -lhR /data
```

---

## 5. 数据持久化说明

| 容器内路径 | 内容 | 是否持久化 |
|---|---|---|
| `/app/data/milvus.db` | Milvus Lite 向量库（RAG 稠密+稀疏混合检索） | 是（named volume） |
| `/app/data/research/` | `tasks.json` 任务记录 + 生成的 md 报告 | 是 |
| `/app/data/outputs`、`uploads`、`pdf` | Agent 产出、上传文件、PDF 素材 | 是 |
| `/app/data/logs`、`browser_data` | 日志、小红书登录 Cookie | 是 |
| Chroma（Web Research） | 进程内存 | 否（设计如此，每次请求重建） |

如果希望这些数据落到**宿主机目录**（方便直接查看产出文件），把 compose 里的卷改成绑定挂载即可：

```yaml
    volumes:
      - ./backend/data:/app/data     # Windows Docker Desktop 下需确认该目录已在 File Sharing 白名单
```

---

## 6. 可选：切换到独立 Milvus 集群

默认用嵌入式 Milvus Lite（零额外容器、够用）。若要多容器共享向量库 / 单独扩容 / 接 attu 等工具：

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.milvus.yml up -d
```

该覆盖文件会额外拉起 `milvus-etcd`（元数据）+ `milvus-minio`（对象存储）+ `milvus`（standalone，内部 19530），
并把后端 `MILVUS_DB_PATH` 从 `data/milvus.db` 改成 `http://milvus:19530`。

> 切换后原 `milvus.db` 里的数据不会自动迁移，需要重新入库：
> `docker compose exec backend python -m scripts.ingest_data`

---

## 7. 构建参数

| Build Arg | 默认 | 说明 |
|---|---|---|
| `PIP_INDEX_URL` | `https://pypi.org/simple` | 国内可传 `https://pypi.tuna.tsinghua.edu.cn/simple` |
| `INSTALL_PLAYWRIGHT` | `true` | 装 chromium（小红书 MCP Server 需要），设为 `false` 可大幅缩短构建时间 |
| `NPM_REGISTRY` | `https://registry.npmjs.org` | 前端依赖源，国内可换 `https://registry.npmmirror.com` |

示例：

```bash
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
NPM_REGISTRY=https://registry.npmmirror.com \
INSTALL_PLAYWRIGHT=false \
docker compose build
```

---

## 8. 排错速查

| 现象 | 原因 / 处理 |
|---|---|
| `docker compose up` 报找不到 `./backend/.env` | 复制 `backend/.env.example` 为 `backend/.env` |
| 构建报 `failed to resolve source metadata for docker.io/docker/dockerfile:1.7` | Dockerfile 里不要写 `# syntax=` 指令（本机镜像加速器拉不到 BuildKit frontend），已移除 |
| `Head "https://<mirror>/v2/.../manifests/...": EOF` | 本机 Docker 镜像加速器**缺少该仓库/标签**；换加速器或在 Docker Desktop → Settings → Docker Engine 里去掉/更换 `registry-mirrors` 后重试（例如 `minio/minio` 在 USTC 源不可达） |
| 访问 `/` 正常，`/api/v1/health` 502 | backend 未 healthy；`docker compose logs backend` 看启动异常 |
| 流式回答一次性出现 | Nginx 缓冲；确认 `/api/` 走的是本仓库的 `deploy/nginx/conf.d/agent-platform.conf` |
| 研究报告重启后消失 | 数据卷被删（`down -v`）或没挂载；`docker volume inspect agent-platform-data` |
| 构建极慢 / playwright 下载超时 | `INSTALL_PLAYWRIGHT=false docker compose build` |
| 端口 8080 被占用 | `HOST_HTTP_PORT=8081 docker compose up -d` |
| 容器内时间不对 | compose 已注入 `TZ=Asia/Shanghai`；镜像内也装了 tzdata |

---

## 9. 已知约定

- 后端以**单进程 uvicorn**（worker=1）运行：深度研究的 `ResearchManager` 是进程内线程池 + 内存任务字典，多 worker 会导致任务状态不一致。如需扩容请先改造为外部任务队列（Celery/Redis）。
- 后端镜像内 `/app/frontend/dist` 不存在，`app/main.py` 会自动走「纯 API 模式」分支（原有代码未做任何修改）。
- 生产建议后续补齐：HTTPS（Nginx 挂载证书或前置反代）、Nginx 访问频率限制、`/docs` 对公网关闭、镜像打 tag 推私有仓库。

---

## 10. 本机实测记录（Docker Desktop 4.75 / Compose v5.1.3 / 16C 32G）

| 项 | 结果 |
|---|---|
| `docker compose config` | 主文件 + Milvus 覆盖文件均通过校验 |
| `docker compose build` | 成功；`agent-platform-backend:1.1.0` ≈ 3.96GB（主要来自 Chromium + chromadb/langchain），`agent-platform-web:1.1.0` ≈ 74MB |
| `docker compose up -d` | backend `Up (healthy)`、web `Up (healthy)`，端口 `0.0.0.0:8080->80` |
| `GET /` | 200 `text/html`，返回 Vue 构建后的 index.html（`/assets/index-*.js|css`） |
| `GET /assets/index-*.js` | 200 `application/javascript`（带 7d 强缓存头） |
| `GET /some/deep/route` | 200 → SPA 回退到 index.html |
| `GET /api/v1/health` | 200，`skills_loaded=6`、`rag_collection=hybrid_demo`、`rag_entities=0` |
| SSE `POST /api/v1/agent/run` | 200，响应头 `Content-Type: text/event-stream` + `Transfer-Encoding: chunked` + `X-Accel-Buffering: no`，事件逐个实时到达（`skills_selected` → `system_prompt` → `user_input` → `error: 未配置 DASHSCOPE_API_KEY` → `done`）→ 反代流式链路打通 |
| 数据持久化 | 容器内 Milvus Lite 自动生成 `/app/data/milvus.db`（32KB）；写入 `/app/data/outputs/_persist_test.txt` 后 `docker compose restart backend`，文件与向量库均完好 |
| 服务发现 | 重启 backend（IP 变化）后 nginx 仍能正常代理 → `resolver 127.0.0.11` 生效 |
| 未知 API 路径 | `/api/v1/nope` → 404（由后端返回，未落到 SPA 回退） |

> Milvus Lite 模式（默认）已在上述环境端到端跑通。
> `deploy/docker-compose.milvus.yml`（独立 Milvus 集群）中 `milvusdb/milvus`、`coreos/etcd` 已成功拉取，
> `minio/minio` 因本机加速器不可达暂未拉取成功，故该可选形态未在本机完成启动验证；换加速器后按第 6 节命令即可启用。

---

## 11. 后续可选优化

1. **镜像瘦身**：不需要小红书 MCP Server 时 `INSTALL_PLAYWRIGHT=false`；或做 runtime 阶段分离（构建依赖不进运行镜像）。
2. **多阶段 + 虚拟环境**：当前 pip 装在系统 site-packages，可用 `python:3.11-slim` + `/opt/venv` 减少层体积。
3. **HTTPS**：Nginx 挂载证书，或前置统一的 Ingress / Caddy。
4. **横向扩容**：先把 `ResearchManager` 的进程内任务改成外部队列（Redis/Celery），再扩 uvicorn worker 数。
5. **CI**：把 `docker compose build` + `docker compose up` + 冒烟 curl 串成流水线，产出带 commit sha 的镜像 tag。
