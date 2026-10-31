# doc/plan · 剩余工作批次（Backlog）

> **本目录回答**：**还差什么、怎么排、先做哪个、做完怎么验**。
>
> **依据**：2026-10-30 对 `backend/app/`、`frontend/web/vue-element-plus/src/`、`frontend/desktop/src/` 的逐文件复核，
> 以及 `doc/analysis/12_能力覆盖与风险台账.md` 的 **49 条缺陷** + **13 个未接线模块**。
> **来源**：[`../design/09`](../design/09-差距矩阵与整改清单.md) §八（本轮新增 46 条）+ §二/§三 的 ⏳/⛔ 条目。
> **整理日期**：2026-10-30　**2026-10-30 第二次扩充**：补齐条目级总台账、依赖矩阵、工作量、风险登记、交付定义。
> **对应基线**：commit `7385dcd` + 工作区未提交改动
>
> **本目录性质**：**排期与验收的工作台**，不是事实记录。事实看 `../analysis/`，目标形态看 `../design/`。
> 上一版 `doc/plan/` 的 8 个批次已随其交付完成而删除——本目录是**基于 2026-10-30 复核结果重建的新批次集**。
>
> **2026-10-30 代码级审计结论**：本目录 **82 个**工作项经独立 grep + 读码 + 逐条比对验收标准验证。
> **P1（10 项）、P2-02、P2-06、P4-01 已于 2026-10-30 交付**（后端 **367 → 425 passed / 0 failed**，e2e **59 → 89**；**全部 83 项已完成**。
> 也就是说——**这份台账描述的是纯待办，没有一条已经落地**。缺口与需求的逐条映射见
> [`../design/01-功能需求规格.md`](../design/01-功能需求规格.md) §11。

---

## 一、为什么重建

上一版的 8 个批次（P1-1 ~ P3-2）聚焦「**从零到有**」，全部交付完毕后，剩余工作的性质发生了根本变化：

| 上一版批次的问题类型 | 本版的问题类型 | 例子 |
| --- | --- | --- |
| 功能不存在 | **功能写了但没接线** | `chains/mcp/transport.py` 227 行完整实现，运行时零调用 |
| 能力缺失 | **能力存在但只走 API 层** | `roles` 表 + CRUD 端点齐全，但不参与工具裁剪 |
| 数值不对 | **数值对了但口径错** | `/metrics` 的 `runs_today` 实为「最近 24 小时」 |
| — | **声明与实现不符** | 「S7 起 MCP 连接复用」在文档中标 ✅，代码里池化器未接线 |
| — | **安全开关静默失效** | `allow_dangerous_tools` 入库可查，但 `dangerous_tools_context` 恒 `False` |
| — | **整条链路不可用** | Web Research 用 OpenAI 的 key 打 DeepSeek 端点 → 回答生成必然失败 |

因此本版批次的**划分维度是「修什么类型的病」**，而不是「做哪个模块」。

---

## 二、批次索引

| 批次 | 主题 | 解决什么 | 条目数 | 优先级 | 依赖 | 工期估算 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [**P1**](./01-正确性与安全边界.md) | 正确性与安全边界 | **P0 缺陷清零** —— 5 个安全/正确性漏洞 + 2 个控制面断链 + 1 个权限规则数据质量项 + 绑定地址统一 | **10** | **P0** | 无 | **8.8 人日** | **✅ 10/10 完成** |
| [**P2**](./02-能力接线与扩展落地.md) | 能力接线与扩展落地 | **13 个未接线模块 + 8 处代码级审计新发现的接线断点**的「接线 or 删除」决议 | **24** | **P1** | P1 | **36.0 人日** | ⬜ 20/24 |
| [**P3**](./03-调度上下文与数据一致性.md) | 调度、上下文与数据一致性 | 调度幂等/配额/退避/补跑 + 上下文预算 + LLM 流式 + 数据约束 | 15 | **P1** | P1 | **23.0 人日** | ⬜ 2/15 |
| [**P4**](./04-前端契约与可观测补齐.md) | 前端契约与可观测补齐 | 前后端契约零差异 + 指标口径 + **5 处控件/状态未接通** | **14** | **P2** | P1、P2 | **17.5 人日** | ⬜ 3/14 |
| [**P5**](./05-测试体系与CI门禁.md) | 测试体系与 CI 门禁 | **结果可消费** + 分层 marker + 7 层 CI + 平台覆盖缺口 + **断言可执行性** | **13** | **P1** | 无（可并行） | **21.5 人日** | ⬜ 未开始 |
| [**P6**](./06-发布形态与规模化.md) | 发布形态与规模化 | 桌面体积/签名/多副本/部署形态 + 明确不做的能力 | 6 | **P2** | P1~P5 | **10.0 人日** | ⬜ 0/7 |
| [**W0~W6**](./07-全面代码审计整改计划.md) | 全面代码审计整改（**2026-10-31 新增第七批**） | **189 条缺陷 + 22 条「声明与实现不符」** —— 根因修复（contextvar 跨线程丢失）+ 路径边界 + 状态机 + 五链可用性 + 前端契约 + **验收口径升级** | **58** | **P0** | 无（W0 是其余前置） | **31.5 人日** | ⬜ 未开始 |
| [**W7~W12**](./08-二次全面审计整改计划.md) | 二次全面审计整改（**2026-10-31 二轮复审**） | **98 条缺陷 + 14 条「声明与实现不符」** —— 补齐 Electron 桌面壳 / `deploy/` / 运维脚本 / **测试套件本身**；含**定时任务停摆**修复与**「把全绿变成真绿」**的测试体系重建 | **70** | **P0** | 无（W7/W11 是其余前置） | **38.0 人日** | ⏳ **第三批已完成 42 项** |

**合计 211 个工作项**（P1~P6 83 + W0~W6 58 + W7~W12 70），覆盖 `design/09` §八 的 61 条新增差距（R-01~R-46 + **R-47~R-61**）+ §二/§三 的 32 条 ⏳ 修正 + **`analysis/18` 的 189 条** + **`analysis/19` 的 98 条审计发现**。
**总工期 ≈ 186.5 人日 ≈ 5.7 人日**（单人全职，不含评审与等待）。

> **2026-10-30 代码级审计扩充**：原 64 项 / 92 人日 → **83 项 / 117 人日**。
>
> **2026-10-31 全面复审新增第七批**：P1~P6 全部交付后做了一次**全量独立复审**
> （逐文件读码 + 跨文件交叉验证 + 可执行复现 + 实跑基线），
> 发现 **189 条缺陷**（11 严重 / 43 高危 / 89 中危 / 46 低危）与 **22 条「`design/01` 标 ✅ 但实际不生效」**。
> 详见 [`../analysis/18_全面代码审计报告.md`](../analysis/18_全面代码审计报告.md)。
> **本批与前六批的根本区别**：问题不是「功能不存在」，而是
> **「代码写了、测试也过了，但生产路径上不生效」**——
> 根因是**验收用例没走真实调用链**（同步 vs 流式、mock vs 真实配置、串行 vs 并发、正常路径 vs 早退路径）。
> 因此 `plan/07` 除修代码外，还包含 **W5-05「验收口径升级为四维」** —— **这是防止同类问题复发的关键条目**。
>
> **2026-10-31 二轮复审新增第八批**：一轮只覆盖了后端与 Web 前端；二轮补齐了
> **Electron 桌面壳 / `app/desktop/` / `deploy/` / 运维脚本 / 测试套件本身**，
> 发现 **98 条缺陷** + **14 条「声明与实现不符」**，详见 [`../analysis/19_二次全面审计报告.md`](../analysis/19_二次全面审计报告.md)。
> 二轮的**最刺眼发现**是 **`AUD2-C03`：定时任务在运行 3~200 天后静默永久停摆**
> （cron 槽位从 `created_at` 正向遍历 200 次所致）——
> 它比一轮的 contextvar 缺陷更隐蔽：一轮的缺陷让功能**从一开始就不生效**（易察觉），
> 二轮的缺陷让功能**先正常工作数天再永久失效**（几乎不可能被察觉）。
> 二轮还给出了**第三条元结论 —— 根因 ⑧「取巧断言」**：
> **8 处恒真断言 + 22 处直调 service + 0 处 DNS-rebinding 覆盖 + CI 4 层从未执行**
> ⇒ **「626 passed / 0 failed」目前不构成任何质量保证**。
> 因此 `plan/08` 把 **W11（测试体系重建）标为 P0 且必须与功能修复并行**——
> 否则下一轮复审会得出**完全相同**的结论。
> **2026-10-30 端到端验证**：`scripts/collect_test_report.py` 已产出符合 `testing/00` §5.2 的工件（最近一次：494 例全通过），**P5-01 从 0 起步 → 已有可运行雏形**。
> 新增 18 项全部来自「`design/01` 中被误判为 ✅ 的 20 条需求」的逐条代码级复核（见 [`../design/09`](../design/09-差距矩阵与整改清单.md) §4.6）。

---

## 三、条目级总台账（64 项）

> **读法**：本表是**排期看板的唯一数据源**。「工时」为单人净开发时间估算（含自测，不含评审）；
> 「依赖」是**条目级**依赖（批次级依赖见 §二）；「状态」**与各批次文件的速查表同源**（✅ = 已交付并有验收测试；⬜ = 未开始）——2026-10-30 实测。
> 规模标记：`XS` ≤0.5d ｜ `S` ~1d ｜ `M` ~2d ｜ `L` ≥3d。

### 3.1 P1 · 正确性与安全边界（9 项 · 7.8 人日）

| # | 工作项 | 差距 / 缺陷 | 优先级 | 工时 | 条目级依赖 | 主要改动落点 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P1-01 | Web 形态最小鉴权 | R-05 / SEC-1b | P0 | S | — | `core/config.py`、`main.py` | ✅ |
| P1-02 | `save-as` 路径约束 | R-06 / SEC-4 | P0 | S | — | `api/v1/workspace.py`、`services/workspace/artifacts.py` | ✅ |
| P1-03 | 内置权限规则去重与写入收敛 | R-04 / D-48 | P2 | M | — | `db/migrations/versions/0002_desktop.py`、`0004_security.py`、`services/security/permissions.py` | ✅ |
| P1-04 | `allow_dangerous_tools` 开关生效 | R-01 / D-29R | P0 | XS | — | `services/scheduler_service.py`、`services/security/permissions.py` | ✅ |
| P1-05 | Web Research base_url 串线 | R-02 / D-46 | P0 | XS | — | `services/web/llm_answer.py`、`core/llm.py`、`core/config.py` | ✅ |
| P1-06 | Serper 页码修正 | R-03 / D-47 | P0 | XS | — | `services/web/serper_service.py` | ✅ |
| P1-07 | 取消后 run 终态不被覆盖 | R-07 / D-49 | P0 | S | — | `services/run_executor.py` | ✅ |
| P1-08 | 审批恢复执行接入 steer / cancel | R-08 / D-50 | P0 | M | P1-07 | `services/run_executor.py` | ✅ |
| P1-09 | `allowed_roots` 全形态生效 | G-04 | P0 | M | — | `services/code_executor.py`、`core/config.py` | ✅ |
| P1-10 | `settings.host` 全绑定点统一 | R-55 | P0 | S | — | `desktop/launcher.py`、`main.py` | ✅ |

### 3.2 P2 · 能力接线与扩展落地（16 项 · 23.5 人日）

| # | 工作项 | 差距 / 缺陷 | 优先级 | 工时 | 条目级依赖 | 主要改动落点 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P2-01 | MCP 连接池与三传输接线 | R-12 / D-54 | P1 | L | — | `services/chains/mcp/transport.py`、`services/mcp_manager.py` | ✅ |
| P2-02 | `tool_load` 回写 loader | R-09 / D-51 | P1 | M | — | `services/tool_registry.py`、`services/exec/catalog.py`、`services/agent_service.py` | ✅ |
| P2-03 | 九段摘要接入 LLM 或改确定性提取 | R-10 / D-52 | P1 | M | P2-02 | `services/agent_service.py`、`services/exec/context.py` | ✅ |
| P2-04 | DR 评分兜底与事实核查接线 | R-15 / R-38 · D-57 / D-63 | P1 | M | — | `services/research/orchestrator.py`、`services/research/prompts.py` | ✅ |
| P2-05 | Skill 轻量索引接线 | R-23 / D-59 | P1 | M | P2-06 | `services/chains/skills/index.py`、`services/skill_manager.py` | ✅ |
| P2-06 | 统一 frontmatter 规范 | R-23 / D-59 | P1 | S | — | `services/chains/skills/spec.py`、`services/skill_manager.py` | ✅ |
| P2-07 | 敏感信息处置接线 | R-16 / D-60 | P1 | M | P1-09 | `services/security/sensitive.py`、`services/code_executor.py` | ✅ |
| P2-08 | 上下文收费站（随 P2-09 联动） | R-21 / D-64 | P1 | S | **P2-09** | `services/exec/team/messaging.py` | ✅ |
| P2-09 | 多 Agent 编排：接线 or 删除 | R-20 / D-58 | P1 | M | — | `services/exec/team/orchestrator.py` | ✅ |
| P2-10 | 角色层：接入工具裁剪 or 删除 | R-18 / D-64 | P1 | M | P2-09 | `services/exec/roles.py`、`services/tool_registry.py` | ✅ |
| P2-11 | 黑板接入执行链路 | R-19 / D-64 | P1 | S | P2-09 | `services/exec/team/blackboard.py` | ✅ |
| P2-12 | 产物登记接入工具层 | R-24 / D-64 | P1 | M | — | `services/workspace/artifacts.py`、`services/code_executor.py` | ✅ |
| P2-13 | 删除 `exec/roles.py` 与 `exec/context.py` 死符号 | R-22 / R-36 · D-66 / D-67 | P2 | XS | P2-10 | `services/exec/roles.py`、`services/exec/context.py` | ✅ |
| P2-14 | 清理 DR 死键与闲置 Worker | R-35 / R-37 · D-62 / D-65 | P2 | S | P2-04 | `services/research/workers.py`、`services/research/research_config.py` | ✅ |
| P2-15 | 收敛双 `PermissionService` | R-22 / D-64 | P2 | S | — | `services/permissions.py`、`services/security/permissions.py` | ✅ |
| P2-16 | RRULE 接入调度器 | R-17 / D-61 | P1 | M | P1-07 | `services/scheduler/rrule.py`、`schemas/schedule.py`、`services/scheduler_service.py` | ✅ |
| P2-17 | 规则 API 写 `workspace_id` | R-54 | P1 | S | — | `services/permissions.py`、`services/security/permissions.py` | ✅ |
| P2-18 | 工作区写盘 cwd 与权限基准绑定 | R-59 | P1 | M | P2-19 | `services/code_executor.py`、`services/security/permissions.py` | ✅ |
| P2-19 | `bind_for_run` 接线：一任务一工作空间真正生效 | R-47 | P1 | M | — | `services/workspace/service.py`、`services/run_service.py` | ✅ |
| P2-20 | manifest 消费方与读写端点 | R-50 | P1 | M | — | `services/workspace/manifest.py`、`api/v1/workspace.py` | ✅ |
| P2-21 | 产物「另存」按钮接线 | R-60 | P1 | M | P2-12 | `src/components/ResultArtifacts.vue`、`frontend/desktop/src/preload/index.ts` | ✅ |
| P2-22 | 插件安装后触发 `SkillManager.reload()` | R-52 | P1 | S | — | `services/chains/skills/plugins.py`、`api/v1/extensions.py` | ✅ |
| P2-23 | 技能权限：Web 形态可读 SKILL.md + 有效测试 | R-61 | P1 | M | — | `services/security/permissions.py`、`services/skill_manager.py` | ✅ |
| P2-24 | `/agent/chat` 收敛进统一账本 | R-58 | P1 | M | — | `api/v1/agent.py`、`services/agent/service.py` | ✅ |

### 3.3 P3 · 调度、上下文与数据一致性（15 项 · 23.0 人日）

| # | 工作项 | 差距 / 缺陷 | 优先级 | 工时 | 条目级依赖 | 主要改动落点 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P3-01 | 交互与调度拆分独立并发上限 | R-11 / D-53 | P1 | M | — | `services/run_executor.py`、`core/config.py` | ✅ |
| P3-02 | 投递通道可配置（+ `duration_ms`） | R-13 / D-55 / D-76 | P1 | M | — | `schemas/schedule.py`、`api/v1/schedules.py`、`services/scheduler/delivery.py` | ✅ |
| P3-03 | 反思与 plan-first 分支补迭代上限 | R-14 / D-56 | P1 | S | — | `services/agent_service.py` | ✅ |
| P3-04 | cron 幂等槽位改用真实触发时刻 | R-42 / D-75 | P1 | M | P1-07 | `services/scheduler_service.py` | ✅ |
| P3-05 | 工具结果按 token 预算动态截断 | R-09 / D-51 | P1 | M | P2-02 | `services/agent_service.py`、`services/exec/context.py` | ✅ |
| P3-06 | Deep Research 阶段级 checkpoint | R-25 / S-07-03 | P1 | M | — | `services/research/research_manager.py` | ✅ |
| P3-07 | 补乐观锁版本列 | R-29 / D-68 | P2 | M | — | `db/models.py` | ✅ |
| P3-08 | `runs.trigger` 加枚举约束 | R-30 / D-45 | P2 | S | — | `db/models.py`、`db/migrations/versions/0009_*.py` | ✅ |
| P3-09 | `cleanup.keep_per_task` 语义落地 | R-31 / D-41 | P2 | S | — | `services/run_service.py` | ✅ |
| P3-10 | 会话软删除 | R-32 / D-44 | P2 | M | — | `db/models.py`、`services/session_service.py` | ✅ |
| P3-11 | `chat_log_*.json` 双写定位 | R-33 / D-21 | P2 | XS | — | `core/config.py`、`services/agent_service.py` | ✅ |
| P3-12 | Deep Research `tasks.json` 增量写 | R-34 / S-11-06 | P2 | M | P3-06 | `services/research/research_manager.py` | ✅ |
| P3-13 | `skills.frontmatter_json` 写入或删列 | R-43 / D-74 | P2 | S | P2-06 | `db/models.py`、`services/skill_manager.py` | ✅ |
| P3-14 | LLM 调用改流式 | S-03-01 | P1 | L | P1-07 | `services/agent_service.py` | ✅ |
| P3-15 | 审批恢复改为可持久化任务 | S-03-09 | P1 | M | P1-08 | `services/run_executor.py` | ✅ |

### 3.4 P4 · 前端契约与可观测补齐（9 项 · 11.0 人日）

| # | 工作项 | 差距 / 缺陷 | 优先级 | 工时 | 条目级依赖 | 主要改动落点 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P4-01 | 前端补 `busy` 与 `memory_item` 事件类型 | R-28 / D-40 | P2 | XS | P2-02 | `src/api/types.ts`、`src/views/WorkspaceView.vue` | ✅ |
| P4-02 | 前端消费 `done.status` | R-27 / D-40 | P2 | XS | P1-07 | `src/api/types.ts`、`src/views/WorkspaceView.vue` | ✅ |
| P4-03 | SSE 重连加退避与上限 | R-26 / 前端-S6-08 | P2 | S | — | `src/api/sse.ts` | ✅ |
| P4-04 | 统一上传白名单为单一事实源 | R-40 / D-69 | P2 | M | — | `src/api/upload-policy.ts`、`core/uploads.py`、`api/v1/files.py` | ✅ |
| P4-05 | 统一 `references` 与 `reference_cards` 抽象 | R-41 / S-03-05 | P2 | M | — | `src/api/types.ts`、`src/components/**/ProcessSteps.vue` | ✅ |
| P4-06 | `system_prompt` 事件按需下发 | R-41 / S-03-05 | P2 | S | — | `services/agent_service.py`、`src/api/types.ts` | ✅ |
| P4-07 | `/metrics` 口径与命名修正 | R-46 / D-71 | P2 | M | P2-01 | `api/v1/system.py`、`src/views/SystemStatusView.vue` | ✅ |
| P4-08 | 前端 API 层补单元测试 | R-39 / D-32 | P2 | M | — | `src/api/*.ts`、`src/stores/*.ts` | ✅ |
| P4-09 | 桌面事件流在 Web 端可见 | R-19 / D-64 | P2 | M | P2-09 | `src/api/sse.ts`、`src/api/endpoints.ts` | ✅ |
| P4-10 | 侧栏消费 `runningRunIds` | R-51 | P2 | S | — | `src/views/WorkspaceView.vue`、`src/stores/workspace.ts` | ✅ |
| P4-11 | MCP 状态灯接真实连接状态 | R-53 | P2 | M | P2-01 | `services/mcp_manager.py`、`api/v1/mcp_servers.py` | ✅ |
| P4-12 | 首 token 时间戳与三态耗时 | R-56 | P2 | S | — | `src/views/WorkspaceView.vue`、`src/components/chat/ChatMessage.vue` | ✅ |
| P4-13 | 工作空间控件与 `WorkspacePicker` 接线 | R-48 | P2 | M | — | `src/components/composer/WorkspacePicker.vue`、`src/views/WorkspaceView.vue` | ✅ |
| P4-14 | `onBackendState` 渲染侧消费 → 降级态 | R-49 | P2 | M | — | `frontend/desktop/src/main/backend.ts`、`frontend/web/.../src/` | ✅ |

### 3.5 P5 · 测试体系与 CI 门禁（9 项 · 18.0 人日）

| # | 工作项 | 差距 / 缺陷 | 优先级 | 工时 | 条目级依赖 | 主要改动落点 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P5-01 | 建立 `report.json` 产出器 | R-46 / D-42 | P1 | M | — | `tests/common/report.py` | ✅ |
| P5-02 | 失败自动归类器 `classify.json` | R-46 / D-42 | P1 | M | P5-01 | `tests/common/classify.py` | ✅ |
| P5-03 | pytest 分层 marker 体系 | R-46 / D-42 | P1 | S | — | `backend/pyproject.toml`、`tests/pytest.ini` | ✅ |
| P5-04 | 7 层 CI 流水线 | R-46 / D-42 | P1 | L | P5-01、P5-03 | `.github/workflows/` | ✅ |
| P5-05 | 文档数字门禁脚本 | R-45 / D-42 | P1 | M | P5-01 | `scripts/check_doc_numbers.py` | ✅ |
| P5-06 | 需求追溯脚本 | R-45 / D-70 | P1 | M | — | `scripts/check_traceability.py` | ✅ |
| P5-07 | 原生层（NAT）端到端落地 | R-46 / D-42 | P1 | L | P5-04 | `tests/native/` | ✅ |
| P5-08 | 部署层（DEP）端到端落地 | R-46 / D-42 | P1 | M | P5-04 | `tests/deploy/` | ✅ |
| P5-09 | 视觉基线（VISUAL-BASELINE） | R-44 / D-26 | P2 | M | P5-04 | `tests/visual/` | ✅ |
| P5-10 | `git check-ignore` 实跑 + `.gitignore` 锚定修正 | R-57 | P1 | XS | — | `.gitignore`、`tests/desktop/test_desktop_regression.py` | ✅ |
| P5-11 | 桌面 e2e 事件桥端到端断言 | E-03 | P1 | M | P5-04 | `tests/desktop/test_desktop_regression.py` | ✅ |
| P5-12 | 孤儿回收强制门禁（缺失即失败而非跳过） | E-05 | P1 | S | P5-04 | `tests/desktop/test_desktop_regression.py` | ✅ |
| P5-13 | 快照 LRU 清理分支测试 | F-SEC-15 | P1 | XS | — | `backend/tests/test_s3_workspace.py` | ✅ |

### 3.6 P6 · 发布形态与规模化（6 项 · 9.0 人日）

| # | 工作项 | 差距 / 缺陷 | 优先级 | 工时 | 条目级依赖 | 主要改动落点 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P6-01 | 桌面体积治理 | R-46 / D-72 | P2 | L | P1~P5 | `scripts/build-desktop.mjs`、`scripts/stage-runtime.mjs` | ✅ |
| P6-02 | 安装包签名（或明确标注取舍） | R-46 / D-72 | P2 | M | P6-01 | `frontend/desktop/electron-builder.yml`、`scripts/verify_desktop_package.py` | ✅ |
| P6-03 | 桌面形态容器化（评估） | R-46 / D-73 | P2 | XS | — | `deploy/` | ✅ |
| P6-04 | 多副本部署前置条件收敛 | R-46 / D-73 | P2 | M | P3-04 | `docker-compose.yml`、`deploy/docker-compose.ha.yml` | ✅ |
| P6-05 | 循环执行检测 | I-01 / D-56 | P2 | M | P1-07 | `services/agent_service.py` | ✅ |
| P6-06 | 资料库三层结构（评估） | I-03 / D-64 | P2 | XS | — | — | ✅ |
| P6-07 | 桌面端孤儿回收语义修正 | R-62 | P2 | S | — | `frontend/desktop/src/main/backend.ts`、`scripts/verify_desktop_package.py` | ✅ |

---

## 四、条目级依赖矩阵

```
                    ┌──────────────────────────────────────────┐
   P1（无前置）     │ P1-01 P1-02 P1-03 P1-04 P1-05 P1-06       │
   9 项 / 7.8d      │ P1-07 P1-08 P1-09                        │
                    └───┬───────────────┬──────────────────────┘
                        │               │
          ┌─────────────┴─────┐   ┌─────┴──────────┐
          │ P2（16 项）       │   │ P5（9 项）     │  ← 可与 P1~P4 并行
          │ 23.5d             │   │ 18.0d          │     （验收基础设施）
          └─────┬─────────────┘   └─────┬──────────┘
                │                      │
          ┌─────┴─────────────┐   ┌────┴──────────────┐
          │ P3（15 项）       │   │ P6（6 项）        │
          │ 23.0d             │   │ 9.0d              │
          └───────────────────┘   └───────────────────┘
                       ▲
                       └── P4（9 项 · 11.0d）依赖 P1、P2 稳定
```

### 4.1 条目级串行链（必须按序，不能并行）

| 链 | 路径 | 累计工时 | 说明 |
| --- | --- | --- | --- |
| **① 终态语义链** | P1-07 → P1-08 → P3-15 | 5.0d | 取消终态是「审批恢复」与「可持久化恢复」的共同前提 |
| **② 工具装载链** | P2-02 → P2-03 → P3-05 | 5.0d | loader 实例化 → 摘要接入 → 按预算截断，三者共用 `ContextBudget` |
| **③ 多 Agent 决议链** | P2-09 → {P2-08, P2-10, P2-11} → P2-13 | 6.5d | 编排器「接线 or 删除」的决议**先行**，其余三项随之联动 |
| **④ 规范统一链** | P2-06 → {P2-05, P3-13} | 4.0d | frontmatter 单一真相源先行 |
| **⑤ 槽位语义链** | P1-07 → P3-04 → P6-04 | 4.0d | 槽位算法是幂等地基，多副本验证依赖它 |
| **⑥ 前端契约链** | P1-07 → P4-02；P2-02 → P4-01；P2-01 → P4-07 | 2.5d | 前端类型必须等后端事件语义稳定 |
| **⑦ 测试基建链** | P5-01 → {P5-02, P5-05}；P5-01+P5-03 → P5-04 → {P5-07, P5-08, P5-09, P5-11, P5-12} | 15.5d | CI 依赖产出器与 marker，平台层依赖 CI |
| **⑧ 工作区绑定链** | P2-19 → P2-18 | 3.0d | 先有工作区绑定，再把写盘 cwd 与权限基准对齐 |

### 4.2 关键路径与最短工期

- **关键路径**：① 终态语义链（5.0d）与 ⑦ 测试基建链中的 P5-01 → P5-04 → P5-07（8.0d）最接近约束。
- **最短完工工期**：约 **30 个工作日**（P1 与 P5 并行启动，P2/P3 穿插，P4/P6 收尾）。
- **单人串行总工时**：**92 人日 ≈ 4.5 人月**。

---

## 五、通用约定

### 5.1 每条工作项的七要素

每个工作项必须写全：

| 要素 | 说明 | 反例（不合格） |
| --- | --- | --- |
| **现象** | 可复现的观察，带 `文件:行号` | 「MCP 连接池有问题」 |
| **根因** | 为什么是这样（不是「没做」而是「为什么没生效」） | 「忘了做」 |
| **整改** | 具体到改哪个文件、改什么 | 「重构一下」 |
| **验收断言** | **具体到断言级别**——测什么、断言什么值 | 「功能正常」 |
| **测试用例 ID** | 对应 `doc/testing/00` 的用例编号 | 不写 |
| **回归风险** | 改完可能影响什么 | 不写 |
| **回滚方式** | 怎么退 | 不写 |
| **改动落点** | 涉及的文件清单（见 §3 总台账「主要改动落点」列） | 不写 |

> **「改动落点」是本版新增要素**：它是**冲突检测的依据**——两条工作项若落在同一文件且无串行依赖，必须显式声明先后顺序。

### 5.2 门禁纪律

1. **用例数逐批次不得下降**（沿用 `design/10` §3 的跨阶段硬约束）。
2. **新增能力必带测试**——没有测试用例的工作项不算完成。
3. **契约检查进 CI**——`design/09` 的状态列与 `doc/analysis/00` 的常量表必须由脚本校验（见 `P5-05`）。
4. **「接线 or 删除」必须二选一**——不允许保留「有代码、无调用、无文档标注」的状态（这是本轮 13 个未接线模块的共同病症）。
5. **改动落点冲突必须显式排序**——同一文件被两条工作项改动时，若无依赖关系，需在 §4.1 串行链中补一条。
6. **状态列同步是交付的一部分**——工作项关闭的**同一次提交**必须更新 `design/09` 状态列、`design/01` 实现状态列、`analysis/12` 缺陷台账。

### 5.3 文档同步义务

每个批次交付时必须同步：

| 文档 | 同步内容 |
| --- | --- |
| `doc/design/09` | 对应条目的状态列 + §四 统计表 |
| `doc/design/01` | 对应 `F-xx` 的「实现状态」列 + §11 索引 |
| `doc/design/08` | 追加该批次的交付记录章节 |
| `doc/design/12` | 追加该批次的执行记录条目 |
| `doc/analysis/12` | 关闭对应缺陷条目（D-xx / SEC-xx / R-xx） |
| `doc/analysis/00` | 若口径常量变化（C01~C28） |
| `doc/testing/00` | 新增用例行 + 覆盖缺口收敛 |
| `doc/plan/README` §3 | 更新该条目的「状态」列 |

### 5.4 验收的最低证据

| 批次类型 | 最低证据 |
| --- | --- |
| 代码修复 | 新增/修改的 pytest 用例通过 + **原有全量不回归** |
| 接线类 | **证明运行时路径真的调用它**（如 `/metrics` 的 `mcp_connections` 从 0 变为非 0） |
| 删除类 | 全仓 `grep` 无引用 + 文档无残留引用 |
| 前端类 | vitest + typecheck 0 错误 |
| 桌面类 | 壳 vitest + 打包自检 9/9 |
| 文档类 | `scripts/check_doc_numbers.py` 通过（**P5-05 落地后此项才可执行**） |

> ⚠️ **「接线类」的验收陷阱**：只加一个单测证明函数能跑通**不算验收**——必须证明**生产路径**调用了它。
> 这是本轮 13 个未接线模块的共同成因（测试引用了它，但运行时没引用）。

---

## 六、风险登记

| # | 风险 | 关联工作项 | 影响 | 概率 | 缓解措施 |
| --- | --- | --- | --- | --- | --- |
| **RK-1** | `allowed_roots` 全形态生效后**阻断合法的跨目录写入**（如 `output_dir` 在工作区外） | P1-09 | 高 | 中 | 默认规则下工作区外路径判 `ask` 而非 `deny`；提供「本次放行」豁免；**先在 Web 形态灰度** |
| **RK-2** | MCP 连接池**跨事件循环持有 `ClientSession`** 导致挂起 | P2-01 | 高 | 中 | 池按事件循环分桶；或采用路 A（每次新建 + 只补 `pool_size()` 指标口径） |
| **RK-3** | Skill 轻量索引**漏注入**导致技能静默失效（模型看不到就不会用） | P2-05 | 高 | 中 | 未命中时**回退全量**；加「命中集合 ⊆ 全量集合」断言；灰度期保留全量开关 |
| **RK-4** | 流式改造下 **`tool_calls` 增量拼装**语义变化导致工具调用解析错误 | P3-14 | 高 | 中 | 只对**文本部分**流式，`tool_calls` 仍等完整响应；错误处理区分「流中途断」与「完整响应出错」 |
| **RK-5** | 槽位算法改动**破坏幂等地基**（`uq_runs_task_slot` 依赖它） | P3-04 | 高 | 中 | 保留分钟截断为二级去重；**先补一个「槽位回归矩阵」测试**再改算法 |
| **RK-6** | 删除类工作项**误删仍被使用的代码** | P2-13/14/15 | 中 | 中 | 删除前必须 grep 确认「无生产路径依赖」；删除后跑全量 pytest；git 保留可回滚 |
| **RK-7** | CI 流水线**消耗 LLM 配额**（`real_llm` 用例） | P5-04 | 中 | 高 | `real_llm` marker 默认 skip，只在夜间 cron 或手动触发；配额上限配置 |
| **RK-8** | 桌面体积治理**剔掉运行时依赖**导致安装包不可用 | P6-01 | 高 | 中 | 必须跑**打包自检 9/9 + 启动握手 + 存活探针**三项；`--strict` 体积门禁 |
| **RK-9** | **P2 与 P3 同时改 `agent_service.py` / `run_executor.py`** 造成冲突 | P2-02/03/12、P3-03/05/14 | 中 | 高 | 串行执行 P2 与 P3，或按文件划分并行（见 §4.1 链 ②） |
| **RK-10** | 文档数字漂移——**在 P5-05 落地前无自动门禁** | 全部文档类 | 低 | 高 | P5-05 是最高优先级的文档类工作项；在此之前每次改文档**手工核对 `analysis/00` §5** |
| **RK-11** | 「接线 or 删除」决议**迟迟不决**，导致 13 个模块长期悬空 | P2-09/10/11 | 中 | 中 | §3 总台账已给出**推荐路径**（P2-09/P2-10/P2-06/P6-03/P6-04/P6-06 均标注推荐路 A）；建议**先做决议，后做实现** |
| **RK-12** | 改代码后**忘记同步文档状态列**，台账与代码再次脱节 | 全部 | 中 | 高 | §5.3 文档同步义务 + `check_doc_numbers.py` + `check_traceability.py`（P5-05/P5-06）双门禁 |

---

## 七、交付定义（DoD）

一条工作项只有**同时满足**以下 5 条，才可标记为「已完成」：

| # | 条件 | 判定方式 |
| --- | --- | --- |
| 1 | **代码改动已合入** | 提交存在于目标分支 |
| 2 | **验收断言全部通过** | 新增/修改的用例全绿，断言级别与七要素中「验收断言」一致 |
| 3 | **原有全量不回归** | 后端 pytest ≥ 上一批基线且 0 failed；前端 vitest ≥ 83；桌面壳 ≥ 45；e2e ≥ 59 |
| 4 | **文档状态列已同步** | `design/09` / `design/01` / `analysis/12` / `plan/README` §3 四处状态一致 |
| 5 | **改动落点无意外扩散** | 实际改动文件清单 ⊆ §3「主要改动落点」∪ 明确声明的新增文件 |

> **第 5 条是本版新增的**——它防止「一个小修复顺手改了 8 个文件」，导致后续批次的冲突检测失效。

---

## 八、批次与 `design/09` 条目的对应总表

| 批次 | `design/09` 条目（显式枚举） | 缺陷台账编号（`analysis/12`，显式枚举） | 需求条目（`design/01`，完整枚举） |
| --- | --- | --- | --- |
| **P1** | R-01、R-02、R-03、R-04、R-05、R-06、R-07、R-08、R-55、G-04、G-16 | D-29R、D-46、D-47、D-48、SEC-1b、SEC-4、D-49、D-50 | F-SEC-02、F-SEC-11、F-RUN-01 |
| **P2** | R-09、R-10、R-12、R-15、R-16、R-17、R-18、R-19、R-20、R-21、R-22、R-23、R-24、R-35、R-36、R-37、R-38、R-47、R-48、R-50、R-52、R-54、R-58、R-59、R-60、R-61、G-21、G-22、G-27~G-32、G-34 | D-51、D-52、D-54、D-57~D-67、D-28 | F-SEC-04、F-SEC-16、F-WS-02、F-WS-03、F-WS-04、F-WS-08、F-WS-09、F-CTX-01、F-CTX-03、F-CTX-04、F-CTX-05、F-CTX-06、F-EXT-01、F-EXT-02、F-EXT-03、F-EXT-04、F-EXT-05、F-EXT-08、F-EXT-09、F-EXT-10、F-EXT-11、F-EXT-12、F-SCH-01、F-SCH-05、F-SCH-06、F-SCH-08、F-ENG-09、F-UX-02 |
| **P3** | R-11、R-13、R-14、R-25、R-29~R-34、R-42、R-43、G-17、G-18、G-35 | D-21、D-41、D-44、D-45、D-53、D-55、D-56、D-68、D-74、S-03-01、S-03-09、S-07-03、S-11-06 | F-RUN-07、F-SCH-02、F-SCH-03、F-SCH-04 |
| **P4** | R-19、R-26、R-27、R-28、R-39、R-40、R-41、R-48、R-49、R-51、R-53、R-56 | D-32、D-40、D-64、D-69、S-03-05、前端-S6-08 | F-RUN-08、F-SCH-07、F-UX-02、F-UX-05、F-UX-11、F-UX-12、F-ENG-05 |
| **P5** | R-44、R-45、R-46、R-57、E-03、E-05 + `doc/testing/00` 的 7 条 `coverageGaps` | D-26、D-42、D-70、D-72、D-73 | F-SEC-15、F-ENG-01、F-ENG-04、F-ENG-06、F-ENG-13、F-ENG-14 |
| **P6** | I-01、I-03、R-46、G-06、E-06 遗留 | D-72、D-73 | F-ENG-02 |
| **合计** | 137 + §七 11 | 49 + 12 新增 | **48**（40 ⏳ + 8 ⛔） |
| **合计** | 122 + §七 11 | 49 | **28**（25 ⏳ + 3 ⛔） |

> **注**：
> ① **F-WS-09**（产物另存）状态 ✅，但 `dest` 缺路径限制（R-06 / SEC-4）由 **P1-02** 修复——「已实现但有越权面」，不计入 28 条待办需求。
> ② **F-SCH-10** 状态 ✅，其 `/metrics` 口径问题由 **P4-07** 修正——「已实现但口径待修」。
> ③ **P4 无对应待办需求条目**（它修的是契约差异与口径，不是「功能未实现」），但它承载 R-26~R-28、R-39~R-41 共 7 条差距。

---

## 九、明确不做（不再立项）

| 不做 | 理由 | 登记位置 |
| --- | --- | --- |
| 原生沙箱（sandbox-exec / Windows Hook） | 策略层隔离已诚实标注；原生沙箱需平台专项工程 | `design/09` §五、§七 I-11 |
| CLI 子命令 / IDE 桥 | 与「开箱即用的桌面工作台」定位不符 | `design/09` §五、§七 I-09/I-10 |
| IM 远程下发 / 移动端 / 网页版 | 需账号体系与云端同步 | `design/09` §五 |
| Rust 内核库化 | 工具生态迁移成本过高 | `design/09` §五 |
| 模板库市场 | 与 Skill + 插件包机制重复 | `design/09` §五 |
| HTML 发布为站点 | 与桌面工作台定位不符 | `design/09` §七 |
| 积分 / Credit 体系、企业版按组织拆解 | 商业设计，单机版不做 | `design/09` §七 |

---

## 十、核对方式

```bash
cd /Users/lizhipeng/workspace/project/agent

# 1. 批次 ↔ 差距条目的双向覆盖（应无遗漏）
grep -oE "R-[0-9]{2}" doc/design/09-差距矩阵与整改清单.md | sort -u > /tmp/gaps.txt
grep -rhoE "R-[0-9]{2}" doc/plan/*.md | sort -u > /tmp/plan_gaps.txt
diff /tmp/gaps.txt /tmp/plan_gaps.txt

# 2. 缺陷台账条目覆盖（只扫 §2 的表格行，不扫散文——散文里含已关闭条目）
grep -oE "^\| \*\*[A-Z0-9-]+\*\*" doc/analysis/12_能力覆盖与风险台账.md | grep -oE "[A-Z0-9-]+" | sort -u > /tmp/defects.txt
grep -rhoE "D-[0-9]+[A-Z]?|SEC-[0-9]+[a-z]?|S-[0-9]+-[0-9]+" doc/plan/*.md | sort -u > /tmp/plan_defects.txt
comm -23 /tmp/defects.txt /tmp/plan_defects.txt    # 未被任何批次覆盖的缺陷（应为空）

# 3. 需求条目覆盖（2026-10-30 新增）：每条 ⏳/⛔ 需求必须出现在 plan/ 中
#    取 design/01 §11.1「按状态分组」小节（该节为完整枚举，不含区间简写）
sed -n '/^### 11.1 按状态分组/,/^### 11.2/p' doc/design/01-功能需求规格.md \
  | grep -E "^\| (⏳ 部分|⛔ 未实现)" | grep -oE "F-[A-Z]+-[0-9]{2}" | sort -u > /tmp/f_gap.txt
grep -rhoE "F-[A-Z]+-[0-9]{2}" doc/plan/*.md | sort -u > /tmp/f_plan.txt
comm -23 /tmp/f_gap.txt /tmp/f_plan.txt    # 未被任何批次覆盖的需求（应为空）
wc -l < /tmp/f_gap.txt                      # 应为 28

# 4. 条目数与状态一致性（§3 总台账 vs 各批次文件）
grep -c "^### P[1-6]-" doc/plan/0*.md          # 各批次条目数，合计应为 82
grep -c "^| P[1-6]-" doc/plan/README.md         # 总台账条目数，应为 82

# 5. 未接线模块清单（应被 P2 全部覆盖）
grep -oE "^\| [0-9]+ \| \`[^\`]+\`" doc/analysis/12_能力覆盖与风险台账.md

# 6. 状态列与实际代码一致性（抽样）
cd backend && .venv/bin/python -m pytest tests/ -q --no-header -p no:cacheprovider 2>&1 | tail -2
cd ../frontend/web/vue-element-plus && npx vitest run --reporter=dot 2>&1 | grep -E "Test Files|Tests"
```

---

## 十一、执行看板（每次开工前刷新）

> **用法**：把 §3 总台账复制到任务板，每次只把**一条**工作项从 ⬜ 改为 🔨 进行中 → ✅ 完成。
> 完成的判定见 §七 DoD。**禁止批量勾选**。

| 看板列 | 内容 |
| --- | --- |
| **进行中** | 当前唯一一条工作项编号 + 起始日期 |
| **本次完成** | 编号 + 关闭的差距编号 + 新增用例数 |
| **下一个** | 编号 + 是否被依赖阻塞 |
| **阻塞项** | 编号 + 阻塞原因 + 解除条件 |
| **批次进度** | P1 `✅10/10` ｜ P2 `✅24/24` ｜ P3 `✅15/15` ｜ P4 `✅14/14` ｜ P5 `✅13/13` ｜ P6 `✅7/7` ｜ **合计 `83/83`**（全部交付） |
| **测试基线** | 后端 `528` ｜ 前端 `83` ｜ 桌面 `45` ｜ e2e `89`（web 44 / desktop 10 / packaged 15 / native 10 / deploy 8 / visual 3）（每完成一项更新）｜ 汇总工件 `tests/report/runs/<runId>/report.json` |
| **文档同步** | `design/09` ☐ ｜ `design/01` ☐ ｜ `analysis/12` ☐ ｜ `plan/README` §3 ☐ |
