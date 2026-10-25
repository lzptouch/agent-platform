# 前端对标 WorkBuddy 与 Trae 工作版 —— 差异分析与改造计划

> **版本：v3.1**（2026-10-25）　　v1.0 首发 → v2.0 自评勘误 → v3.0 首轮实施 → **v3.1 全量测试与缺陷修复**
> 范围：`frontend/web/vue-element-plus`（唯一前端实现）　　后端：`backend/app`
> 文档性质：**分析 + 计划 + 实施记录 + 测试报告**。所有量化结论均可复跑验证（见 §15）；实施结果见 §16；测试报告见 §17。
>
> **v3.1 变更摘要**：新增 §17 全量测试报告 —— 8 套件全绿（后端 69/69 operation、契约 58/58、单测 17/17、E2E 28/28 + 9/9 + **84/84**，开发形态与单端口形态各跑一遍）；
> 修复 3 个真实缺陷（C1 技能校验 GET/POST 不匹配、C2 204 空响应体致删除异常、C3 `ScheduleCreate.skills` 不接受 null）；
> 新增 `contract_check.py`（前后端契约自动比对）与 `client.spec.ts`（回归用例）。
>
> **v2.0 变更摘要**：新增 §0 自评与勘误（修正 6 处事实性错误、补 5 项结构性缺陷）；重估工作量
> （前端 21~28 → **27~36** 人日）；新增阶段 0「工程基建」；重写产物索引方案（**无需新建表**）；
> 新增并发规范、全状态矩阵、13 页逐页处置表、灰度回滚方案。

---

## 0. v1 计划合理性自评

> **结论先行**：v1 的**形态判断成立**，但事实依据有 **6 处硬错误**、计划有 **5 项结构性缺陷**、工作量**低估约 30%**。本节先自评，§0.4 给出修订后的结论。

### 0.1 自评总表

| 维度 | v1 判断 | 复核结论 | 评级 |
| --- | --- | --- | --- |
| 目标形态识别（工作台 vs 管理后台） | 产品形态代差 | **成立**，官方截图与代码结构双向印证 | ✅ 可靠 |
| 7 条设计公理 | 提炼自三款产品 | **成立**，且可落到具体交互 | ✅ 可靠 |
| 后端能力盘点 | "后端已经足够" | **方向成立、细节有误**：`/files` 无 DB 索引、无 `files` 表，产物散落在 `runs.files_json` | ⚠️ 需修正 |
| 差异矩阵（IA 5 / L 8 / IX 9 项） | 逐项列差异 | **成立**，可对应到代码行 | ✅ 可靠 |
| 阶段划分 | 6 阶段 | **缺阶段 0（工程基建）**；阶段 5 优先级应下调 | ⚠️ 需补强 |
| 工作量估算 | 前端 21~28、后端 4~6 人日 | **偏低**，重估为前端 **27~36**、后端 **5~7** | ❌ 需上调 |
| 方案 C（双壳并行） | 因"13 页有测试覆盖、46 个组件依赖" | **结论可保留，两条论据均不成立**（见 #2、#5） | ❌ 论据需重写 |
| 并发 / 多任务可行性 | **未评估** | **重大缺失**：见 §3.4 | ❌ 需新增 |

### 0.2 勘误表（v1 事实性错误）

| # | v1 表述 | 代码实测事实 | 影响 |
| --- | --- | --- | --- |
| 1 | "13 条平铺路由" | **14 条** = 13 个页面 + 1 个 `{ path:'/', redirect:'/chat' }` | 轻微 |
| 2 | "已有 46 个组件依赖，重写成本过高" | **自研组件仅 3 个**（`ChatMessage`/`MarkdownView`/`ProcessSteps`）；npm 依赖仅 **8 个** | **严重**：论据失效，且说明"改造=新建"，工作量应**上调** |
| 3 | "全量 71 条 API" | **54 个 path / 69 个 operation** | 轻微 |
| 4 | "`src/api/*`：3 文件 903 行" | **5 文件 1211 行**（client 123 / endpoints 93 / index 186 / sse 185 / types 624） | 轻微 |
| 5 | "现有 13 页**有测试覆盖**" | **前端 0 个测试文件**；仅后端 12 个测试文件 | **严重**：方案 C 论据失效 |
| 6 | "`files` 有 GET/POST/DELETE，加 `session_id` 关联" | **不存在 `files` 表**。`/files` 是 `LocalCodeExecutor.output_dir` 的**文件系统直读**（文件名即 ID，无 DB 关联）；产物实际记在 `runs.files_json` | **严重**：§7.3 原方案无法执行，需重设计 |
| 7 | "命中 **2.5/7**" 与 §0 "仅满足 **2 条**" | 逐项算：A1❌ A2⚠️ A3❌ A4❌ A5❌ A6❌ A7⚠️ → **0 完全满足 + 2 部分满足 = 1.0/7** | **严重**：同文三处数字互相矛盾 |
| 8 | "前端约 **21~29** 人日" 与 §6.7 "**21~28**" | 分阶段求和 = 21~28（原表无误，§0 抄错） | 轻微 |
| 9 | "WorkBuddy 一级功能（**8**）" | 实际列举 **7 项** | 轻微 |
| 10 | "`config_json` 里预留但未实现的 space" | `config_json` 是通用配置槽，**从未包含 space 语义** | 轻微 |
| 11 | "左侧菜单 13 项**无折叠**" | 13 项中**已有 1 个分组**（`el-menu-item-group title="能力"`，含 6 项） | 轻微 |
| 12 | "「停止」仅 AbortController" | 前端用 `AbortController` 断流，**后端 run 不会被打标 cancelled**（`execute_stream` 无取消处理） | 中：需补后端取消语义 |

### 0.3 五项结构性缺陷（比数字错误更重要）

| # | 缺陷 | 为什么致命 | v2 处置 |
| --- | --- | --- | --- |
| **D1** | **未评估并发能力** | 目标是 Trae SOLO 式「多任务并行」，但后端 `execute_sync` 信号量上限 = `schedule_max_concurrent`（默认 **2**）且 `acquire(blocking=False)` 失败时**直接跳过返回 `busy`**；`execute_stream`（前端对话走这条）则**完全无护栏** | 新增 §3.4 架构约束 + §8.6 并发规范 + 阶段 4 增「并发护栏」任务 |
| **D2** | **缺阶段 0：工程基建** | 前端 4813 行、**零测试**、无 CI 门禁。直接重构，回归只能靠肉眼 | 新增阶段 0（测试与门禁）**2~3 人日** |
| **D3** | **缺逐页处置决策** | §9.2 只给"新增/复用/废弃"三个桶，13 个页面各自去留未逐个交代，执行时必卡 | 新增 §9.3 逐页处置表 |
| **D4** | **无灰度与回滚设计** | "可独立上线"只是口号，无 feature flag、无旧路径策略、无数据兼容细则 | 新增 §10.4 |
| **D5** | **只写理想态，无异常态** | 输入框需处理 12+ 种状态（加载/错误/超时/重连/限流…），v1 只画了 idle | 新增 §8.7 全状态矩阵 |

### 0.4 修订后的核心结论

| # | 结论 | 依据 |
| --- | --- | --- |
| 1 | 现状是**「管理后台 + 13 个平铺功能页」**，目标是**「单一任务工作台 + 左栏任务流」**——是产品形态代差，不是样式差异 | 官方截图 + 路由表 |
| 2 | 共同骨架：**左栏 = 能力入口 + 任务列表；主区 = 单会话工作台 + 居中大输入框**，全站一个对话入口 | 两张官方截图 |
| 3 | 7 条公理中现状 **0 条完全满足 + 2 条部分满足（A2/A7）= 1.0/7** | §2.4 逐项计分 |
| 4 | 后端**基本够用但"未组织"**：54 path/69 operation 覆盖会话、运行账本、审批、团队、定时、技能；`GET /sessions/{id}` 已返回**带消息分页的 `SessionDetail`**，是"任务即会话"的现成地基 | `openapi.json` + `sessions.py` |
| 5 | 后端真实缺口 **4 项**（v1 写 3 项）：`space`、`attachments`、**产物索引**（无表，只能靠 `runs.files_json` 反查）、**并发护栏** | §7 |
| 6 | 前端**从 0 建**：需新增约 **16 个组件**（现有自研组件仅 3 个）→ 工作量上调至 **27~36 人日**；后端 **5~7 人日** | §6.8 |
| 7 | 仍推荐**双壳并行**，但论据改为：13 个后台页是**管理型 CRUD 模型**，工作台是**对话型流式模型**，共用一壳会互相污染状态与心智 | §9.1 |

---

## 1. 调研方法（可复现）

### 1.1 工具链

| 环节 | 工具 | 用途 |
| --- | --- | --- |
| 官方界面取证 | Playwright（Python，`backend/.venv` 内已装）+ Chromium | 渲染并截图 Trae Work 网页版真实界面、WorkBuddy 官网真实界面 |
| 本地界面取证 | 同上 | 对本项目 13 个页面批量截图 + 提取 DOM 结构特征（导航项/按钮/输入占位符） |
| 文档与交互逻辑 | `web_search` / `web_fetch` | 抓取 Trae SOLO 三栏布局、Builder/Coder 工作流、WorkBuddy 模式与功能模块定义 |
| 代码事实核对 | `read_file` / `search_content` | 逐文件核对前端实现与后端 API，避免"看图说话" |

### 1.2 采集清单（本次实际执行）

| 目标 | URL / 路径 | 产物 |
| --- | --- | --- |
| 本项目 13 个页面 | `http://127.0.0.1:5185/{chat,work,teams,schedules,skills,research,mcp,rag,web,files,wr,status,settings}` | `assets/cur_*.png` |
| WorkBuddy 官网 | `https://www.workbuddy.cn/` | `assets/ref_workbuddy_site.png` |
| **WorkBuddy 客户端真实界面** | 官网 Hero 素材 `hero-app-shot-ClS5-M_E.webp`（2976×1860，2×） | `assets/ref_workbuddy_home_ui.png` |
| Trae 官网 | `https://www.trae.cn/`、`https://www.trae.cn/work` | `assets/ref_trae_work_site.png` |
| **Trae Work 网页版真实界面** | `https://work.trae.cn/`（未登录态亦渲染完整外壳） | `assets/ref_trae_work_ui.png` |
| Trae SOLO 交互逻辑 | 掘金 / ima 知识库 / CSDN / 网易 多源交叉 | 见 §11 |

### 1.3 复现命令

```bash
# 本地页面取证（需后端 18040 + 前端 5185 已启动）
cd backend && .venv/bin/python ../frontend/scripts/ui_probe/shoot_local.py

# 官方界面取证（Trae Work 网页版 / WorkBuddy 官网 / Trae 社区）
cd backend && .venv/bin/python ../frontend/scripts/ui_probe/shoot_external.py

# WorkBuddy 高清界面素材
curl -sSL -o wb_hero.webp \
  "https://assets.workbuddy.cn/web/workbuddy/a5b2fb510f0e7b156f19d072fae0cd12ae1f2f19/assets/hero-app-shot-ClS5-M_E.webp"
sips -s format png wb_hero.webp --out wb_hero.png && sips -Z 1400 wb_hero.png --out wb_hero_1400.png
```

> 取证脚本已随仓库保存在 `frontend/scripts/ui_probe/`（`shoot_local.py` / `shoot_external.py`），
> 依赖 `backend/.venv` 内已安装的 Playwright，默认输出到 `/tmp/agent_ui_probe/`。

---

## 2. 基准形态拆解

### 2.1 WorkBuddy（腾讯 · 全场景 AI 办公工作台）

> 证据：`assets/ref_workbuddy_home_ui.png`（官网官方素材，客户端真实界面）+ 官网文案 + 多个第三方实测文章。

#### 2.1.1 全局信息架构

```
┌──────────────┬──────────────────────────────────────────────────────┐
│ 左栏 (220px) │ 主区（单任务工作台）                                │
│              │                                                      │
│  ⌘▢ ⌕ ⚙      │           WorkBuddy, 我帮你                          │  ← 居中大标题
│              │      [日报办公] [代码开发] [创建设计]                   │  ← 场景 Chip
│ 新建任务 ●    │                                                      │
│ 助理          │   [文档处理][金融服务][数据分析与可视化][深度研究]      │  ← 能力 Chip 行
│ 项目          │   [幻灯片][更多 >]                                   │
│ 专家·技能·连接器│  ┌────────────────────────────────────────────┐   │
│ 自动化        │  │ 今天帮你做些什么？ @ 引用对话 / 调用技能      │   │  ← 大输入框
│ 资料库        │  │                                            │   │
│ 更多 (应用·灵感)│  │ +                          快速⌄ 🎤 (↑)   │   │
│              │  └────────────────────────────────────────────┘   │
│ 任务 (18) ⌄  │   □ 选择工作空间⌄   ☑ 默认权限⌄                    │  ← 框外工具条
│ 空间 (20) ⌄  │                                                      │
│              │                                                      │
│ 👤 lolkima    │                                                      │
│    企业版     │                                                      │
└──────────────┴──────────────────────────────────────────────────────┘
```

#### 2.1.2 左栏细节（逐项实测自官方素材）

| 元素 | 细节 | 对本项目的含义 |
| --- | --- | --- |
| 顶部窗口区 | macOS 红黄绿三键 + 右侧 3 个图标（面板折叠 / 搜索 / 筛选） | 折叠、搜索、筛选三件套当前**全部缺失** |
| 产品名 | `WorkBuddy` 独立一行（无 Logo 方块） | 当前是 "A" 方块 + "Agent Platform" |
| 一级功能（**7 项**） | 新建任务 / 助理 / 项目 / 专家·技能·连接器 / 自动化 / 资料库 / 更多（应用·灵感） | 当前是 13 个平铺项，**没有"新建任务"作为第一入口** |
| 选中态 | 新建任务 = 浅灰圆角底（**非强调色描边**） | 当前用 `--accent` 蓝色 outline 描边，视觉过重 |
| 分组折叠 | `任务 (18) ⌄` / `空间 (20) ⌄` —— 计数 + 展开箭头 | 当前会话列表**只在 /work 页的二级侧栏**，且按 mode 过滤后只有一种 |
| 底部账号区 | 头像 + 用户名 + `企业版` 标识 | 当前**完全没有**（无用户体系，见 §7.4） |
| 图标风格 | 统一 1.5px 线性图标，尺寸 16px | Element Plus 图标可满足，需统一尺寸 |

#### 2.1.3 主区与输入框细节

| 元素 | 规格 | 证据 |
| --- | --- | --- |
| 大标题 | 居中、约 28px、半粗，正文色（不是纯黑） | 官方素材 |
| 场景 Chip | 3 个，圆角胶囊，图标 + 文字（日报办公 / 代码开发 / 创建设计） | 官方素材 |
| 能力 Chip 行 | 6+ 个（文档处理 / 金融服务 / 数据分析与可视化 / 深度研究 / 幻灯片 / 更多 >），带小图标 | 官方素材 |
| 输入框 | 圆角 ~16px 大卡，内高 ~90px，**上下留白充裕** | 官方素材 |
| 输入框占位符 | `今天帮你做些什么？ @ 引用对话 / 调用技能` —— **把 @ 与 / 直接写进占位符** | 官方素材 |
| 输入框左上 | `+`（附件/上下文） | 官方素材 |
| 输入框右下 | 模型选择 `快速⌄` + 麦克风 + 圆形发送键（↑） | 官方素材 |
| 框外底条 | `□ 选择工作空间⌄` / `☑ 默认权限⌄` —— **在输入框之外** | 官方素材 |
| 对话进行中 | 输入框上移、对话区推入、底部固定 | 第三方实测文章 |

#### 2.1.4 交互逻辑要点

1. **任务 = 对话**：左侧「任务」列表即历史会话（18 条），任务之间上下文互不干扰。
2. **空间 = 文件夹**：左侧「空间」(20) 用于把同一项目下的任务归档 —— 这正是本项目 `sessions.config_json` 里**预留但未实现**的概念。
3. **工作空间 = 工作目录**：输入框下方「选择工作空间」决定 Agent 的文件读写根目录，与本项目 `backend/data/outputs` 的隐式单目录形成对照。
4. **默认权限**：一键切换 Agent 的工具权限（等价本项目 `mode=chat/work` 的工具档案 `ToolProfile`）。
5. **三种模式**：普通 / **Plan**（先出计划、人工确认后执行）/ **Craft**（全自动读写文件）—— 与本项目 `chat/work + plan_first` 语义同构，但**命名与入口位置不同**。
6. **记忆系统**：`/remember` 命令，三层记忆（云 / 本地 / 工作区）。
7. **专家 / 技能 / 连接器**：合并为一个左栏入口 —— 本项目目前拆成「技能团队 / Skill 管理 / MCP 控制台」三个页面，**颗粒度不一致**。

### 2.2 Trae Work（字节 · 网页版，2026 新形态）

> 证据：`assets/ref_trae_work_ui.png`（`https://work.trae.cn/` 未登录态完整渲染）+ `https://www.trae.cn/work` 官网文案。

```
┌──────────────┬──────────────────────────────────────────────────────┐
│ 左栏 (200px) │                              [下载桌面端] [⊡]        │
│  ⊡  ⌕        │                                                      │
│ 新建任务 ⌘⌃N ●│              Build with TRAE                        │  ← 居中大标题
│ 插件市场      │      ┌────────────────────────────────────┐         │
│ 自动化        │      │ @ 添加上下文，/ 使用命令和技能      │         │
│ 模板库        │      │                                    │         │
│ 我的产物      │      │ +  @              Auto Mode⌄ 🎤 (↑) │         │
│              │      └────────────────────────────────────┘         │
│ 任务列表  ⚙   │        🗂 选择仓库（可选）⌄                        │  ← 框外工具条
│              │                                                      │
│   暂无任务    │    [应用开发] [项目理解] [游戏创意] [工具脚本]         │  ← 模式卡
│              │                                                      │
│ 登录 →        │                                                      │
│ 下载桌面端    │                                                      │
└──────────────┴──────────────────────────────────────────────────────┘
```

| 维度 | Trae Work | 与 WorkBuddy 的关系 |
| --- | --- | --- |
| 能力 Chip | 换成了 **4 张模式卡**（应用开发 / 项目理解 / 游戏创意 / 工具脚本） | 与 WorkBuddy 的「场景 Chip」同位 |
| 上下文入口 | 输入框占位符 `@ 添加上下文，/ 使用命令和技能` + 左下 `@` 图标 | 与 WorkBuddy 的 `@ 引用对话 / 调用技能` **几乎同构** |
| 上下文选择 | 框外 `🗂 选择仓库（可选）⌄` | 等价 WorkBuddy 的「选择工作空间」 |
| 模式切换 | 输入框右下 `Auto Mode⌄`（**下沉到输入框**） | WorkBuddy 则是顶部右侧模型选择 |
| 任务列表 | 左栏可折叠分组，带筛选图标，支持并行多任务 | WorkBuddy 同构 |
| 产物 | 左栏独立入口「我的产物」 | WorkBuddy 为「资料库」 |
| 插件/模板 | 「插件市场」「模板库」独立入口 | 本项目有「Skill 管理」可对应插件市场 |

### 2.3 Trae SOLO（IDE 内三栏 —— "白盒化"的任务执行视图）

> 证据：掘金《Trae 实战：4 项功能把活整个交给 AI》、ima 知识库《@Trae 精炼指南》、CSDN 实测、网易实测，**四源交叉验证**。

| 栏位 | 内容 | 与本项目对应 |
| --- | --- | --- |
| **左：多任务窗口** | 并行管理多个任务，展示执行状态 | 本项目 `WorkView` 左栏已有会话列表，但**仅单任务、无并行状态** |
| **中：对话流** | 需求沟通 → 任务执行 → 修改记录的完整过程 | 本项目 `WorkView` 中栏已有消息 + 步骤流，**最接近** |
| **右：工具面板** | 文档（PRD）/ DiffView / 部署 / 内置浏览器预览 | 本项目**完全缺失**（产物只在消息气泡里以附件形式出现） |

**SOLO Builder 交互链（官方路径）**：

```
自然语言需求
   └─► @SOLO Builder
        └─► Doc 工具生成结构化 PRD（右侧「文档」面板实时呈现）
             └─► 对话迭代需求
                  └─► 「查看变更」→ 红绿 Diff 对比
                       └─► 人工编辑 / 版本管理 / AI 协助修改
                            └─► 「确认，开始开发」
                                 └─► 自动实现 + 内置浏览器实时预览
```

**SOLO Coder vs Builder 分工**：Builder = 0→1（PRD 驱动、端到端搭建）；Coder = 1→N（在既有代码上迭代）。

**Trae 快捷键**：`Option+P` 切换 Plan 模式；`Ctrl+Enter` 接受变更；`Ctrl+Backspace` 撤销变更；`Ctrl+U` 把终端报错加入对话。

### 2.4 共性设计范式（提炼为 7 条公理）

| # | 公理 | WorkBuddy | Trae Work | Trae SOLO | 当前本项目 | 满足 |
| --- | --- | --- | --- | --- | --- | --- |
| A1 | **单对话入口**：全站只有一个主工作台，其余为二级页面 | ✅ | ✅ | ✅ | ❌ 13 个平铺页各有各的输入框 | 0 |
| A2 | **左栏 = 能力入口 + 任务流**，任务流在主区左侧常驻 | ✅ | ✅ | ✅ | ⚠️ 仅 `/work` 有，切页即消失 | 0.5 |
| A3 | **模式/模型选择器下沉到输入框右下角** | ✅ | ✅ Auto Mode | ✅ | ❌ 在顶栏 | 0 |
| A4 | **`@` 引用上下文 + `/` 唤起命令与技能**（占位符即入口说明） | ✅ | ✅ | ✅ | ❌ 完全无 | 0 |
| A5 | **上下文/工作区选择器在输入框之外**（框下工具条） | ✅ | ✅ | ✅ | ❌ 无（`output_dir` 隐式单目录） | 0 |
| A6 | **能力做成 Chip / 卡片**，不是全局复选框 | ✅ | ✅ | ✅ | ❌ 顶栏 4 个复选框 + 2 个 Popover | 0 |
| A7 | **任务即会话、空间即文件夹** | ✅ | ⚠️ 仅任务 | ✅ 多任务窗口 | ⚠️ 有会话（历史可恢复）、无空间 | 0.5 |

**计分：0 条完全满足 + 2 条部分满足（各计 0.5）= 1.0 / 7 —— 这是本次改造的核心量化结论。**

> v1 误写为"2.5/7"且在 §0 写"仅满足 2 条"，三处互相矛盾，v2 统一为 **1.0/7**。
> 补充：A7 的"会话"半边现状其实**合格** —— `GET /api/v1/sessions/{id}` 返回含消息分页的 `SessionDetail`，
> `ChatView` / `WorkView` 均已用它恢复历史（`detail.messages`）。缺的只是"空间"维度。

---

## 3. 当前前端现状（代码事实 + 截图证据）

### 3.1 现状截图

| 页面 | 截图 | 观察 |
| --- | --- | --- |
| 对话 `/chat` | `assets/cur_chat.png` | 顶栏 4 个能力复选框 + 2 个 Popover；欢迎卡片是一张灰底 `el-card`，非居中大标题 |
| 工作 `/work` | `assets/cur_work.png` | 二级左栏（会话列表 220px）+ 顶栏 segmented/Plan/团队/Skill；空态是 Element 默认 `el-empty` 插画 |
| 技能团队 `/teams` | `assets/cur_teams.png` | 表格型 CRUD，与左栏入口概念重复 |
| 定时任务 `/schedules` | `assets/cur_schedules.png` | 表格型 CRUD |
| Skill 管理 `/skills` | `assets/cur_skills.png` | 表格 + 资源树，最"重"的一页 |
| 深度研究 `/research` | `assets/cur_research.png` | 独立任务提交页，与对话页功能重叠 |
| 系统状态 `/status` | `assets/cur_status.png` | 纯诊断页 |

### 3.2 代码事实（v2 复核后的准确数据）

| 文件 / 指标 | 实测 | 关键事实 |
| --- | --- | --- |
| `src/router/index.ts` | 37 行 | **14 条路由** = 13 个页面 + 1 个 `{ path:'/', redirect:'/chat' }`；无布局路由、无嵌套 |
| `src/App.vue` | **154 行** | `el-aside` 220px 固定菜单 **13 项**（含 1 个 `el-menu-item-group title="能力"` 分组 6 项）；`el-header` 60px 承载 4 个能力复选框（MCP/RAG/Web/反思）+ 2 个 Popover；**右下角为版本串** `P0 · Vue 3 + Element Plus · v0.1.0` |
| `src/views/*.vue` | **13 个文件** | `ChatView`(379) / `WorkView`(435) / `ResearchView`(332) 三页**各自实现了一套输入框 + 能力开关**（重复实现是 IA 混乱的根源） |
| `src/components/*.vue` | **仅 3 个** | `ChatMessage` / `MarkdownView` / `ProcessSteps` —— **自研组件几乎为零，全靠 Element Plus**；改造 = **从 0 建**，不是"改" |
| `src/api/*` | **5 文件 1211 行** | `client`(123) / `endpoints`(93) / `index`(186) / `sse`(185) / `types`(624)；**SSE 封装完备，是核心资产** |
| `src/stores/` | 2 文件 175 行 | `config`(82) 全局能力开关；`session`(93) 仅 `mode` 单维，`loadSessions` 按 mode 过滤；**无 space 概念** |
| `src/styles/tokens.css` | 82 行 | 12 组颜色 token + 圆角/阴影/字体；**已支持暗色模式**（`prefers-color-scheme`）—— 官方两款为纯浅色，暗色是本项目**独有优势，必须保留** |
| npm 依赖 | **8 个** | `vue` `vue-router` `pinia` `element-plus` `@element-plus/icons-vue` `markdown-it` `highlight.js` `dompurify` |
| 前端源码总量 | **4813 行** | `vue` / `ts` / `css` 合计 |
| 前端测试 | **0 个** | 无 `*.spec.*` / `*.test.*`，无 vitest/playwright 前端用例 → 见缺陷 D2 |

### 3.3 后端能力盘点（`openapi.json`：**54 path / 69 operation**）

| 目标形态所需 | 后端现状 | 结论 |
| --- | --- | --- |
| 会话（任务）CRUD + 分页 | `GET/POST /sessions`、`GET/PATCH/DELETE /sessions/{id}` ✅ | **够用** |
| **会话历史消息** | `GET /sessions/{id}` → `SessionDetail`（**含消息分页**）✅ | **够用**，"任务即会话"的现成地基 |
| 模式 chat/work | `POST /agent/run` 支持 `mode` + `plan_first` ✅ | **够用** |
| 工具权限档案 | `ToolProfile`（`services/tool_registry.py`，`CHAT`/`WORK` 两档）✅ | **够用**，Ask/Plan/Craft 三态映射到两档 + 开关 |
| Plan 人工审批 | `POST /agent/runs/{id}/approve|reject` ✅ | **够用** |
| 运行账本 + 事件回放 | `GET /runs`、`/runs/{id}`、`/runs/{id}/events`、`/runs/{id}/stream` ✅ | **够用**（SOLO 右栏事件流可直接复用） |
| 技能 / 团队 | `skills` 12 条、`teams` 7 条 ✅ | **够用**（对应「专家·技能·连接器」「插件市场」） |
| 定时任务（自动化） | `schedules` 9 条 ✅ | **够用** |
| 产物文件 | `/files`：`GET` 列表 / `POST /upload` / `GET {name}` / `DELETE {name}` | ⚠️ **是 `output_dir` 文件系统直读，无 `files` 表、无 `session_id` 关联**；产物真正落库在 `runs.files_json` |
| 工作空间（space） | ❌ 无（`sessions` 表 9 字段：`id/mode/title/team_id/config_json/owner/archived/created_at/updated_at`） | **需新增** |
| 上下文引用（@） | ❌ 无（`RunRequest` 无 `attachments` 字段） | **需新增** |
| **并发护栏** | ⚠️ `execute_sync` 上限 = `schedule_max_concurrent`(2)，超出**跳过**；`execute_stream` **无限制** | **需新增**（见 §3.4） |
| 运行取消 | ❌ 无（前端 `AbortController` 断流后，run 仍为 `running`） | **需新增**（P1） |
| 记忆（`/remember`） | ❌ 无 | P2 |
| 账号/用户 | ❌ 无（`sessions.owner` 字段存在但无 `users` 表） | P2 |
| 深度研究 | `/research` 6 条 ✅ | 有独立任务流，可做「成果物」 |

### 3.4 后端架构约束（v1 完全缺失，直接影响计划可行性）

| 约束 | 实测证据 | 对计划的影响 |
| --- | --- | --- |
| **数据表只有 9 张** | `sessions` / `messages` / `runs` / `run_events` / `scheduled_tasks` / `skills` / `teams` / `team_skills` / `system_locks`（+ `alembic_version`）；**无 `files` 表** | §7.3 产物索引**不能靠加字段实现**，须改为聚合 `runs.files_json` 或新建 `artifacts` 表 |
| **产物记在 `runs.files_json`** | `runs` 表含 `files_json`，`run_service.finish(files=...)` 写入 | 产物索引可**零新表**实现：`GET /sessions/{id}/artifacts` = 聚合该会话所有 run 的 `files_json` |
| **同步执行并发上限 = 2** | `run_executor.py:43` `BoundedSemaphore(settings.schedule_max_concurrent)`；`:275` `acquire(blocking=False)` 失败即返回 `{"error":"busy: 并发已达上限，本次跳过","skipped":True}` | 定时任务/脚本侧最多 2 并发，**且不排队**（直接跳过） |
| **流式执行无并发护栏** | `execute_stream` 全文无 `_semaphore` 引用 | 前端**可以**并行多发 `/agent/run` 流 → "多任务并行"技术上可行，但**无上限保护**，存在打爆 LLM 配额风险 |
| **无 run 取消语义** | `execute_stream` 无取消检查；`runs.status` 无 `cancelled` 落库路径 | "停止生成"后账本状态失真；阶段 3 需补 |
| **调度用 DB 租约** | `system_locks` + `scheduler_service` 的 primary 租约 | 多实例部署时 run 并发会跨进程叠加，护栏必须放 DB 或 Redis 层 |

> **结论**：Trae SOLO 式「多任务窗口并行」在本项目**前端可行、后端缺护栏**。计划中必须把"并发上限（建议前端 3 / 后端 4）+ 排队语义 + 状态回显"列为阶段 4 的显式交付物，而不是留作隐含假设。

---

## 4. 差异矩阵

### 4.1 信息架构（P0 —— 最致命）

| # | 现状 | 目标 | 影响 |
| --- | --- | --- | --- |
| IA-1 | 13 个平铺路由各自独立 | 1 个主工作台 `/workspace`（默认首页）+ 能力后台 `/admin/*` | 用户进站后**不知道该点哪里**；13 个输入框 = 13 个心智入口 |
| IA-2 | 「对话」与「工作」是两个**页面**（`/chat`、`/work`），靠 segmented 跳转 | 同一页面内**模式切换**（Ask / Plan / Craft） | 现有 segmented 会**整页跳转**，会话列表不跟随，割裂感强 |
| IA-3 | 「深度研究」独立页，与对话页功能重叠 | 收为工作台内的一种「能力 Chip / 模板」 | 功能重复导致维护双份输入逻辑 |
| IA-4 | 「技能团队 / Skill 管理 / MCP 控制台」语义边界模糊 | 合并为「**专家·技能·连接器**」单入口，内部 Tab 分区（对齐 WorkBuddy） | 现状三页让用户分不清「团队」和「Skill」 |
| IA-5 | 无「新建任务」统一入口 | 左栏第一项固定为「新建任务」 | 目标形态的**第一动作锚点** |

### 4.2 布局与视觉（P0/P1）

| # | 现状 | 目标 |
| --- | --- | --- |
| L-1 | 顶栏 60px 常驻，承载 4 复选框 + 2 Popover + 版本号 | **取消全局顶栏**；能力开关下沉到输入框区域（对齐 A6） |
| L-2 | 版本号 `P0 · Vue 3 + Element Plus · v0.1.0` 占据顶栏黄金位 | 移至 `/admin/status` 或左栏底部账号区 |
| L-3 | 空态用 Element 默认 `el-empty` 插画 + `el-card` | 居中大标题（`Build with TRAE` / `WorkBuddy, 我帮你`）+ 场景 Chip + 能力 Chip 行 |
| L-4 | 消息区 `max-width: 880/900px` 居中，**输入框通栏** | 输入框与消息区**同宽（~560~640px）居中**，左右留白更大 |
| L-5 | 输入框为 `el-input textarea rows=3` + 独立「发送」按钮 | 圆角大卡 + 左下 `+` / `@`、右下 模型⌄ + 麦克风 + 圆形发送键；**Enter 发送 / Shift+Enter 换行提示写进占位符** |
| L-6 | 选中态用 `--accent` 蓝色 outline | 浅灰圆角底（WorkBuddy 风格），克制 |
| L-7 | 左侧菜单 13 项无折叠、无搜索、无计数 | 分组折叠（任务 N ⌄ / 空间 N ⌄）+ 顶栏搜索 + 筛选 |
| L-8 | 无账号区 | 左栏底部：头像 + 名称 + 版本/企业版标识 |

### 4.3 交互逻辑（P0/P1）

| # | 现状 | 目标 | 依据 |
| --- | --- | --- | --- |
| IX-1 | 能力开关是**全局复选框**（MCP/RAG/Web/反思） | 变成**上下文 Chip / 模式卡**，且**随会话持久化** | A6 |
| IX-2 | 模型选择在顶栏 | 下沉到**输入框右下** | A3（Trae `Auto Mode⌄`） |
| IX-3 | 无 `@` 引用、无 `/` 命令 | 输入框占位符写明 `@ 引用对话 / 使用命令和技能`，实现命令面板 | A4 |
| IX-4 | 无工作空间概念 | 框外工具条 `选择工作空间⌄` + `默认权限⌄` | A5 |
| IX-5 | Plan 审批卡片是 `el-card` 内的可编辑 input 列表 | 升级为**带序号徽标、步骤标题 + 说明双行、底部「确认执行 / 拒绝」右对齐**的独立卡片；支持**逐步执行进度回填** | Trae Builder「确认，开始开发」 |
| IX-6 | 执行过程步骤（ProcessSteps）内联在消息气泡内 | 抽为**可折叠的执行轨迹区**（Trae SOLO 中栏） | SOLO 三栏 |
| IX-7 | 产物以附件列表内联在气泡 | 独立**产物面板**（Trae SOLO 右栏 / Trae「我的产物」） | SOLO 右栏 |
| IX-8 | 深度研究进度只能在 `/research` 页看 | 任务内联进度条 + SSE 进度流 | 现有 `GET /research/{id}/stream` 已具备 |
| IX-9 | 无「停止」语义（仅 AbortController） | 停止按钮 + 停止后保留部分产出 | — |

### 4.4 能力缺口（P1/P2）

| # | 缺口 | 影响形态 | 建议 |
| --- | --- | --- | --- |
| C-1 | 工作空间 / 空间（Space） | 「空间即文件夹」「选择工作空间⌄」 | **P1**：新增 `spaces` 表 + 会话绑定 space_id |
| C-2 | 上下文引用（`@` 文件 / `@` 会话） | `@ 添加上下文` | **P1**：输入框左侧附件选择器 → `agent/run` 增 `attachments` |
| C-3 | 命令面板（`/`） | `/ 使用命令和技能` | **P1**：纯前端，`/` 唤起 Skill / 模板 / 模式命令 |
| C-4 | 产物索引 | 「我的产物」 | **P1**：后端 `files` 增加 `session_id` 关联与聚合接口 |
| C-5 | 记忆（`/remember`） | 长期偏好 | **P2**：后端 `memories` 表 |
| C-6 | 账号 / 多用户 | 左栏底部账号区 | **P2**：`users` 表 + 简单 token |

---

## 5. 改造目标形态（Target）

### 5.1 目标信息架构（v2 已与 §9.3 逐页处置表对齐）

```
/                  → 开关开启时重定向 /workspace（关闭时仍走 /chat，见 §10.4）
/workspace         【主工作台】默认首页
   ├─ Ask（对话）  = mode=chat
   ├─ Plan（计划） = mode=work + plan_first=true
   ├─ Craft（工作）= mode=work + plan_first=false   ← 三态同页切换，不跳路由
   └─ 深度研究     = 工作台内的能力 Chip（提交后内联进度）

/admin/                       【能力管理后台】
   ├─ /admin/capabilities      专家·技能·连接器（Tab：团队 / 技能 / MCP）
   │                           ← 合并原 /teams /skills /mcp 三页
   ├─ /admin/schedules         自动化（并发上限 / 退避 / 权限可视化）
   ├─ /admin/artifacts         我的产物（聚合 runs.files_json，见 §7.3）
   ├─ /admin/spaces            空间管理
   ├─ /admin/research          深度研究历史
   ├─ /admin/knowledge         RAG 知识库（原 /rag）
   ├─ /admin/web               Web 检索（原 /web，密钥未配时标注"未配置"）
   ├─ /admin/status            系统状态（承接版本串 + 并发占用面板）
   ├─ /admin/settings          设置
   └─ /admin/lab/wr            WR 范式实验（原 /wr，非主线）
```

> 旧路径 `/chat` `/work` `/research` `/teams` `/skills` `/mcp` `/schedules` `/files`
> `/rag` `/web` `/status` `/settings` `/wr` **全部保留可访问**，避免书签失效与灰度回退受阻。

### 5.2 目标布局骨架

```
┌──────────────┬───────────────────────────────────────────────────────────────┐
│ 左栏 240px   │  [任务标题 · 模式标识]                    [历史 ⌄][分享][⋯]   │ ← 轻量上下文栏
│ ┌──────────┐ │                                                               │
│ │⊡ ⌕ ⚙     │ │                    （对话流 / 执行轨迹 / 产物引用）           │
│ └──────────┘ │                                                               │
│ 新建任务      │                                                               │
│ 助理          │                                                               │
│ 项目(空间)    │                                                               │
│ 专家·技能·连接器│                                                               │
│ 自动化        │                                                               │
│ 产物          │                                                               │
│ ──────────── │                                                               │
│ 任务 (N) ⌄   │                                                               │
│  · 会话 A    │                                                               │
│  · 会话 B    │                                                               │
│ 空间 (N) ⌄   │                                                               │
│ ──────────── │                                                               │
│ 👤 用户/企业版 │                                                               │
└──────────────┴───────────────────────────────────────────────────────────────┘
                                    ▲
                          对话流底部固定「输入区」
┌───────────────────────────────────────────────────────────────┐
│  [日报办公][代码开发][创建设计]      ← 场景 Chip（空态时显示）      │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ 今天帮你做些什么？ @ 引用对话 / 使用命令和技能             │ │
│  │ +  @                          快速⌄  🎤  (↑)            │ │
│  └───────────────────────────────────────────────────────────┘ │
│   🗂 选择工作空间⌄   ☑ 默认权限⌄                               │
└───────────────────────────────────────────────────────────────┘
```

### 5.3 设计 Token 对齐

| 项 | 现状 token | 目标 | 说明 |
| --- | --- | --- | --- |
| 强调色 | `--accent: #4d6bfe` | 保留，但**不用于选中态描边** | 改用 `--bg-hover` 浅灰底做选中态 |
| 输入框圆角 | `--radius: 14px` | 输入框 16px；胶囊 Chip 全圆角 | 目标形态全是圆角胶囊 |
| 侧栏底色 | `--bg-sidebar: #f7f8fa` | 保留 | 与官方素材一致 |
| 消息区宽度 | 880/900px | **560~640px** | 目标形态输入框更窄、留白更多 |
| 字号阶梯 | body 14px | 大标题 24~28px / Chip 13px / 元信息 12px | 目标形态层级更明显 |
| 暗色模式 | 已支持 | **保留** | 官方两款为纯浅色，暗色是本项目差异化优势 |
| 动效 | 无 | Chip hover / 卡片入场 120~160ms | 目标形态有微动效 |

---

## 6. 改造计划（**7 阶段**，可独立上线）

> 人日为单人估算，含自测；不含设计稿产出。**v2 新增阶段 0**（v1 缺失，是最大计划漏洞）。

### 阶段 0 · 工程基建（2~3 人日）★ v2 新增

**目标**：在动任何功能代码前，先建立"能发现回归"的能力。当前前端 **0 测试**，直接重构等于盲改。

| 变更 | 文件 | 说明 |
| --- | --- | --- |
| 新增 | `vitest.config.ts` + `src/**/*.spec.ts` | 单元测试基线；优先覆盖 `api/sse.ts`（事件分发、断线重连、`after_seq` 续播）与 `stores/*` |
| 新增 | `e2e/workspace.spec.ts`（Playwright） | 3 条冒烟：打开首页 / 发一条消息收到流式回复 / 切会话恢复历史 |
| 新增 | `package.json` scripts | `test` / `test:e2e` / `typecheck` / `lint` |
| 新增 | 视觉快照基线 | 对 13 个现有页面截图存为基线，后续每阶段比对（可复用 `frontend/scripts/ui_probe/`） |
| 改 | CI（若有） | 合入前置：`typecheck` + `vitest` 必过 |

**验收**：`npm run test` 有 ≥15 个用例且全绿；`npm run test:e2e` 3 条冒烟通过；13 页视觉基线已入库。

> 若确认不做阶段 0，则后续每阶段的验收标准必须降级为"人工点检清单"，并在 §10.1 风险表中登记"无回归网"。

---

### 阶段 1 · 骨架重排：路由与布局（3~4 人日）

**目标**：把 13 平铺路由改为「1 主工作台 + `/admin/*` 后台」，建立可扩展的布局壳。

| 变更 | 文件 | 说明 |
| --- | --- | --- |
| 新增 | `src/layouts/WorkspaceLayout.vue` | 左栏 + 主区骨架；左栏含搜索、折叠、账号区占位 |
| 新增 | `src/layouts/AdminLayout.vue` | 后台布局（保持现有顶栏能力开关，用于运维场景） |
| 新增 | `src/layouts/SideNav.vue` | 可复用左栏导航（数据驱动，图标/分组/计数） |
| 改 | `src/router/index.ts` | 引入 `children` 嵌套路由；`/` → `/workspace`；`/chat` `/work` → 重定向到 `/workspace?mode=chat|plan|craft` |
| 改 | `src/App.vue` | 降级为纯 `<router-view>`，移除全局能力复选框与版本号顶栏 |
| 改 | `src/styles/tokens.css` | 新增 `--radius-input`、`--chip-bg`、`--sidebar-w`、`--message-w` 等 |

**验收**：`/` 打开即工作台；`/admin/skills` 等后台页仍可用；浏览器前进后退正常；`npm run typecheck` 通过。

---

### 阶段 2 · 输入区重做（5~7 人日）★ 最高价值

**目标**：实现 A3/A4/A5/A6 —— 这是目标形态的"门面"，用户感知最强。

| 变更 | 文件 | 说明 |
| --- | --- | --- |
| 新增 | `src/components/composer/ComposerInput.vue` | 圆角大卡输入框；`+`/`@` 左下，模型⌄/🎤/圆形发送右下；Enter 发送 / Shift+Enter 换行提示写进占位符 |
| 新增 | `src/components/composer/ContextChips.vue` | 能力 Chip 行（由会话能力配置驱动，空态时显示场景 Chip） |
| 新增 | `src/components/composer/ContextBar.vue` | 框外工具条：`选择工作空间⌄` + `默认权限⌄` |
| 新增 | `src/components/composer/CommandPalette.vue` | `/` 唤起命令面板（Skill / 模板 / 模式 / 深度研究） |
| 新增 | `src/components/composer/AtPicker.vue` | `@` 唤起上下文选择（引用文件 / 历史会话 / Skill） |
| 新增 | `src/components/composer/ModelSwitcher.vue` | 模型 + 模式合并下拉（对齐 `Auto Mode⌄`） |
| 改 | `src/stores/config.ts` | 能力开关从全局复选框 → **会话级 `session.config`**（随 session 持久化） |

**验收**：输入框视觉与 `assets/ref_trae_work_ui.png` 对齐；`/` 与 `@` 可唤起面板；模式切换不刷新页面；会话重开后能力配置保持。

---

### 阶段 3 · 工作台对话流（5~7 人日）

**目标**：把 `/chat` 与 `/work` 合并为一个页面内的模式切换（A1），并把执行轨迹、产物、Plan 审批升级。

| 变更 | 文件 | 说明 |
| --- | --- | --- |
| 改 | `src/views/ChatView.vue` / `WorkView.vue` → 合并为 `src/views/WorkspaceView.vue` | 模式 = `chat` / `work` / `work+plan_first` 三态；切换保留当前会话 |
| 改 | `src/components/ChatMessage.vue` | 气泡内联步骤 → 抽离为「执行轨迹」折叠区 |
| 新增 | `src/components/RunTimeline.vue` | 执行轨迹：轮次 / 工具调用 / 结果 / 引用；复用 `ProcessSteps` 的配色语义（内置青 / MCP 紫 / RAG 绿 / Web 橙） |
| 改 | `src/components/ProcessSteps.vue` | 支持折叠、来源着色、引用卡片内联 |
| 改 | `src/views/WorkView.vue` 内 PlanCard | 升级审批卡：序号徽标 + 标题/说明双行可编辑 + 底部右对齐「确认执行 / 拒绝」+ 执行中逐步回填 |
| 新增 | `src/components/ArtifactStrip.vue` | 产物条：气泡下方横向文件卡片（可点击预览） |
| 改 | `src/stores/session.ts` | `mode` 单值 → 会话级 `config` 对象；新增 `spaces` 维度 |

**验收**：Ask/Plan/Craft 三态切换零跳页；Plan 审批后 SSE 续播不断流；执行轨迹可折叠且不丢数据；产物可点击。

---

### 阶段 4 · 左栏任务流与空间（5~6 人日）

| 变更 | 文件 | 说明 |
| --- | --- | --- |
| 新增 | `src/components/TaskList.vue` | 左栏任务分组（计数 + 折叠 + 搜索 + 筛选），支持并行任务状态标签 |
| 新增 | `src/components/SpaceGroup.vue` | 空间分组；会话可归属空间 |
| 新增 | `src/components/SidebarSearch.vue` | 顶栏搜索（⌘K），跨任务/空间/技能/产物 |
| 改 | `src/layouts/SideNav.vue` | 数据驱动菜单：新建任务 / 助理 / 项目 / 专家·技能·连接器 / 自动化 / 产物；分组折叠 |
| 改 | 后端 | `spaces` 表 + `sessions.space_id`（见 §7） |

**验收**：新建任务一键重置主区；任务可并行存在且状态可见；⌘K 搜索可用；空间可归类会话。

---

### 阶段 5 · 能力后台合并与「产物」页（3~4 人日）

| 变更 | 说明 |
| --- | --- |
| 改 | `/admin/skills` + `/admin/mcp` + `/admin/teams` → 合并为 `/admin/capabilities`，内部 Tab：**团队 / 技能 / 连接器(MCP)**（对齐 WorkBuddy「专家·技能·连接器」） |
| 改 | `/admin/schedules` 保留，改造成「自动化」配置页（补「每次运行上限 / 失败退避 / 权限」可视化） |
| 改 | `/admin/files` → 「我的产物」：按会话 / 类型 / 时间聚合，支持预览与下载 |
| 改 | `/admin/research` → 深度研究任务历史，工作台内可发起并内联进度 |
| 改 | `/admin/status` 承接原顶栏版本信息 |

**验收**：左栏 6 个入口与目标形态一一对应；产物页可按会话过滤；研究任务可从工作台发起。

---

### 阶段 6 · 打磨与验收（4~5 人日）

| 项 | 内容 |
| --- | --- |
| 视觉 | 圆角/阴影/字号阶梯对齐目标形态；Chip 动效；暗色模式逐页复核 |
| 可访问性 | 键盘可达（⌘K、⌘⌃N 新建任务、Enter/Shift+Enter）、焦点环、对比度 ≥ 4.5:1 |
| 响应式 | ≥1280 三栏；1024~1280 左栏可折叠；<1024 侧栏抽屉化 |
| E2E | 复用 `backend/scripts/ui_browser_test.py`，扩展 10 场景（新建任务/三模式/命令面板/@引用/审批/产物/空间/搜索/自动化/产物聚合） |
| 回归 | `cd backend && .venv/bin/python -m pytest tests/ -q` 全绿 |

---

### 6.7 排期与依赖（v2 重估）

```
阶段0 基建 ──► 阶段1 骨架 ──► 阶段2 输入区 ──► 阶段3 工作台 ──┐
                                                              ├──► 阶段6 打磨
              后端 artifacts 聚合 ──┐                         │
              后端 spaces/attachments ┼──► 阶段4 任务流 ────────┘
              后端 并发护栏/取消 ────┘        阶段5 后台 ──► 可穿插进行
```

| 阶段 | 人日 | 依赖 | 可单独上线 | v1 → v2 变化 |
| --- | --- | --- | --- | --- |
| **0 工程基建** | **2~3** | — | —（前置） | **新增** |
| 1 骨架重排 | 3~4 | 0 | ✅ | 不变 |
| 2 输入区重做 | **5~7** | 1 | ✅（可对 `/chat` 灰度） | **上调**：组件从 0 建 + 命令面板/@选择器交互复杂 |
| 3 工作台对话流 | **5~7** | 1、2 | ✅ | **上调**：含后端取消语义配合 |
| 4 任务流与空间 | **5~6** | 3 + 后端 spaces/并发护栏 | ✅ | **上调**：含并发状态回显 |
| 5 能力后台合并 | 3~4 | 1 | ✅ | 不变（优先级下调，可后置） |
| 6 打磨验收 | **4~5** | 全部 | — | **上调**：含视觉回归 + 暗色复核 + 10 场景 E2E |
| **前端合计** | **27~36** | | | 原 21~28 |
| **后端合计** | **5~7** | | | 原 4~6 |

### 6.8 为什么工作量上调 30%

| 原因 | 说明 |
| --- | --- |
| **自研组件只有 3 个**（v1 误判为"改 46 个"） | 工作台需要约 **16 个新组件**，全部从零写：`ComposerInput`/`ContextChips`/`ContextBar`/`CommandPalette`/`AtPicker`/`ModelSwitcher`/`TaskList`/`SpaceGroup`/`SidebarSearch`/`RunTimeline`/`ArtifactStrip`/`PlanCard`/`AccountMenu` + 3 个布局壳 |
| **前端零测试** | 阶段 0 需先建测试与检查（v1 完全没算） |
| **命令面板 / `@` 选择器是"小而深"的交互** | 键盘导航、模糊匹配、异步候选、分组、空态、多选回显 —— 单项 1.5~2 人日 |
| **三处重复实现要归一** | `ChatView` / `WorkView` / `ResearchView` 各有一套输入框与能力开关，合并时需逐一比对行为差异，避免丢功能 |
| **并发与取消语义** | 需前后端协同（护栏、排队、状态回显、取消落库），v1 未计 |

---

## 7. 后端 API 新增 / 调整设计

### 7.1 工作空间 Space（P1）

```sql
CREATE TABLE spaces (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  root_path TEXT NOT NULL DEFAULT '',      -- Agent 可访问的根目录（留空=默认 outputs）
  owner TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
ALTER TABLE sessions ADD COLUMN space_id TEXT REFERENCES spaces(id) ON DELETE SET NULL;
```

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/api/v1/spaces` | 列表 / 创建 |
| GET/PUT/DELETE | `/api/v1/spaces/{id}` | 详情 / 更新 / 删除 |
| POST | `/api/v1/spaces/{id}/resolve` | 按路径解析归属空间（供自动归档） |

### 7.2 上下文引用 Attachments（P1）

```jsonc
// POST /api/v1/agent/run 新增字段
{
  "prompt": "总结这三份文档",
  "attachments": [
    { "type": "file",    "path": "data/uploads/a.pdf" },
    { "type": "session", "id": "sess_xxx" },
    { "type": "skill",   "name": "pdf-analyzer" }
  ]
}
```

后端行为：把 attachments 解析为 system prompt 的上下文段 + 可选注入文件内容。

### 7.3 产物索引（P1）—— v2 重写：**无需新建表**

> v1 原方案是"给 `files` 表加 `session_id`"，但**`files` 表根本不存在**（`/files` 是 `output_dir` 文件系统直读）。
> 实测产物已经持久化在 `runs.files_json`，因此改用**聚合查询**实现，零迁移成本。

| 方法 | 路径 | 实现方式 |
| --- | --- | --- |
| GET | `/api/v1/sessions/{id}/artifacts` | **聚合该会话全部 `runs.files_json`** + `research` 产物，按 `created_at` 倒序；无需新表 |
| GET | `/api/v1/artifacts` | 全局产物列表：`join(runs, sessions)` + `files_json` 展开，支持 `kind`（报告/图片/代码/数据）、`since`、分页 |
| GET | `/api/v1/files?session_id=` | 在现有文件系统列表基础上**增加可选过滤**（返回 `run_id` 反查得到的归属），保持向后兼容 |

**实现要点**
1. `files_json` 存的是文件名字符串数组 → 需与 `output_dir` 真实文件做存在性校验（文件可能被手工删除）。
2. 文件名即 ID 的现状意味着**同名文件会互相覆盖** → 若要做可靠的"产物版本"，才需要新建 `artifacts` 表（`id / run_id / session_id / filename / sha256 / size / kind / created_at`）。**建议 P1 先用聚合，P2 再引入表**。
3. 前端「我的产物」页应能同时展示"文件系统里存在的"与"账本里记录但已丢失的"两类，后者标灰提示。

### 7.4 账号与记忆（P2，非本期必需）

- `users` 表 + 简易 token 中间件 → 支撑左栏账号区。
- `memories` 表 + `/api/v1/memories`（`/remember` 命令读写）。
- 现有 `sessions.owner` 字段届时启用。

### 7.5 兼容性约定

- 所有新字段**可选**，旧前端调用不受影响（渐进式）。
- `mode` 参数语义**不变**（`chat`/`work`），`plan_first` 语义不变 —— 只改 UI 组织方式，不改后端契约。

---

## 8. 交互规范（可直接落地实现）

### 8.1 模式定义（对齐 WorkBuddy Ask/Plan/Craft）

| UI 名称 | 后端参数 | 工具档案 | 人工确认 |
| --- | --- | --- | --- |
| 对话（Ask） | `mode=chat` | 只读（read_file/list/rag/web） | 否 |
| 计划（Plan） | `mode=work, plan_first=true` | 全量 | **是**（审批卡） |
| 工作（Craft） | `mode=work, plan_first=false` | 全量 | 否 |

### 8.2 快捷键

| 键位 | 动作 |
| --- | --- |
| `⌘K` | 全局搜索（任务 / 空间 / 技能 / 产物） |
| `⌘⌃N` | 新建任务（对齐 Trae Work） |
| `⌘/` | 唤起命令面板 |
| `@` | 唤起上下文选择 |
| `Enter` / `Shift+Enter` | 发送 / 换行 |
| `Esc` | 关闭面板 / 中断生成 |

### 8.3 输入区状态机

```
idle ──输入文本──► composing ──Enter──► streaming ──done──► idle
  │                   │                    │
  │                   └─@/ 或 / 唤起面板     └─Esc──► aborted（保留部分产出）
  └─空 + 点发送 ──► disabled
```

### 8.4 Plan 审批卡交互

1. SSE 收到 `approval_required` → 渲染卡片，输入框禁用，焦点移到卡片「确认执行」。
2. 「确认执行」→ `POST /agent/runs/{id}/approve`（可带 `edited_plan`）→ `GET /runs/{id}/stream?after_seq=0` 续播。
3. 「拒绝」→ `POST /agent/runs/{id}/reject` → 卡片转为「已拒绝」只读态。
4. 卡片必须在**重启后仍可审批**（后端 `runs.plan_json` 已持久化，前端只需在加载历史时检测 `awaiting_approval` 状态的 run）。

### 8.5 空态规范

| 场景 | 标题 | 副元素 |
| --- | --- | --- |
| 无会话 | `Agent Platform, 我帮你` | 3 个场景 Chip + 能力 Chip 行 |
| 有会话无消息 | 同上（隐藏场景 Chip） | 能力 Chip 行 |
| 搜索无结果 | `未找到匹配结果` | 建议放宽筛选条件 |

### 8.6 并发与多任务规范（v2 新增）

> 依据 §3.4：后端流式接口**无并发护栏**，同步接口上限 2 且**超额直接跳过**。因此"并行"必须由前端与后端共同约定。

| 规则 | 定义 |
| --- | --- |
| **前端并行上限** | 同时最多 **3** 个会话处于 `streaming`；达到上限后新任务进入**排队**（`queued`），串行启动 |
| **后端护栏（新增）** | `RunExecutor.execute_stream` 引入与 `execute_sync` 同源的信号量，上限 `agent_max_concurrent`（建议 4，可配）；超额返回 `429` + `{code:"busy", retry_after}` 而非静默失败 |
| **排队语义** | `queued` 任务在 UI 显示倒计时/位次；任一在跑任务结束即启动队首 |
| **状态回显** | 左栏任务项显示 5 态徽标：`idle` / `queued` / `running` / `awaiting_approval` / `failed`；`running` 显示已耗时 |
| **跨页保活** | 切换会话**不中断**正在跑的流：SSE 连接归属到 store（按 `run_id` 持有），而非组件生命周期 |
| **状态来源** | 以 `GET /runs?status=running` 为准做**对账**（页面刷新后恢复"哪些任务在跑"），不能只信内存 |
| **取消语义（新增）** | `POST /agent/runs/{id}/cancel` → `runs.status=cancelled`；前端"停止"先调它再 `abort()`，保证账本一致 |

### 8.7 输入区与对话区全状态矩阵（v2 新增）

| # | 状态 | 触发条件 | 输入区表现 | 主区表现 |
| --- | --- | --- | --- | --- |
| 1 | `empty` | 无会话 | 场景 Chip + 能力 Chip + 占位符 | 居中大标题 |
| 2 | `idle` | 有会话、无输入 | 发送键禁用（灰） | 历史消息 |
| 3 | `composing` | 有输入文本 | 发送键激活（实心） | — |
| 4 | `submitting` | 已发请求、等首包 | 发送键 → 转圈，输入框只读 | 用户气泡已入列 + "思考中"骨架 |
| 5 | `streaming` | 收到首个事件 | 发送键 → 停止键 | 流式追加 + 执行轨迹实时增长 |
| 6 | `tool_running` | 正在调工具 | 同上 + 顶部细进度条 | 轨迹内工具节点高亮 |
| 7 | `awaiting_approval` | 收到 `approval_required` | **输入框禁用** + 提示"等待确认计划" | Plan 卡片置顶 + 焦点移到「确认执行」 |
| 8 | `aborted` | 用户点停止 | 恢复 `idle` | 保留部分产出 + "已停止"标记 |
| 9 | `error_network` | SSE 断开且重连失败 | 顶部条："连接中断，重试" | 已收内容保留，未收部分显示断点 |
| 10 | `error_backend` | 收到 `type:error` | 同上 + 展示 `error.message` | 气泡显示错误卡片（可复制详情） |
| 11 | `error_busy` | 返回 429 / `busy` | 输入框保留文本不清空 + toast | 提示"并发已满，已排队/稍后重试" |
| 12 | `offline` | `navigator.onLine === false` | 发送键禁用 + toast | 提示离线 |

> **原则**：任何异常态都**不得清空用户已输入文本**；任何中断都**不得丢弃已接收的流式内容**。

---

## 9. 组件拆分与取舍

### 9.1 方案 C（推荐）：双壳并行，渐进迁移

| 壳 | 路由 | 内容 | 面向 |
| --- | --- | --- | --- |
| 工作台壳 | `/workspace` | 新形态 | **终端用户**（默认首页） |
| 后台壳 | `/admin/*` | 现有 13 页改造后归位 | **运维 / 高级用户** |

**理由（v2 重写）**：

> v1 的两条论据（"13 页有测试覆盖"、"46 个组件依赖重写成本高"）**经复核均不成立**：前端 0 测试、自研组件仅 3 个。
> 结论不变，但论据必须换成真正成立的三条：

1. **两种交互模型不可混装**：13 个后台页是**表单/表格型 CRUD**（同步、离散、页内状态自洽），
   工作台是**对话/流式型**（长连接、跨页保活、事件驱动）。硬塞进同一个壳，会让顶栏、状态栏、
   路由守卫同时承担两套语义（例如"能力开关"在 CRUD 页是查询参数，在工作台是会话级上下文）。
2. **渐进可控**：13 页已有后端 12 个测试文件兜底的 API 契约，页面本身**行为稳定但没人测**；
   把它们**平移**进 `/admin/*`（只改路由与布局壳，不动业务逻辑）是低风险操作，而重写才是高风险。
3. **角色分离符合目标形态**：WorkBuddy / Trae 的"能力管理"本身就是二级入口（专家·技能·连接器 /
   插件市场 / 模板库），不占主区。`/admin/*` 正好承接，语义与位置都对得上。

**代价**：短期内两套导航并存，需在左栏明确分组（工作台区 / 管理区），并用角色或开关控制可见性。

### 9.2 新增 / 复用 / 废弃清单

| 类别 | 内容 |
| --- | --- |
| **新增（**16 个**）** | 布局壳 3：`WorkspaceLayout`、`AdminLayout`、`SideNav`　输入区 5：`ComposerInput`、`ContextChips`、`ContextBar`、`CommandPalette`、`AtPicker`　对话区 4：`RunTimeline`、`ArtifactStrip`、`PlanCard`（抽取）、`ModelSwitcher`　左栏 3：`TaskList`、`SpaceGroup`、`SidebarSearch`　其他 1：`AccountMenu` |
| **复用（不改）** | `api/client.ts`、`api/sse.ts`、`api/endpoints.ts`、`api/types.ts`、`stores/config.ts`、`MarkdownView`、`ProcessSteps`（增强）、`ChatMessage`（瘦身） |
| **废弃 / 合并** | `App.vue` 的全局能力复选框区；`/chat` 与 `/work` 两个独立路由（并入 `/workspace`）；`WRChatView`（WR 范式实验页，收进 `/admin` 或删除）；重复的深度研究输入区 |
| **暂不动** | `styles/tokens.css` 的暗色模式、`stores/session.ts` 的 localStorage 持久化键名（保持向后兼容） |

### 9.3 13 个页面逐页处置表（v2 新增，D3）

| 现有页面 | 路由 | 处置 | 去向 | 说明 |
| --- | --- | --- | --- | --- |
| `ChatView` | `/chat` | **重构** | `/workspace?mode=chat` | 逻辑并入 `WorkspaceView`；抽屉式会话列表 → 常驻左栏 |
| `WorkView` | `/work` | **重构** | `/workspace?mode=craft` | 保留二级左栏能力，升级为全局任务流；Plan 卡抽为组件 |
| `ResearchView` | `/research` | **拆分** | 发起 → 工作台 Chip；历史 → `/admin/research` | 消除与对话页重复的输入区 |
| `TeamsView` | `/teams` | **平移合并** | `/admin/capabilities?tab=teams` | 只改壳，业务逻辑不动 |
| `SkillsView` | `/skills` | **平移合并** | `/admin/capabilities?tab=skills` | 同上 |
| `MCPView` | `/mcp` | **平移合并** | `/admin/capabilities?tab=mcp` | 同上 |
| `SchedulesView` | `/schedules` | **平移增强** | `/admin/schedules` | 补并发上限/退避/权限可视化（对齐 §8.6） |
| `FilesView` | `/files` | **增强** | `/admin/artifacts` | 接入 §7.3 聚合接口，支持按会话过滤 |
| `RAGView` | `/rag` | **平移** | `/admin/knowledge` | 能力页，低优先级 |
| `WebResearchView` | `/web` | **平移** | `/admin/web` | 依赖 `BOCHA/SERPER` 密钥，当前不可用，保留入口但标注"未配置" |
| `SystemStatusView` | `/status` | **平移增强** | `/admin/status` | 承接原顶栏版本串；补"并发占用/在跑任务"面板 |
| `SettingsView` | `/settings` | **平移** | `/admin/settings` | — |
| `WRChatView` | `/wr` | **降级** | `/admin/lab/wr` | 实验性 WR 范式（plan→action→reflection→answer），非主线；不删以留回溯 |

**汇总**：重构 3、合并 3、平移/增强 6、降级 1 → 13 页全部有归属，**无遗漏、无"待定"**。

---

## 10. 风险、取舍与非目标

### 10.1 风险

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 路由重构波及 13 页 | 回归面大 | 13 页按 §9.3 逐页处置；旧路径**保留可访问**（不硬跳转），仅 `/` 在开关开启时重定向到 `/workspace`；阶段 0 的视觉基线用于比对（见 §10.4） |
| 工作台信息密度过高 | 用户找不到能力入口 | 左栏分组 + 搜索 + 空态引导；能力 Chip 收进「更多」 |
| `@` / `/` 命令面板实现复杂 | 拖期 | P1 先做**纯前端**命令面板（Skill/模板/模式），`@` 文件引用放 P1.5 |
| 后端 `spaces` 拖期 | 阶段 4 阻塞 | 阶段 4 前置为空实现（本地 localStorage），后端就绪后切换 |
| SSE 续播在审批后丢事件 | 执行过程不完整 | 复用现有 `after_seq` 游标；补单测覆盖 approve → stream |
| 暗色模式与新视觉体系冲突 | 视觉不统一 | 阶段 6 专项复核暗色 token |

### 10.2 取舍

| 取舍 | 选择 | 理由 |
| --- | --- | --- |
| 是否保留 Element Plus | **保留** | 13 个页面已深度使用 `el-table`/`el-form`/`el-drawer` 等；虽然自研组件只有 3 个，但**页面级用法已固化**，换组件库等于重写 13 页。且目标形态所需（圆角卡、Chip、Popover、命令面板）Element Plus 均可实现，只需覆写 token |
| 是否引入 Tailwind / UnoCSS | **不引入** | 项目已有 token 体系；引入新原子化框架需重写全部样式，收益不足 |
| 是否做多栏右侧面板 | **P2** | Trae SOLO 右栏（文档/Diff/产物）价值高，但本项目产物形态以文件为主，先用「产物条 + 独立产物页」过渡 |
| 是否做语音输入 | **不做** | 无后端 ASR 能力，属装饰性功能 |
| 是否实现记忆系统 | **P2** | `/remember` 价值明确但依赖账号体系，且当前为单用户 |

### 10.3 非目标

- 不改后端 Agent / Tool / RAG 链路的业务语义；
- 不改 SSE 协议（`frontend/docs/sse-protocol.md` 保持有效）；
- 不做移动端适配（仅保证 ≥1024 可用）；
- 不做多语言。

### 10.4 灰度、回滚与数据兼容（v2 新增，D4）

| 项 | 设计 |
| --- | --- |
| **特性开关** | `localStorage.__ws_v3 = "on" \| "off" \| "canary"`；`canary` = 按 URL 参数 `?v3=1` 命中。开关关闭时 `/` 仍走 `/chat` 旧页面 |
| **旧路径兼容** | `/chat`、`/work`、`/research` 等**保留路由且可访问**，不做硬跳转；仅当 `v3=on` 时 `/` 才重定向到 `/workspace`。避免书签失效 |
| **前端持久化兼容** | `stores/session.ts` 现用 localStorage 键名**保持不变**；新增 `space_id`、`config` 时给默认值，旧数据读入不报错 |
| **后端接口兼容** | 新字段全部可选；`space_id` 为空即"未归类"，左栏空间分组显示"未归类"桶，**不阻塞**任何现有调用 |
| **迁移策略** | `sessions.space_id` 用 Alembic 加列 + 默认 `NULL`；**不做数据回填**（历史会话一律归入"未归类"） |
| **回滚方式** | 关开关即回旧界面（后端接口向后兼容，无需回滚数据库）；**禁止**在阶段 4 前删除任何旧路由 |
| **回滚判据** | 上线 48h 内若出现"消息发送失败率 > 2%"或"会话切换丢历史"，立即关开关 |

### 10.5 可观测性与成功指标（v2 新增）

| 层 | 指标 | 采集方式 | 目标 |
| --- | --- | --- | --- |
| 行为 | 首屏到"发出第一条消息"的耗时 | 前端埋点 | P50 < 8s |
| 行为 | 空态 → 发出消息的转化率 | 埋点（空态曝光 / 发送点击） | 提升基线 20% |
| 行为 | `@` / `/` 面板唤起率与选择成功率 | 埋点 | 成功率 > 70% |
| 技术 | SSE 首包延迟、断流率、重连成功率 | 现有 `run_events` + 前端埋点 | 断流率 < 1% |
| 技术 | 前端 JS 包体积 | `vite build` 产物 | 首屏 gzip < 350KB |
| 技术 | 交互性能 | Lighthouse / `PerformanceObserver` | INP < 200ms |
| 运维 | 并发占用峰值、`busy` 拒绝次数 | §8.6 护栏指标 + `/admin/status` | `busy` 率 < 0.5% |

> 若无埋点基础设施，阶段 0 应至少接入一个轻量方案（本地 `console` + 后端 `/api/v1/events` 上报），
> 否则"改造是否成功"只能靠主观判断。

---

## 11. 附录 A：资料来源

### Trae

| 内容 | 链接 | 用途 |
| --- | --- | --- |
| Trae Work 网页版真实界面 | `https://work.trae.cn/` | **主参考图**（`assets/ref_trae_work_ui.png`） |
| Trae 官网 · Work 产品页 | `https://www.trae.cn/work` | 多项目并行、Agent 体系、Rules、上下文来源 |
| Trae 官网首页 | `https://www.trae.cn/` | IDE/SOLO 双模式定位 |
| 《Trae 实战：4 项功能把活整个交给 AI》（掘金） | `https://juejin.cn/post/7686352376153112618` | **SOLO 三栏布局**、Builder 全流程、Coder/Builder 分工、右侧工具面板 |
| 《@Trae 精炼指南》（ima 知识库） | ima.qq.com 分享链接 | SOLO 三栏（任务窗口/对话流/工具面板）、@SOLO Coder 定位 |
| 《Trae SOLO 对话式编程》（CSDN） | `https://blog.csdn.net/Tony_Shen/article/details/161569776` | IDE 模式 vs SOLO 模式界面与工作流差异 |
| 《Trae Solo 现在就想干一件事：把 AI Coding 做成白盒》（网易） | `https://www.163.com/dy/article/KE9B26MK05566UKH.html` | 三栏布局的"白盒化"设计意图 |
| 《官方 FAQ｜SOLO 模式》（Trae 社区） | `https://forum.trae.cn/t/topic/53` | Plan 模式快捷键 `Option+P`；SOLO 布局暂不支持自定义 |
| 《作为"进阶玩家"》（Trae 社区） | `https://forum.trae.cn/t/topic/12954` | Chat（军师）vs Builder/SOLO（执行者）角色分工 |
| 《Trae 深度使用指南》（公众号 一豪YH） | 微信公众号 2247484152 | IDE 模式下 Agent/Chat 差异；`@` 创建智能体；`Ctrl+Enter` 接受变更、`Ctrl+Backspace` 撤销、`Ctrl+U` 添加终端报错；Rules 与记忆 |

### WorkBuddy

| 内容 | 链接 | 用途 |
| --- | --- | --- |
| WorkBuddy 官网（含客户端真实界面 Hero 素材） | `https://www.workbuddy.cn/` | **主参考图**（`assets/ref_workbuddy_home_ui.png`，2976×1860） |
| 《零基础玩转 WorkBuddy》（腾讯云开发者） | `https://cloud.tencent.com.cn/developer/article/2756802` | 技能中心 / 记忆系统 / 自动化 / 专家与连接器；`/remember`；三种模式 |
| 《用 WorkBuddy 两周，我重新理解了"效率工具"》（腾讯云） | `https://cloud.tencent.com/developer/article/2732277` | **左栏模块划分**：新建任务 / 助理 / 项目 / 专家·技能·连接器 / 自动化 / 资料库；「工具」与「工作台」分离的设计理念 |
| 《使用一段时间 workbuddy 后的心得分享》（腾讯云） | `https://cloud.tencent.com.cn/developer/article/2698130` | **任务 = 对话、空间 = 文件夹** 的产品语义；助手/灵感/自动化/专家/技能/连接器 菜单释义 |
| 《WorkBuddy 保姆级教程：技能、专家、连接器、自动化》（公众号） | 微信公众号 2247483688 | 「技能=工具，专家=身份，连接器=数据，自动化=闹钟」的功能定位 |
| 《零基础也能学会！WorkBuddy 从零到一完整上手指南》（头条） | `https://www.toutiao.com/a7668111901481533996` | **三栏布局拆解**；普通 / Plan / Craft 三模式定义与风险提示 |
| 《WorkBuddy 最新超全使用指南》（公众号 韩累累） | 微信公众号 2247483751 | 官方定义："全场景 AI 办公工作台…自然语言下达任务 → 自主理解 → 拆解 → 调用工具 → 交付文档/表格/演示文稿/网页/报告" |
| 《WorkBuddy 下载量第一，保姆级教程》（6oon） | `https://6oon.com/article/324.html` | 新建任务 / 工作空间 / 对话框改稿 / 专家 四步上手动线；文件拖拽与 Ctrl+V 截图粘贴 |
| 《20 分钟快速上手 WorkBuddy》（B站转载） | 微信公众号 2652309162 | 桌面智能体工作台定位；自动记忆 |
| 《WorkBuddy 住进企业微信，AI 同事几分靠谱？》（钛媒体/新浪） | `https://k.sina.com.cn/article_5953190046_162d6789e06703uuws.html` | 长时间任务的"思考列车"进度反馈模式 |

> ⚠️ 引用说明：WorkBuddy 与 Trae 均为闭源产品，上述界面与交互描述来自**官方页面 + 官方社区 + 第三方实测文章**的交叉验证；本文中的"改造目标"是**基于公开可见形态的再设计**，不涉及任何私有实现细节。

---

## 12. 附录 B：截图索引

| 文件 | 内容 | 来源 |
| --- | --- | --- |
| `assets/ref_workbuddy_home_ui.png` | WorkBuddy 客户端真实界面（1400px 缩放，原 2976×1860） | workbuddy.cn 官网 Hero 素材 |
| `assets/ref_workbuddy_site.png` | WorkBuddy 官网首页全页 | 本次抓取 |
| `assets/ref_trae_work_ui.png` | Trae Work 网页版真实界面（1600×1000，未登录态） | work.trae.cn |
| `assets/ref_trae_work_site.png` | Trae 官网 Work 产品页 | 本次抓取 |
| `assets/cur_chat.png` | 本项目 `/chat` 现状 | 本次抓取 |
| `assets/cur_work.png` | 本项目 `/work` 现状 | 本次抓取 |
| `assets/cur_teams.png` | 本项目 `/teams` 现状 | 本次抓取 |
| `assets/cur_schedules.png` | 本项目 `/schedules` 现状 | 本次抓取 |
| `assets/cur_skills.png` | 本项目 `/skills` 现状 | 本次抓取 |
| `assets/cur_research.png` | 本项目 `/research` 现状 | 本次抓取 |
| `assets/cur_status.png` | 本项目 `/status` 现状 | 本次抓取 |

> 项目内既有的 `doc/workbuddy/screenshots/*.png`（12 张）是**本项目 v2 已实现的界面快照**，代表"当前形态"，可与本文参考图对照阅读。

---

## 13. 附录 C：执行清单（勾选式）

> **v3.0 状态**：阶段 0~3 已完成（✅），阶段 4~6 部分完成（◐）。详见 §16 实施记录。

### 阶段 0 · 工程基建（v2 新增，**最先做**）✅
- [x] `vitest` 接入 + `api/sse.ts` 单测（11 例：事件分发 / `\r\n` / 坏 JSON 容错 / 多字节截断 / 非 2xx / Abort）
- [x] Playwright 冒烟（`smoke.py` 28 项 + `smoke_plan.py` 9 项）
- [ ] 13 页视觉基线截图入库（已归档 v3 截图 6 张，基线比对未做）
- [x] `typecheck` / `test` / `test:watch` 三个 npm script 可用（`lint` 未接入）

### 阶段 1 · 骨架 ✅
- [x] 新建 `src/layouts/WorkspaceLayout.vue` / `AdminLayout.vue` / `components/layout/SideNav.vue`
- [x] 路由改为嵌套结构，`/` → `/workspace`（受 `__ws_v3` 开关控制）
- [x] 旧路径（`/chat` `/work` `/research` `/skills` …）**保留可访问**，重定向到 `/admin/*`
- [x] `App.vue` 移除全局能力复选框与版本号
- [ ] `tokens.css` 增补 `--radius-input` / `--chip-bg` / `--sidebar-w` / `--message-w`（改用组件内样式）

### 阶段 2 · 输入区 ✅
- [x] `ComposerInput.vue`（圆角大卡 / Enter 发送 / 占位符含 @ 与 / / `/` 与 `@` 触发）
- [x] `ContextChips.vue`（3 场景 Chip + 5 能力 Chip）
- [x] `ContextBar.vue`（工作空间 / 默认权限）
- [x] `CommandPalette.vue`（`/` 命令面板，↑↓ 导航 / Enter 执行）
- [x] `AtPicker.vue`（`@` 上下文选择：对话 / 技能 / 产物）
- [x] `ModelSwitcher.vue`（Ask·Plan·Craft + 模型合并下沉输入框右下）
- [x] 能力配置改为会话级（`WorkspaceView.caps`）

### 阶段 3 · 工作台 ✅
- [x] `WorkspaceView.vue` 合并 Chat/Work，三态同页切换（URL 同步 `?mode=`）
- [x] `RunTimeline.vue` 执行轨迹（可折叠，来源着色沿用 `ProcessSteps`）
- [x] `PlanCard.vue`（序号徽标 / 双行可编辑 / 右对齐操作）
- [x] `ArtifactStrip.vue` 产物条
- [x] 审批后 `after_seq=0` 续播（`smoke_plan.py` 9/9 验证通过）

### 阶段 4 · 任务流
- [ ] `TaskList.vue`（分组 / 计数 / 折叠 / 搜索 / 筛选 / 并行状态）
- [ ] `SpaceGroup.vue` + 后端 `spaces` 接口
- [ ] `SidebarSearch.vue`（⌘K）
- [ ] `AccountMenu.vue`（左栏底部账号区占位）

### 阶段 5 · 后台合并
- [ ] `/admin/capabilities`（团队 / 技能 / MCP 三 Tab）
- [ ] `/admin/schedules` 自动化配置增强（含并发上限/退避/权限可视化）
- [ ] `/admin/artifacts` 我的产物（聚合 / 预览 / 丢失文件标灰）
- [ ] `/admin/research` 深度研究历史
- [ ] `WRChatView` 降级到 `/admin/lab/wr`
- [ ] 13 页按 §9.3 处置表逐页核对，**无遗漏**

### 阶段 6 · 打磨
- [ ] 视觉对齐 + 暗色复核（13 页逐页）
- [ ] 快捷键：⌘K / ⌘⌃N / ⌘/ / Esc
- [ ] 响应式 1280 / 1024 断点（<1024 左栏抽屉化）
- [ ] E2E 扩到 10 场景
- [ ] `pytest` 全绿 + `npm run test` 全绿
- [ ] 包体积 < 350KB gzip；INP < 200ms
- [ ] 灰度开关演练（`on` → `off` → `canary` 三态各跑一次）

### 横切项（v2 新增）
- [ ] §8.6 并发护栏：后端信号量 + 429 + 前端 3 并行上限 + 排队
- [ ] §8.7 12 种状态逐一实现并点检
- [ ] §10.4 灰度开关 + 旧路由保留
- [ ] §10.5 埋点（至少落在"空态→发送"与"SSE 断流"两处）

---

## 14. 附录 D：下一步建议

> **v3.0 更新**：阶段 0~3 已落地并验证通过（见 §16）。以下按"剩余工作"重排优先级。

### P0 · 必须做（否则目标形态不完整 / 有技术债）

1. **并发护栏**（§8.6 / §3.4）—— 后端 `execute_stream` 无任何限流，前端可并发打爆 LLM 配额。
   建议 **0.5 人日先压测**（并发发 4 条 `/agent/run` 流，观察配额/内存/响应退化），再定 §8.6 的上限取值。
   这是全计划中**唯一"可能推翻目标形态"的技术假设**。
2. **`run` 取消语义** —— 前端停止只断 SSE，后端 run 状态仍为 `running`，账本失真。
3. **产物聚合接口**（§7.3，2 个接口）—— 让「我的产物」从文件目录变成按会话可追溯。
4. **包体积 463KB → <350KB** —— Element Plus 全量引入所致，需 `manualChunks` + 按需引入。

### P1 · 补齐形态

5. **后端 `spaces` 接口**（3 个）—— 当前空间分组仅存 localStorage，跨设备失效。
6. **`/admin/artifacts` 真实页**（不是旧 `/files` 复用）。
7. **响应式 <1024 抽屉化** + **暗色模式 13 页复核**。
8. **`@` 引用真正落地**（`attachments` 字段）—— 当前 `@` 只做文本插入，未把上下文喂给后端。
9. **空间归属 UI**（把任务拖进空间）与 **`/admin/capabilities` 内的 MCP/RAG 深度合并**。

### P2 · 增强

10. 并行任务窗口（Trae SOLO 左栏多任务并行）—— 依赖 P0-1 完成。
11. 右侧工具面板（文档 / DiffView / 浏览器预览）。
12. 记忆系统 `/remember`、账号体系。

### 工程约定（已生效，建议固化）

- 改动后必须过 8 道门禁（`npm run`）：

  ```bash
  npm run typecheck        # 0 error
  npm run test             # 17/17 单测
  npm run test:contract    # 前后端契约 58/58
  npm run test:api         # 后端 69/69 operation
  npm run test:e2e:smoke   # 28/28
  npm run test:e2e:plan    # 9/9
  npm run test:e2e         # 84/84 全功能
  npm run build            # 构建
  ```

- **契约比对是强制项**：`test:contract` 会解析 `src/api/index.ts` 的每个调用点，与后端 OpenAPI 比对 method+path，防止再出现 C1 类缺陷。
- 截图归档到 `doc/workbuddy/screenshots/v3_*.png`，形成 v2/v3 对照档案。
- 灰度开关 `localStorage.__ws_v3` 保留在生产，异常时关开关即回退旧界面。
- 后端变更后需 `kill <pid>` 重启；前端变更后需 `node frontend/scripts/build-frontend.mjs` 才影响单端口形态。

---

## 15. 附录 E：断言复核清单（v2 新增）

> 本文所有量化结论对应的验证命令。**任何人可在 1 分钟内复跑，推翻任一条即可修订本文。**

| 断言 | 验证命令 | 期望输出 |
| --- | --- | --- |
| 路由 14 条 | `grep -cE "^\s*\{\s*path" frontend/web/vue-element-plus/src/router/index.ts` | `14` |
| 页面 13 个 | `ls frontend/web/vue-element-plus/src/views/*.vue \| wc -l` | `13` |
| 自研组件 3 个 | `ls frontend/web/vue-element-plus/src/components/*.vue \| wc -l` | `3` |
| npm 依赖 8 个 | `python3 -c "import json;print(len(json.load(open('frontend/web/vue-element-plus/package.json'))['dependencies']))"` | `8` |
| 前端源码 4813 行 | `find frontend/web/vue-element-plus/src -name '*.vue' -o -name '*.ts' -o -name '*.css' \| xargs wc -l \| tail -1` | `4813` |
| 前端测试 0 个 | `find frontend/web/vue-element-plus -name '*.spec.*' -o -name '*.test.*' \| wc -l` | `0` |
| 后端 54 path / 69 op | `curl -s localhost:18040/openapi.json \| python3 -c "import json,sys;d=json.load(sys.stdin);print(len(d['paths']), sum(len(v) for v in d['paths'].values()))"` | `54 69` |
| 无 `files` 表 | `sqlite3 backend/data/app.db "select name from sqlite_master where type='table'"` | 9 表，**无 files** |
| 产物记 `files_json` | 同上 + `PRAGMA table_info(runs)` | 含 `files_json` |
| 同步并发上限 2 | `grep -n "_semaphore\|schedule_max_concurrent" backend/app/services/run_executor.py` | `BoundedSemaphore(settings.schedule_max_concurrent)` |
| 流式无护栏 | `sed -n '/def execute_stream/,/^    async def /p' backend/app/services/run_executor.py \| grep -c semaphore` | `0` |
| 会话历史可恢复 | `grep -n "detail.messages" frontend/web/vue-element-plus/src/views/*.vue` | 命中 `ChatView` / `WorkView` |
| 计分 1.0/7 | 人工按 §2.4 逐项加总 | `1.0` |

---

## 16. 实施记录（v3.0 首轮落地，2026-10-25）

> 计划前 4 个阶段已实现并通过自动化验证。**本节是事实记录**，与 §6 计划并存。

### 16.1 已交付内容

| 阶段 | 状态 | 交付物 |
| --- | --- | --- |
| **0 工程基建** | ✅ 完成 | `vitest.config.ts`；`src/api/sse.spec.ts`（6 例）；`src/stores/session.spec.ts`（5 例）；npm `test` / `test:watch` 脚本；`frontend/scripts/ui_probe/smoke.py`（28 项）、`smoke_plan.py`（9 项） |
| **1 骨架重排** | ✅ 完成 | `layouts/WorkspaceLayout.vue`、`layouts/AdminLayout.vue`、`components/layout/SideNav.vue`（数据驱动，workspace/admin 双形态）；`router/index.ts` 改为嵌套路由 + 13 个旧路径重定向；`App.vue` 降为纯 `<router-view>`；`stores/flags.ts` 灰度开关 |
| **2 输入区重做** | ✅ 完成 | `composer/ComposerInput.vue`（圆角大卡 / Enter 发送 / 占位符含 @ 与 /）、`composer/ModelSwitcher.vue`（Ask·Plan·Craft + 模型合并下沉）、`composer/ContextChips.vue`（场景 3 + 能力 5 Chip）、`composer/ContextBar.vue`（工作空间 / 默认权限）、`composer/CommandPalette.vue`（`/` 命令面板）、`composer/AtPicker.vue`（`@` 上下文选择） |
| **3 工作台对话流** | ✅ 完成（核心） | `views/WorkspaceView.vue`（Chat+Work 合并、三态同页切换、Plan 审批、执行轨迹、产物条、错误条）、`components/RunTimeline.vue`、`components/PlanCard.vue`、`components/ArtifactStrip.vue`、`stores/workspace.ts`（统一任务流 + 空间分组） |
| **4 任务流与空间** | ⚠️ 部分 | 任务列表 ✅、⌘K 搜索 ✅、空间分组 ✅（**本地 localStorage 实现**，后端 `spaces` 接口未建） |
| **5 能力后台合并** | ⚠️ 部分 | 「专家·技能·连接器」三 Tab 合并 ✅；「我的产物」仍为旧 `/files` 页（**§7.3 聚合接口未实现**） |
| **6 打磨验收** | ⚠️ 部分 | 快捷键 ✅（⌘K）、响应式 ⚠️（<1024 未做抽屉化）、E2E 37 项 ✅、暗色复核 ⚠️ |

**新增/改动文件 22 个**（新 17、改 5），前端源码从 4813 行 → **约 6100 行**。

### 16.2 自动化验证结果

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| 类型检查 | `npm run typecheck` | ✅ 0 error |
| 单元测试 | `npm run test` | ✅ **11/11** 通过（2 个文件） |
| 生产构建 | `npx vite build` | ✅ 成功（4.25s） |
| E2E 冒烟 | `backend/.venv/bin/python frontend/scripts/ui_probe/smoke.py` | ✅ **28/28** 通过 |
| Plan 审批链路 | `... smoke_plan.py` | ✅ **9/9** 通过 |

**冒烟覆盖**：根路径重定向 / 侧栏结构 / 空态 hero / 场景与能力 Chip / 输入框与占位符 / 模式切换（Ask→Plan→Ask，URL 同步）/ `/` 命令面板 / `@` 上下文选择 / **真实 SSE 流式发送并完成** / 执行轨迹 / 旧路径重定向 / 合并页三 Tab / 旧 `/chat` 可访问 / **灰度开关回退** / 无未捕获 JS 错误。

### 16.3 实施中发现并修复的 4 个真实缺陷

| # | 缺陷 | 根因 | 修复 |
| --- | --- | --- | --- |
| B1 | **Plan 审批卡不出现** | `sessionStore.newSession()` 用 store 的 `chat` 模式建会话，而发送时用 `work` → 后端报"该会话是对话模式，不支持计划审批" | `newSession(nextMode?)` 支持显式指定；`send()` 统一用 `toBackend(mode)`；模式与当前会话不匹配时**自动换会话** |
| B2 | **Vite 编译 500** | `ComposerInput` 内对 prop 用 `v-model:mode`（prop 不可写） | 改为 `:mode` + `@update:mode` |
| B3 | **`/` 触发符残留** | 唤起命令面板后输入框仍留 `/`，导致随后输入 `@` 无法触发（正则要求前置空白） | 唤起时移除末尾 `/` |
| B4 | **任务标题显示"新建任务"** | 会话标题异步生成，`ws.tasks` 尚未刷新 | 有会话但无标题时显示"未命名任务" |

### 16.4 与计划的偏差（需决策）

| 项 | 计划 | 实际 | 处置建议 |
| --- | --- | --- | --- |
| 包体积 | < 350KB gzip | **463.5KB gzip**（element-plus 全量引入） | 需 `manualChunks` 拆分 + Element Plus 按需引入，否则达不到指标 |
| 空间（Space） | 后端 `spaces` 表 + 3 接口 | **仅本地 localStorage** | 后端接口未建，跨设备/多用户会失效 |
| 我的产物 | §7.3 聚合接口（`runs.files_json`） | 仍用旧 `/files` 文件系统直读 | 需后端补 2 个聚合接口 |
| 并发护栏 | §8.6 前端 3 并行 + 后端 429 | **未实现** | 最高优先级技术债，见 §14 建议 5 |
| run 取消语义 | `POST /runs/{id}/cancel` | 前端仅 `AbortController`，后端 run 状态仍为 running | 需后端补 |
| 暗色模式复核 | 逐页 | 仅工作台页 | 需补 13 页复核 |

### 16.5 界面效果（截图）

| 截图 | 内容 |
| --- | --- |
| `doc/workbuddy/screenshots/v3_01_workspace_chat.png` | v3 工作台：左栏能力入口 + 任务流、居中大标题、能力 Chip 行、圆角大输入框、框外工具条 |
| `doc/workbuddy/screenshots/v3_02_plan_approval.png` | Plan 审批卡：序号徽标 + 步骤标题/说明可编辑 + 右对齐「拒绝 / 确认执行」 |
| `doc/workbuddy/screenshots/v3_03_plan_after_approve.png` | 审批通过后续播完成 |
| `doc/workbuddy/screenshots/v3_04_command_palette.png` | `/` 命令面板 |
| `doc/workbuddy/screenshots/v3_05_at_picker.png` | `@` 上下文选择 |
| `doc/workbuddy/screenshots/v3_06_admin_capabilities.png` | 后台「专家·技能·连接器」三 Tab 合并页 |

---

## 17. 全量测试报告（v3.1，2026-10-25）

### 17.1 测试套件与结果

| # | 套件 | 命令 | 覆盖 | 结果 |
| --- | --- | --- | --- | --- |
| 1 | **后端全接口** | `npm run test:api` | OpenAPI **69/69 operation**，**80 条断言** | ✅ **100%** |
| 2 | **前后端契约** | `npm run test:contract` | 前端 58 个 API 调用点 ↔ 后端路由 | ✅ **58/58 匹配，0 不匹配** |
| 3 | **类型检查** | `npm run typecheck` | 全量 TS/Vue | ✅ 0 error |
| 4 | **单元测试** | `npm run test` | `sse` 6 + `client` 6 + `session` 5 | ✅ **17/17** |
| 5 | **生产构建** | `npm run build` | typecheck + vite build | ✅ 3.8s |
| 6 | **E2E 冒烟** | `npm run test:e2e:smoke` | 布局/输入区/模式/命令面板/@/流式/旧路径/灰度 | ✅ **28/28** |
| 7 | **E2E Plan 链路** | `npm run test:e2e:plan` | 计划生成 → 审批卡 → 确认 → 续播 | ✅ **9/9** |
| 8 | **E2E 全功能** | `npm run test:e2e` | 8 组 84 项（含全部 11 个功能页交互） | ✅ **84/84** |

> 6/7/8 均在**开发形态（5185）**与**单端口形态（18040，后端托管 dist）**下各跑一遍，全部通过。

### 17.2 E2E 全功能 8 组覆盖明细

| 组 | 项数 | 覆盖内容 |
| --- | --- | --- |
| A 前端↔后端连通性 | 8 | 浏览器内 fetch 5 个核心端点；技能表/MCP 列表数据确来自后端 |
| B v3 工作台 | 11 | 场景 Chip 填充、能力 Chip 切换、流式发送、执行轨迹、重命名、任务入栏、任务切换、新建、删除 |
| C 旧对话/工作页 | 7 | 会话抽屉、模型下拉、建议按钮、Plan 勾选、团队下拉 |
| D 能力后台三 Tab | 18 | 团队（新建/启停/删除）、技能（校验/弹窗）、MCP（卡片/刷新/重载/启停） |
| E 定时任务 | 6 | 新建（cron）、立即执行、删除、残留校验 |
| F 其余功能页 | 15 | 深度研究（降级提示）、产物 Tab/刷新、RAG 三 Tab、Web 检索（503 提示）、WR 执行、状态、设置（主题切换） |
| G 全局顶栏 | 5 | 4 个能力复选框、Skill 弹层全选/清空 |
| H 旧路径与灰度 | 14 | 11 条旧路径重定向 + `/chat` `/work` 可访问 + 全程无 JS 错误 |

### 17.3 本轮测试发现并修复的 3 个真实缺陷

| # | 缺陷 | 影响 | 根因 | 修复 |
| --- | --- | --- | --- | --- |
| **C1** | **技能校验 404** | 点「校验」必失败 | 前端 `skillValidate` 用 **GET**，后端只注册 **POST** `/skills/{name}/validate` | 改用 `post`（`api/index.ts`）；并新增 `contract_check.py` 自动比对 58 个调用点的 method/path |
| **C2** | **删除操作抛未捕获异常 + 列表不刷新** | 删除团队/定时任务/技能后前端报 `Unexpected end of JSON input`，列表不更新 | `client.ts` 对 **204 No Content**（空 body）仍调用 `res.json()` | `client.ts` 改为先判 204、再用 `text()` + `JSON.parse` 容错；新增 `client.spec.ts` 6 条回归用例 |
| **C3** | **`ScheduleCreate.skills` 不接受 `null`** | `POST /schedules` 传 `skills: null` → **422**，与 `RunRequest.skills`（支持 null）语义不一致 | schema 声明 `list[str]`，未做 nullable | `app/schemas/schedule.py` 改为 `list[str] \| None = None`；`scheduler_service` 落库时 `or []` |

### 17.4 测试基建产出（随仓库维护）

| 文件 | 作用 |
| --- | --- |
| `backend/scripts/api_test.py` | 后端 69 operation 全量测试（含动态 id 依赖链、SSE 事件断言、写操作自动清理） |
| `frontend/scripts/ui_probe/_browser.py` | 浏览器启动器：内置 Chromium 缺失时回退系统 Chrome（规避 revision 不匹配） |
| `frontend/scripts/ui_probe/contract_check.py` | 前后端契约自动比对（method + path） |
| `frontend/scripts/ui_probe/smoke.py` | E2E 冒烟 28 项 |
| `frontend/scripts/ui_probe/smoke_plan.py` | Plan 审批链路 9 项 |
| `frontend/scripts/ui_probe/func_test.py` | **全功能 E2E 84 项**（8 组） |
| `src/api/sse.spec.ts` / `client.spec.ts` / `stores/session.spec.ts` | 17 条单元测试 |

### 17.5 环境依赖提示

- `backend/.venv/bin/pip` 的 shebang 指向旧路径（venv 迁移遗留），**须用 `.venv/bin/python -m pip`**。
- Playwright 包版本须与 `~/Library/Caches/ms-playwright/` 中的浏览器 revision 匹配；不匹配时 `_browser.py` 会自动回退系统 Chrome。
- 深度研究与 Web 检索需 `BOCHA_API_KEY` / `SERPER_API_KEY`；当前未配置，前端**正确降级**（按钮禁用 + 明确警告），非缺陷。

---

## 18. 修订记录

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| v1.0 | 2026-10-25 | 首次产出：形态拆解 + 差异矩阵 + 6 阶段计划 |
| **v2.0** | 2026-10-25 | **合理性自评 + 勘误**：修正 6 处事实性错误（路由数/组件数/API 数/api 行数/测试覆盖/files 表）、统一 3 处矛盾数字（2.5/7 → 1.0/7）、重写 §9.1 方案 C 论据；**补强 5 项缺陷**：新增阶段 0 基建、§3.4 架构约束、§7.3 产物索引零表方案、§8.6 并发规范、§8.7 状态矩阵、§9.3 逐页处置表、§10.4 灰度回滚、§10.5 可观测性、§15 断言复核清单；**工作量重估** 前端 21~28 → 27~36、后端 4~6 → 5~7 |
| **v3.0** | 2026-10-25 | **首轮实施落地**：阶段 0~3 完成 + 阶段 4/5 部分（见 §16）。新增 17 个文件、改 5 个；typecheck 0 error、vitest 11/11、E2E 28/28 + Plan 链路 9/9、构建成功。记录 4 个实施期真实缺陷（B1~B4）与 6 项与计划的偏差 |
| **v3.1** | 2026-10-25 | **全量测试与缺陷修复**：新增 §17 测试报告（8 套件全绿）。后端 **69/69 operation、80 断言 100%**；前后端契约 **58/58**；单测 **17/17**；E2E **28/28 + 9/9 + 84/84**（开发形态与单端口形态各跑一遍）。修复 3 个真实缺陷：C1 技能校验 method 不匹配（GET→POST）、C2 204 空响应体导致删除异常与列表不刷新、C3 `ScheduleCreate.skills` 不接受 null。新增 `contract_check.py` 契约自动比对与 `client.spec.ts` 回归用例 |
