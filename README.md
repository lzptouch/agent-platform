# agent

整合 **5 条能力链**（Skill / MCP / RAG / Web Research / Deep Research）的 Agent 平台。

> **交付形态**：**一个桌面软件**（Electron 壳 + 内嵌 TypeScript 后端 sidecar）。
> **单一运行时**：Node（不再需要 Python / Docker / 手动起服务）。
> **改造依据**：`doc/design/16-桌面一体化改造方案与实施计划.md`

---

## 目录结构

```
agent/
├── apps/
│   ├── desktop/             # 桌面壳（Electron 33 主进程 + utilityProcess 编排 sidecar）
│   │   └── src/{main,preload,shared}
│   ├── server/              # ★ TS 后端（Fastify 5 · Drizzle · better-sqlite3）
│   │   ├── src/
│   │   │   ├── http/        #   app / routes / middleware / sse / static / bootstrap
│   │   │   ├── domain/      #   agent run tools scheduler research skill team
│   │   │   │                #   exec security workspace rag web accounting
│   │   │   ├── db/          #   schema / client / migrate
│   │   │   ├── mcp/         #   manager / transport / servers
│   │   │   ├── workers/     #   沙箱（Node 必备 + Python 可选）
│   │   │   ├── runtime/     #   Python 运行时管理 / Skill 安装
│   │   │   └── shared/      #   config errors logger types llm
│   └── ui/                  # 桌面渲染层（Vue 3 + Vite + Element Plus + Pinia）
│
├── skills/                  # 6 个内置 Agent Skill
├── contract/                # ★ 契约冻结产物（只读）
│   ├── openapi.json         #   98 路径 / 126 操作
│   ├── events.json          #   26 事件 + 4 条 SSE 协议
│   ├── errors.json          #   错误码枚举 + HTTP 映射
│   └── tables.sql           #   22 表 DDL
├── baseline/features.csv    # ★ 功能基线清单（185 项 · 唯一「功能一致」判据）
├── doc/                     # 文档集（analysis / design / knowledge）
├── scripts/                 # 构建 / 生成脚本（build-desktop / rebuild-native / gen_*）
│   └── ui/                  #   build-frontend.mjs
├── tests/                   # ★ 全部测试统一归拢（2026-11-02）
│   ├── unit/                #   各端单测（server / desktop / ui，vitest）
│   ├── desktop|packaged|visual/  # 根级 E2E（pytest + Playwright）
│   ├── e2e/                 #   大模型端到端（Node + Playwright 驱动安装包）
│   ├── scripts/             #   校验 / 验证脚本（check_* / verify_* / smoke / ui_probe）
│   ├── docs/                #   测试文档（testing/00 计划 · test-runs/ 证据链 · traceability）
│   ├── report/              #   测试报告与截图（runs / archive / shots）
│   └── common/              #   公共骨架（harness / report / classify）
└── deploy/                  # 桌面端发布手册
```

---

## 快速开始

### 开发态

```bash
# 安装依赖
cd apps/server && npm install && cd ../..
cd apps/ui && npm install && cd ../..
cd apps/desktop && npm install && cd ../..

# 三进程
cd apps/server && npm run dev        # TS 后端（AGENT_PORT=18040）
cd apps/ui && npm run dev            # Vite（5185，proxy /api → 18040）
cd apps/desktop && npm start         # Electron 壳
```

### 打包

```bash
# ⚠️ 第一步必做：生成双 ABI 原生模块（Node 137 + Electron 130）
node scripts/rebuild-native.mjs

# 第二步：一条命令完成前端 → 后端 → 暂存 → 壳 → 安装包
node scripts/build-desktop.mjs --platform mac --arch arm64 --publish never

# 第三步：打包态自检
node tests/scripts/verify-desktop-package.mjs
```

产物在 `apps/desktop/release/`（macOS arm64 dmg **125MB** / zip；另有 x64 版本）。
详见 [`deploy/README.md`](deploy/README.md)（**发布手册**：前置条件、体积预算、实机验收清单、常见问题）。

### 测试

```bash
cd apps/server && npm test       # TS 后端 vitest   → 69 passed（5 文件）
cd apps/ui && npm test           # 前端 vitest       → 102 passed（20 文件）
cd apps/desktop && npm test      # 桌面壳 vitest     → 62 passed（11 文件）

# 接口冒烟（35 端点 / 38 断言）
AGENT_DESKTOP_TOKEN=<token> node tests/scripts/ui/smoke.mjs http://127.0.0.1:<port>

# 大模型端到端（Playwright 驱动真实安装包；需 .env 里的密钥）
cd tests/e2e && npm install && npx playwright install chromium && node llm-e2e.mjs
```

| 门禁 | 命令 | 作用 |
| --- | --- | --- |
| 契约闸门 1~4 | `cd apps/server && npx vitest run`（用例在 `tests/unit/server/`） | 路径/操作 · 事件/SSE · 表 DDL · 响应形状 · 功能基线 |
| 文档一致性 / 数字 / 追溯 | `python3 tests/scripts/check_doc_{consistency,numbers,traceability}.py` | 文档不得与代码脱节 |
| 前后端字段一致 | `python3 tests/scripts/check_frontend_shape.py` | 前端读的字段后端必须给 |
| 与改造前响应键一致 | `node tests/scripts/dump_response_keys.mjs` + `python3 tests/scripts/check_python_parity.py` | 等价性逐端点比对 |

测试记录与证据链见 [`tests/docs/test-runs/README.md`](tests/docs/test-runs/README.md)；
**大模型端到端验收**见 [`tests/docs/test-runs/P9-final/E2E-LLM-验收报告.md`](tests/docs/test-runs/P9-final/E2E-LLM-验收报告.md)。

---

## 架构

```
┌──────────────────────────────────────────────────────────────────┐
│ Agent Desktop (Electron 33)                                      │
│  ┌─────────────────────┐        ┌────────────────────────────┐  │
│  │ 主进程（壳）          │        │ 渲染进程（Vue 3，apps/ui） │  │
│  │ · 单实例 / 托盘 / 热键 │        │  api → '/api/v1' 同源      │  │
│  │ · utilityProcess 编排  │        │  EventSource SSE           │  │
│  └──────────┬──────────┘        └────────────▲───────────────┘  │
│             │ utilityProcess.fork()            │ http 127.0.0.1 │
│             ▼                                   │                │
│  ┌──────────────────────────────────────────────┴──────────────┐ │
│  │ Node Sidecar（TS 后端 · Fastify 5）                           │ │
│  │  http/  domain/  db/  mcp/  workers/  runtime/  shared/       │ │
│  └─────────────────────────────────────────────────────────────┘ │
│        │                │                │              │         │
│        ▼                ▼                ▼              ▼         │
│   userData/data/    vectors/          LLM/Search API   内置 Skill/ │
│   app.db + outputs  chunks.db                          （只读）    │
└──────────────────────────────────────────────────────────────────┘
```

### 实测结果（2026-11-01）

| 套件 | 改造前 | 改造后 | 差异 |
| --- | ---: | ---: | --- |
| 后端全量 | 692 / 3 skip / 0 fail | **692 / 3 skip / 0 fail** | **0** ✅ |
| 前端 vitest | 102 | **102** | **0** ✅（业务代码 0 改动） |
| 桌面壳 vitest | 60 | **62** | +2 |
| 接口冒烟 | 37/38 | **38/38** | +1 转绿 |
| **大模型端到端** | —（改造前无此套件） | **20/20** | 新增 |
| 差异台账 | — | equivalent 10 · waived 6 · **defect 0** | ✅ |

**大模型能力实测**：问「中国的首都是哪里」→ 答「北京」（首字 522ms）；追问能记住上下文；
RAG 真实 PDF 入库 → 混合检索命中 1 条（Embedding `text-embedding-v3`，维度 1024）；
13 个功能页零渲染错误、零白屏。

### 关键设计约束（与改造前保持一致）

| 项 | 值 |
| --- | --- |
| HTTP 契约 | 98 路径 / 126 操作（`contract/openapi.json` 冻结） |
| Agent 事件 | 26 种（`contract/events.json` 冻结） |
| 业务表 | 22 张（`contract/tables.sql` 冻结） |
| SSE 端点 | 4 条（含 `Last-Event-ID` 续传、`max_events` 有界模式） |
| 握手协议 | `AGENT_DESKTOP_READY {json}`（**不变**） |
| Agent 循环上限 | `max_iterations = 20` |
| 执行限额 | CPU 60s / 内存 1GB / 句柄 256 / 单文件 64MB / 输出 64KB / 墙钟 180s |
| 调度 | 交互槽 4 与调度槽 2 **分离**；`(task_id, scheduled_for)` 幂等 |
| 权限 | 三态 allow/ask/deny；ask 超时 120s 按 deny；「仅此一次」不落库 |
| RAG | 混合检索权重 sparse 0.7 / dense 1.0 / limit 10；BM25 k1=1.5 b=0.75 |

---

## 配置

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `DASHSCOPE_API_KEY` | 空 | **主 LLM + Embedding**（缺失则 Agent 运行与 RAG 不可用） |
| `LLM_API_KEY` | 空 | 备选 LLM（DeepSeek 等，用于 planner / RAG 问答） |
| `BOCHA_API_KEY` / `SERPER_API_KEY` | 空 | 深度研究 / Web Research 检索（任一即可） |
| `GAODE_API_KEY` | 空 | 高德地图（MCP weather Server 的地理编码） |
| `AGENT_PORT` | 0（OS 分配） | 开发态固定后端端口 |

> 桌面态由壳写入 `<userData>/config.json`（首启设置向导），不依赖 `.env`。

---

## 相关文档

| 文档 | 内容 |
| --- | --- |
| `doc/design/16-桌面一体化改造方案与实施计划.md` | 本次改造的完整方案与实施计划 |
| `doc/design/03-桌面壳与后端进程编排设计.md` | sidecar 进程编排（`utilityProcess`） |
| `doc/design/14-测试与发布策略.md` | 测试分层与发布门禁 |
| `tests/docs/test-runs/README.md` | 测试记录总索引 |
| `baseline/features.csv` | 功能基线清单（185 项） |
| `deploy/README.md` | 桌面端发布手册 |
