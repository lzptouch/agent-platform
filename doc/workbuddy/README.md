# WorkBuddy 能力扩展方案（v2 · 代码校验后修订版）

本目录为 `agent` 对标 WorkBuddy 的能力扩展设计与实施计划。

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [00_需求分析与总体设计.md](./00_需求分析与总体设计.md) | 代码事实核对、原方案问题清单、WorkBuddy 对标、总体架构、**数据库选型与 Schema**、阶段划分 |
| [01_阶段1_数据基座与双模式会话.md](./01_阶段1_数据基座与双模式会话.md) | SQLAlchemy/Alembic 数据层 + `mode` 双模式 + 会话与运行记录 |
| [02_阶段2_Skill管理与Skill团队.md](./02_阶段2_Skill管理与Skill团队.md) | Skill 管理闭环（FS+DB 双源）、团队 CRUD、三种编排策略 |
| [03_阶段3_定时任务.md](./03_阶段3_定时任务.md) | APScheduler、幂等调度、租约防重、运行记录与事件回放 |
| [04_阶段4_前端整合与端到端验收.md](./04_阶段4_前端整合与端到端验收.md) | 工作台 UI、Plan 人工确认、E2E 验收与性能测试 |
| [05_技术选型与开源参考.md](./05_技术选型与开源参考.md) | 网络调研与开源实现对比、数据库/调度器选型依据、参考链接 |

## v2 相对 v1 的核心修订

1. **引入关系型数据库**（SQLite WAL，可通过 `DATABASE_URL` 切 PostgreSQL），不再沿用 JSON 落盘。
2. **模式对齐 WorkBuddy**：`chat`（对应 Ask）/ `work`（对应 Craft）/ `work + plan_first`（对应 Plan）。
3. **工具过滤下沉到 `ToolRegistry`**：原方案只改 system prompt，但工具数组由 `get_combined_tools()` 全量注入，会导致"提示词说没有、实际仍可调用"。
4. **会话历史只回放最终问答**：直接回放 `assistant(tool_calls)` + `tool` 消息会破坏 OpenAI tool_call 配对。
5. **定时任务不再"JSON + APScheduler jobstore"双写**：自有表为唯一真相，启动时重建 job；并用 `(task_id, scheduled_for)` 唯一约束保证幂等。
6. **补上多 worker / 多副本防重**：DB 租约锁，持锁进程才注册调度器。
7. **补上真实代码约束**：SSE 生成器内不能依赖 FastAPI 依赖注入的 DB Session；现有 `_save_log` 与会话落库需去重；`skills_dir` 只有单目录。

## 阅读顺序

先读 00 的「§1 代码核对结论」与「§2 原方案问题清单」，再按阶段 01→04 实施；05 提供选型证据与参考实现。
