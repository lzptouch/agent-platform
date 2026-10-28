# agent

整合 **5 条能力链**（Skill / MCP / RAG / Web Research / Deep Research）的 Agent 平台。
前后端分离：**`backend/`（FastAPI）** 与 **`frontend/`（Vue 3 + Vite）** 为同级独立项目。

```
agent/
├── backend/                 # FastAPI 后端（Python 3.10~3.12）
│   ├── app/                 #   应用代码（api / services / mcp / schemas / core）
│   ├── skills/              #   6 个 Agent Skill
│   ├── data/                #   运行时数据（outputs / pdf / milvus.db / logs）
│   ├── tests/               #   40 个 pytest 用例
│   ├── scripts/             #   RAG 入库脚本
│   ├── notebooks/           #   教学 notebook
│   ├── requirements.txt / pyproject.toml
│   ├── .env(.example)       #   密钥配置
│   └── README.md            #   后端详细文档
│
├── frontend/                # 默认前端（唯一实现）+ 桌面壳
│   ├── web/vue-element-plus/#   Vue 3 + TS + Vite + Element Plus + Pinia + Router
│   ├── desktop/             #   桌面壳（Electron 主进程 + 内嵌 FastAPI sidecar）
│   ├── scripts/             #   build-frontend.mjs（构建 → frontend/dist）/ smoke.mjs
│   └── dist/                #   【生成物】后端 StaticFiles 托管的静态产物
│
├── doc/                     # 文档集（analysis / knowledge / deployment）
├── deploy/                  # 容器化部署资产 + 部署操作手册
└── docker-compose.yml       # 主编排：backend + web(nginx)
```

> 前端曾是多实现（Web×3 + 桌面×2 + 小程序×3 + Android×2 + iOS×2 + macOS×2 + 鸿蒙×1）集合，
> 已收敛为唯一默认实现 **`frontend/web/vue-element-plus`**。

## 快速开始

### 后端（端口 8000）

```bash
cd backend
uv venv .venv --python 3.11
# Windows：uv pip install --python .venv/Scripts/python.exe -r requirements.txt
# Linux/macOS：uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env   # 填入 DASHSCOPE_API_KEY（必需）/ LLM_API_KEY（DeepSeek，必需）
                       # 可选：BOCHA_API_KEY 或 SERPER_API_KEY（深度研究链路的检索引擎）
# Windows：.venv/Scripts/python.exe -m scripts.ingest_data   # RAG 入库（真实 PDF → Milvus）
# Windows：.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

> 本机 `8000` 若被占用（如与其它本地服务共存），可改用 `--port 8001` 并让前端 proxy 指向对应端口。

### 前端（开发模式，端口 5185）

```bash
cd frontend/web/vue-element-plus
npm install
npm run dev            # 打开 http://localhost:5185（/api 代理到 vite.config.ts 的 target，当前 18040）
```

> 前端 dev 代理目标由 `frontend/web/vue-element-plus/vite.config.ts` 的 `server.proxy['/api'].target` 决定（当前 `http://127.0.0.1:18040`）。开发时请让后端跑在该端口，或按需修改 target 指向后端实际端口。

### 前端（生产模式，单端口 8000）

```bash
node frontend/scripts/build-frontend.mjs   # 产出 frontend/dist
# 后端检测到 frontend/dist 后自动托管：http://127.0.0.1:8000/
```

## 5 条能力链

| 链 | 能力 | 密钥 |
| --- | --- | --- |
| Skill | 6 Skill + 本地代码执行 + Agent 循环（OpenAI 兼容 function calling） | `DASHSCOPE_API_KEY` |
| MCP | 3 个 stdio MCP Server（天气/搜索/小红书）+ 静态反射 | 天气免 Key；搜索需 `SERPER_API_KEY` |
| RAG | PDF → DashScope `text-embedding-v3` API → Milvus Lite（BM25+稠密混合检索）→ DeepSeek 带 `[n]` 引用 | `DASHSCOPE_API_KEY` + `LLM_API_KEY` |
| Web Research | Serper + 多线程爬虫 + Chroma 召回 + GPT 引用卡片 | `SERPER_API_KEY` + `OPENAI_API_KEY`（可选） |
| **Deep Research** | **Orchestrator-Workers 多智能体 + OODA 子循环 + 质量评分迭代 + 报告落盘**（迁移自 deep_research） | `BOCHA_API_KEY`（推荐）或 `SERPER_API_KEY`（自动降级） |

> Embedding 全部走 API，**无 torch / 无本地模型**；Milvus 稀疏向量由 BM25 Function 服务端生成。

## 测试

```bash
cd backend && .venv/bin/python -m pytest tests/ -q   # 99 passed（含 WorkBuddy 扩展 59 个新用例）
```

## WorkBuddy 能力扩展（v2）

对标 WorkBuddy 新增三大能力，设计文档见 `doc/workbuddy/`（00~05 + 截图）：

- **对话模式 / 工作模式**：`mode=chat`（Ask，只读工具+多轮上下文）/ `mode=work`（Craft，全量工具）/ `plan_first`（Plan，先出计划、人工确认后执行）
- **会话持久化**：SQLite（WAL）+ SQLAlchemy 2.0 + Alembic；`POST /api/v1/sessions` 管理会话，消息与运行记录落库，重启可恢复
- **Skill 团队**：`teams` CRUD + `none/sequential/router` 三种编排策略，`POST /api/v1/teams/{id}/resolve` 预览
- **Skill 管理闭环**：创建 / 编辑 / 启停用 / zip 导入导出（内置 Skill 只读保护，路径穿越拦截）
- **定时任务**：`POST /api/v1/schedules`（cron / 间隔），APScheduler + DB 租约防多副本重复调度 + `(task_id, scheduled_for)` 幂等 + 失败退避 + 运行历史与事件回放（`GET /api/v1/runs/{id}/stream`）
- **前端**：`/chat`（对话）、`/work`（工作台 + Plan 审批卡片）、`/teams`、`/schedules`、`/skills`（管理）

```bash
# 浏览器端到端测试（10 场景 + 截图，需先启动后端）
backend/.venv/bin/python scripts/ui_browser_test.py
```

## 验证过的端到端场景

- Agent + RAG：自动调 `rag_query`，带 `[7]` 引用回答电池容量（150kWh 半固态电池）
- Agent + MCP：自动调 `mcp_weather__get_alerts`，返回真实 NWS 加州预警
- Agent + reflection：plan → action → reflection → DeepSeek-r1 `reasoning_delta` 流式
- 前端 4 链开关、工具来源着色（内置青 / MCP 紫 / RAG 绿 / Web 橙）、引用卡片、思考过程流式
- **Skill 可选**：前端多选（全选 / 清空），仅选中的 Skill 注入 system prompt；`skills=[]` 表示不加载任何 Skill
- **Deep Research**：`POST /api/v1/research` → 后台线程池执行 → SSE 进度流 → 报告与 `tasks.json` 落盘，重启可恢复


## 深度研究链路（第 5 链）

```bash
# 提交任务
curl -X POST http://127.0.0.1:8000/api/v1/research \
  -H 'Content-Type: application/json' \
  -d '{"task":"2026 年新能源汽车市场竞争格局","max_workers":4,"max_iterations":3}'

# 查看进度 / 报告
curl http://127.0.0.1:8000/api/v1/research/<task_id>
curl http://127.0.0.1:8000/api/v1/research/<task_id>/result
curl -N http://127.0.0.1:8000/api/v1/research/<task_id>/stream   # SSE
```

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/research/health` | 链路健康（检索提供方 / 任务数） |
| POST | `/api/v1/research` | 提交任务（无检索 Key 时**立即失败**并给出原因） |
| GET | `/api/v1/research` | 任务列表 |
| GET | `/api/v1/research/{id}` | 任务状态 + 进度 |
| GET | `/api/v1/research/{id}/result` | 报告（未完成 202） |
| GET | `/api/v1/research/{id}/stream` | SSE 进度流 |
| DELETE | `/api/v1/research/{id}` | 删除任务（运行中 400） |

**落盘结构**：

```
data/research/
├── tasks.json              # 任务记录（重启恢复，运行中任务标记为中断）
└── <task_id>/
    ├── report_YYYYmmdd_HHMMSS.md
    └── meta_YYYYmmdd_HHMMSS.json
```

## Docker 部署（对外提供服务形态）

除了上面的直启开发态，已提供完整的容器化部署配置，全部文件都在本仓库内：

```
docker-compose.yml                  # 主编排：backend + web(nginx)
.dockerignore
deploy/
├── README.md                       # 架构分析 / 部署步骤 / 排错 / 实测记录
├── 部署文件分析与操作手册.md         # 文件全景 / 两条部署路线 / 验收清单 / 排错速查
├── backend/Dockerfile              # 后端镜像（含 playwright chromium）
├── backend/entrypoint.sh
├── frontend/Dockerfile             # 前端多阶段构建：node build → nginx 运行
├── nginx/nginx.conf
├── nginx/conf.d/agent.conf# 静态托管 + /api 反代 + SSE 支持
└── docker-compose.milvus.yml       # 可选：独立 Milvus 集群（etcd + minio + milvus）
```

三步启动：

```bash
cp backend/.env.example backend/.env    # 填入 DASHSCOPE_API_KEY / LLM_API_KEY / BOCHA_API_KEY 等
docker compose build
docker compose up -d
```

访问：<http://localhost:8080/>（Nginx 对外唯一入口：`/` 静态前端，`/api/v1/*` 反代到后端，
`/docs` 为 Swagger）。对外端口可用 `HOST_HTTP_PORT=80 docker compose up -d` 修改。

向量库默认用嵌入式 Milvus Lite（`data/milvus.db`），数据统一落在命名卷 `agent-data`；
需要正式版 Milvus 时叠加覆盖文件即可：

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.milvus.yml up -d
docker compose exec backend python -m scripts.ingest_data   # 重新入库
```

详细内容见 [`deploy/README.md`](deploy/README.md)（架构与操作）与
[`deploy/部署文件分析与操作手册.md`](deploy/部署文件分析与操作手册.md)（文件全景 + 逐步操作 + 验收清单）。

## 文档

项目文档集统一在 [`doc/`](./doc/)：

| 目录 | 内容 |
| --- | --- |
| `doc/analysis/` | 模块 / 接口 / 链路 / 一致性 / 可观测 / 高并发 / 部署 / 测试 / 代码规范 / 功能覆盖矩阵 / deepResearch 整合分析 |
| `doc/knowledge/` | Skill 注册表 / MCP 协议 / 多智能体架构 / 质量评分 / Milvus Lite / Vue3+SSE / Langfuse |
| `doc/deployment/` | 部署导览与总览 / 故障排查手册 |

文档总索引见 [`doc/README.md`](./doc/README.md)（四分区：`analysis` 当前事实 / `design` 目标形态 / `plan` 待办 / `knowledge` 通用原理）。
