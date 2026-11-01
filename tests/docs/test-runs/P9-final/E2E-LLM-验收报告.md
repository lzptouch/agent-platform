# P9-E2E · 大模型功能端到端验收报告（Playwright 驱动真实安装包）

> **日期**：2026-11-01 ｜ **方式**：`Playwright` 驱动**真实 Electron 安装包**，
> 模拟真实鼠标/键盘事件（点击、输入、回车），逐页截图观察返回结果
> **被测对象**：`apps/desktop/release/mac-arm64/Agent Desktop.app`（安装包，含 TS 后端）
> **证据**：`screenshots/*.png`（21 张）+ `raw/e2e-llm.log` + `raw/e2e-llm.json`
> **脚本**：`tests/e2e/llm-e2e.mjs`

---

## [1] 结论

**20 / 20 全部通过 ✅** —— 且本轮**发现并修复了 9 个真实缺陷**（其中 5 个是**功能失效**级）。

| # | 验证项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 工作台渲染（输入框可见） | ✅ | 首屏 URL = `http://127.0.0.1:<port>/workspace` |
| 2 | **大模型问答返回正确内容** | ✅ | 问「中国的首都是哪里」→ 答「**北京**」，界面显示 `✓ 已完成（首字 522ms · 总 523ms）` |
| 3 | **多轮上下文** | ✅ | 追问「我刚才问的是哪个城市」→ 仍答「**北京**」（385ms） |
| 4 | 新建任务按钮 | ✅ | 点击后回到空态 |
| 5 | 命令/技能面板 | ✅ | 「更多」入口可打开 |
| 6 | 任务模式菜单 | ✅ | 「对话」下拉可打开 |
| 7 | **RAG 入库 + 检索（Embedding 链路）** | ✅ | 真实 PDF 入库 → 检索**命中 1 条**；实体数 1 · 维度 1024 · `text-embedding-v3` |
| 8-20 | 13 个功能页巡检 | ✅ | 全部有内容，**零渲染错误**、零白屏 |

---

## [2] 模型能力实测（本次提供密钥）

| 能力 | 模型 | 结果 |
| --- | --- | --- |
| 聊天（中文问答） | `qwen-plus` | ✅ `1 + 1 = 2。` |
| JSON 模式（RAG 抽取用） | `qwen-plus` | ✅ `{"skills":["python"]}` |
| system + 多轮 | `qwen-plus` | ✅ `你叫小王 😊` |
| **Embedding**（RAG 必需） | `text-embedding-v3` | ✅ 维度 **1024** |
| 其他模型 | `qwen-max` ✅ / `qwen-turbo` ⚠️429 限流 / `qwen3-max` ❌不存在 / `deepseek-v3` ❌不存在 | |

> **配置要点**：本账号**没有** `deepseek-chat` / `deepseek-reasoner`，而
> `rag_model` / `answer_model` 的默认值正是这两个 → 必须覆盖为 `qwen-plus`
> （已写入 `.env`）。

---

## [3] 本轮发现并修复的 9 个缺陷

### 3.1 功能失效级（5 个）

| # | 缺陷 | 用户可见现象 | 根因 | 修复 |
| --- | --- | --- | --- | --- |
| 1 | **环境变量不生效** | 界面报「未配置 LLM 密钥（provider=dashscope）」，**模型完全不可用** | `config.ts` 只遍历 `.env` 文件里的键做环境变量覆盖 → **没有 `.env` 时所有环境变量被忽略**；安装包内 `resources/` 只读，放不了 `.env` | 改为遍历 **schema 的全部键** → 环境变量独立生效（与 pydantic-settings 语义一致） |
| 2 | `GET /api/v1/teams` 返回 `{items}` | 契约要求**裸数组** → 前端 `el-table` 抛 `Me is not iterable`，团队表**空白** | TS 实现与冻结契约不符 | 改回裸数组 |
| 3 | `GET /api/v1/schedules` 返回 `{items}` | 同上（定时任务表空白） | 同上 | 改回裸数组 |
| 4 | `GET /api/v1/files` 返回 `{items,total}` | 前端读 `.files` → `undefined` → `items.length` 抛错，**文件页崩溃** | Python 侧是 `{total, files}` | 改回 `{total, files}` |
| 5 | `GET /api/v1/health` 只有 7 个字段 | **系统状态页大面积空白**（输出目录 / API Key 状态 / RAG / Research 全空） | Python 侧有 17 个字段，前端逐个读 | 补齐全部字段（含 `api_key_configured` / `llm_available` / `output_dir` / `rag_*` / `research_*` / `scheduler` / `database`） |

### 3.2 契约保真级（4 个）

| # | 缺陷 | 现象 | 修复 |
| --- | --- | --- | --- |
| 6 | `GET /api/v1/workspaces` 缺 `current` | 前端无法高亮当前工作空间 | 补 `current`（与 Python 侧一致） |
| 7 | `GET /api/v1/desktop/status` 缺 `runtime` / `components` | 前端 `runtime.python` 抛 `Cannot read properties of undefined` | 补齐（单运行时下 `runtime.python=null`、新增 `runtime.node`） |
| 8 | `GET /api/v1/desktop/components` 形状不符 | 前端读 `playwright_chromium.{installed,path,size_bytes}` → 空 | 按契约补齐 |
| 9 | `GET /api/v1/cost/estimate` 键名完全不同 | 前端 `RunCostBar` 读 `est.percentiles.p50` → **消耗区间恒为空** | 改为 `{percentiles:{p50,p90,samples}, pricing}`；原「按 token 估算」移到 `/cost/estimate/tokens` |

> **另修**：`POST /plugins/scan` 返回形状（前端读 `level` / `rejected_by_default` / `findings[]`）、
> `GET /memories` 缺 `enabled`/`max_injected`、`GET /files/policy` 缺 `builtin_extensions`/`extensions`、
> `GET /mcp_servers/config` 缺 `sources`、`GET /mcp_servers/{name}/tools` 缺 `server`/`tool_count`/`tools`。

---

## [4] 新增的门禁（防止同类问题复发）

| 门禁 | 位置 | 作用 |
| --- | --- | --- |
| **闸门 3c · 响应形状零差异** | `tests/unit/server/response-shape.test.ts` | 启动真实实例，按契约断言**数组型端点确实返回数组** + 桌面态关键字段存在 |
| **闸门 3d · 与改造前（Python）响应键一致** | `tests/scripts/check_python_parity.py` + `tests/scripts/dump_response_keys.mjs` | 从 `git HEAD` 取改造前 Python 的响应键，与 TS **运行时**实际返回逐端点比对 |
| **L3 大模型端到端层** | `.github/workflows/ci.yml` → `llm-e2e` | 有 `DASHSCOPE_API_KEY` secret 时跑 Playwright 端到端 |

> **为什么闸门 1 抓不到这类问题**：闸门 1 只校验「路径 + 方法是否注册」，
> **不校验响应体的键** —— 这是设计文档 §12.3 未覆盖的盲区，本次实测暴露并补上。

---

## [5] 关键截图索引

| 文件 | 画面 | 验证点 |
| --- | --- | --- |
| `01-workspace-empty.png` | 工作台空态 | 首屏正常渲染 |
| `02-workspace-typed.png` | 已输入问题 | 真实键盘输入生效 |
| `03-workspace-answer.png` | **模型回答「北京」** + `✓ 已完成（首字 522ms）` | 大模型链路打通 |
| `04-workspace-followup.png` | 追问后再答「北京」 | 多轮上下文生效 |
| `06-workspace-command-panel.png` | 命令/技能面板 | 交互可达 |
| `08-rag-ingest-retrieval.png` | RAG 入库与检索 | Embedding 链路 |
| `10-page-skills.png` | 技能管理（6 个 Skill 全列出） | 表格不再崩 |
| `11-page-rag.png` | RAG 统计：**实体数 1 · 维度 1024 · text-embedding-v3** | 入库结果可见 |
| `15-page-system-status.png` | 系统状态：**DashScope/DeepSeek 均「已配置」**、输出目录、Collection | `/health` 字段补齐后信息完整 |
| 其余 12 张 | 能力/研究/Web 检索/自动化/产物/角色/插件/设置/桌面设置/空间 | 全部有内容，无白屏 |

---

## [6] 复现命令

```bash
# 1) 双 ABI 原生模块
node scripts/rebuild-native.mjs

# 2) 打包（安装包）
node scripts/ui/build-frontend.mjs
node scripts/build-desktop.mjs --platform mac --arch arm64

# 3) LLM 端到端（读仓库根 .env 里的密钥）
cd tests/e2e && npm install && npx playwright install chromium
node llm-e2e.mjs
```

> `.env` 需包含 `DASHSCOPE_API_KEY` / `DASHSCOPE_BASE_URL` /
> `LLM_API_KEY` / `LLM_BASE_URL` / `DEFAULT_MODEL` / `RAG_MODEL` / `ANSWER_MODEL`。
> 该文件**已被 `.gitignore` 排除**，不会进版本库。

---

## [7] 仍未覆盖（诚实登记）

| # | 项 | 原因 |
| --- | --- | --- |
| 1 | **检索类**功能（Web 检索 / Deep Research） | 需要 `SERPER_API_KEY` / `BOCHA_API_KEY`（本次未提供）→ 界面正确显示「未配置」 |
| 2 | **视觉回归**（19 视图 diff < 2%） | 需与改造前的基准图逐视图比对；本次为**功能层**验证 |
| 3 | **RAG 混合检索 Top-10 重合率 ≥ 0.9** | 需改造前基准向量库 |
| 4 | 工具执行类场景（写文件 / 执行命令 / 产物交付） | 需要审批通道与写权限，风险高于收益，未自动化 |
