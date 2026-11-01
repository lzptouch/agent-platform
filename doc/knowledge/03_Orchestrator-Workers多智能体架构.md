# Orchestrator-Workers 多智能体架构

> **依据代码**：`apps/server/src/domain/research/manager.ts`、`apps/server/src/http/routes/research.ts`（2026-11-01 复核重写）
> **原理主题**：多智能体研究的编排模式。
>
> **⚠️ 诚实口径**：本篇的模式原理是当前代码的**设计取向**；实现现状是
> **Orchestrator 的阶段骨架**（状态机 + 持久化 + SSE），Worker 层与评分层
> 尚未实现。事实描述见 `../analysis/07_DeepResearch链路.md`。

---

## 一、要解决的问题

深度研究（Deep Research）与普通问答的开销结构不同：

| 维度 | 普通问答 | 深度研究 |
|---|---|---|
| 上下文 | 一问一答，线性 | 几十~几百条来源，远超窗口 |
| 子任务 | 无 | 子问题天然并行（分头查证） |
| 质量 | 一次生成 | 需要「评分 → 不达标重来」闭环 |
| 时长 | 秒级 | 分钟级，必须可中断、可续跑 |

单 Agent 的 function-calling 循环装不下这些：上下文线性增长会撑爆窗口；
串行检索慢；没有质量闸门。

## 二、Orchestrator-Workers 模式

```
                 ┌────────────────────────┐
                 │      Orchestrator      │
                 │  规划子问题 → 分派 →    │
                 │  回收摘要 → 综合 → 评分 │
                 └──────────┬─────────────┘
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ Worker 1 │ │ Worker 2 │ │ Worker 3 │   每个 Worker 跑 OODA 子循环
        └──────────┘ └──────────┘ └──────────┘
```

- **Orchestrator**：不亲自检索，只做规划（把问题拆成子问题）、分派、
  回收各 Worker 的**压缩摘要**、综合成报告、评分并决定是否再来一轮；
- **Worker**：各自独立的 Agent 循环，只对自己的子问题负责；
  产出的**原文不进主上下文**，只有摘要不进——这是「上下文收费站」思想
  （防止主上下文被子任务的检索原文淹没）；
- 对照：Anthropic「Building effective agents」把这类系统归为
  Orchestrator-Workers；其多 Agent 研究系统实测比单 Agent 在广度任务上
  显著占优（代价是 token 消耗数倍）。

## 三、OODA 子循环（Worker 内循环）

**Observe → Orient → Decide → Act**（观察 → 判断 → 决策 → 行动）：
源自军事决策理论，落到检索 Worker 上：

1. **Observe**：检索/抓取，拿到新证据；
2. **Orient**：证据与已有认知比对——缺口在哪？矛盾点在哪？
3. **Decide**：下一步是再检索（换关键词）、深读某篇、还是够了；
4. **Act**：执行，回到 1。

与一次性「搜完就写」相比，OODA 让 Worker 能**根据中途发现调整方向**——
研究的本质是不可预知的，计划外的线索往往最重要。

## 四、当前代码的落点（骨架）

`ResearchManager`（`manager.ts:58`）已实现的是 **Orchestrator 的外壳**：

| 模式要素 | 当前实现 |
|---|---|
| 阶段序列 | `queued → clarify → plan → search → read → synthesize → verify → report → done` 状态机（`manager.ts:173`） |
| 每阶段留痕 | `stages[]`（阶段 + 时间戳）+ 事件外发 |
| 中断/续跑 | `cancelled` 集合 + `checkpoint` 字段（见 04 篇） |
| Worker 层 | **未实现**（无子任务分派、无并行 Worker） |
| 质量评分 | **未实现**（`quality_score`/`iterations` 字段保留） |
| 检索执行 | **未实现**（无 Bocha/Serper 调用代码；无 Key 时任务明确 failed） |

即：阶段机的「骨架」已经能跑通任务生命周期（提交 → 推进 → 持久化 → 进度流 →
终态），但每个阶段内**没有真实工作**。接入检索与评分属于 `../design/09` 附录（批次）范畴。

## 五、为什么是「骨架先行」

多智能体系统最难的不是某一步的 LLM 调用，而是**生命周期**：
任务从哪来到哪去、中断后怎么续、用户怎么看到进度。
骨架先把这些「无聊但致命」的部分钉死（状态机、持久化、SSE、Key 门禁），
阶段内的智能可以逐个填充而不动架构。

## 六、业界对照

| 系统 | 编排 | 质量闭环 |
|---|---|---|
| Anthropic Multi-Agent Research | Orchestrator-Workers + 引用 | 有（内部评分） |
| LangGraph Supervisor | 状态图 + supervisor 节点 | 无内置 |
| CrewAI | 角色分工 + 流程 | 无内置 |
| 本项目（设计取向） | 阶段骨架 +（待接 Worker/评分） | 评分字段预留 |

## 参考

- Anthropic, *Building effective agents*（Orchestrator-Workers 模式定义）
- Anthropic, *How we built our multi-agent research system*
- `../analysis/07`（当前实现事实）
