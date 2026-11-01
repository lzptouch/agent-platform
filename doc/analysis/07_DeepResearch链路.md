# DeepResearch 链路

> **依据代码**：`apps/server/src/domain/research/manager.ts`、`http/routes/research.ts`、`apps/ui/src/views/ResearchView.vue`、`apps/ui/src/api/sse.ts`（2026-11-01 复核）
>
> **⚠️ 诚实口径**：当前 TS 后端是**阶段骨架**——任务生命周期、阶段推进、持久化、
> SSE 进度流、Key 门禁都是真实的；但**检索、OODA 子循环、评分迭代未实现**
> （无 Bocha/Serper 调用代码，无评分器，`quality_score`/`iterations` 从不写入）。
> 本文只描述代码里存在的东西；Orchestrator-Workers 的**模式原理**见
> `../knowledge/03_Orchestrator-Workers多智能体架构.md`。

# 第一部分 现状事实

## 一、定位

用户提交一个研究问题 → 任务经历 7 个阶段 → 产出报告。
端点 7 个（`05` §2 research 组）；并发上限 `research_max_concurrent=3`（配置位）。

## 二、编排骨架（`ResearchManager`，`manager.ts:58`）

内存态：`tasks: Map<id, ResearchTask>` + `cancelled: Set` + `listeners: Map<id, Set<fn>>`。

**任务结构**（`manager.ts:31`）：

```ts
{ id, query, status, created_at, updated_at,
  stages: [{stage, at, detail?}],   // OODA 阶段记录
  sources: [{title, url, snippet}], // 检索到的资料（当前恒空）
  report, checkpoint, error,
  quality_score, iterations }       // 保留字段，当前不写入
```

**阶段机**（`run()`，`manager.ts:170`）：

```
queued → clarify → plan → search → read → synthesize → verify → report → done
              （每个阶段：置 status → 记 stages[] → 写 checkpoint → persist() → emit stage 事件）
              cancelled 集合命中 → cancelled
              阶段推进完成后：无检索 Key → failed（写明原因）；有 Key → done + 占位报告
```

## 三、checkpoint 续跑

- `checkpoint` = **最后完成的阶段名**；重跑从 `stages.indexOf(checkpoint)+1` 继续
  （`manager.ts:174`）；
- 每阶段推进即 `persist()`（全量写 `userData/research/tasks.json`）；
- 启动时 `loadPersisted()` 读回全部任务。

## 四、检索提供方与 Key 门禁

- `research_configured = bocha_api_key 或 serper_api_key 非空`（`shared/config.ts:476`）；
- `POST /research`：未配置 → 任务照建但响应 `status: "failed"` + 明示原因
  （不当场 4xx/5xx，让前端能展示任务卡片）；
- `GET /research/health`：`search_provider` ∈ `bocha / serper / none`（bocha 优先）。

## 五、SSE 进度流（`GET /research/{id}/stream`）

- 订阅 `ResearchManager.subscribe()` 的监听器 → `stage/progress/done/error` 事件直推；
- 同时 500ms 轮询任务状态：到终态（done/failed/cancelled）发 `done{status}` 收尾；
- 心跳 `: ping`；最长 3600s 自动断开（`research.ts:110`）；
- 前端 `streamResearchWithReconnect()` 负责断流续订与去重（见 `06` §五）。

## 六、落盘与持久化

- 唯一持久化是 `tasks.json`（全量 JSON 数组，每次 persist 整写）；
- **不写 `runs` 账本**（当前 TS 实现里研究任务与运行账本无关联；
  `runs.trigger` 的 CHECK 允许 `'research'` 是契约层预留）；
- 报告同时以 `task.report` 字段存于 tasks.json。

# 第二部分 原理剖析

## 七、为什么是 Orchestrator-Workers 而不是单 Agent 循环（模式意图）

深度研究的开销结构与普通问答不同：检索面宽（几十上百条来源）、
子任务天然并行（多个子问题同时查证）、需要**质量闭环**（评分不达标就再来一轮）。
单 Agent 循环的线性上下文装不下这些。Orchestrator-Workers 把「规划/分派/综合」
与「执行子任务」分开，OODA（观察-判断-决策-行动）给每个 Worker 一个内循环。
（当前代码只落地了 Orchestrator 的阶段骨架；Worker 与评分器尚未实现，
原理详见 `../knowledge/03`、`../knowledge/04`。）

## 八、为什么任务持久化用 `tasks.json` 而不是进主库

研究任务是**长生命周期 + 自包含**的对象（阶段记录、来源清单、报告都在一处），
读写在任务边界天然成批。JSON 文件够用且可直接人工查看/修错。
代价：全量读写，任务数增长后 IO 放大（已知边界；主库已有 `agent_messages` 等
扩展表可承接，属未来演进点）。

## 九、为什么「无 Key」要走 failed 任务而不是直接报错

研究是异步任务：提交接口返回后，用户会在列表页看到它。直接 5xx 会让
「任务是否存在过」都不可考；建成 failed 任务并写明原因（缺哪个 Key），
界面可以如实展示「任务已提交但因未配置检索而失败」，可删除、可重提。

# 第三部分 已知边界与观察

1. **检索/阅读/综合/核查未实现**：阶段只推进状态机，无真实工作；有 Key 时报告为占位文本；
2. `quality_score` / `iterations` / `sources` 字段保留但无写入方；
3. `research_max_concurrent=3` 配置位存在，但当前无并发闸（任务是 `void run()` 后台推进）；
4. `tasks.json` 全量读写（§八的代价）；
5. `research_fact_check` / `bocha_*` 等配置位保留，无消费方。
