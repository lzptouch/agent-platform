"""``app.services.agent`` —— **遗留链路（legacy）**。

S1（WP-1.5）起，本包不再是主 Agent 循环：

- 主链路是 ``app.services.agent_service.AgentService`` + ``app.services.run_executor``，
  所有运行都会落 ``runs`` / ``run_events`` 账本；
- 本包提供的是早期 notebook 实验代码（plan→action→reflection→answer），
  仅通过 ``POST /api/v1/agent/chat`` 暴露，**不写账本、不参与统一执行器**。

保留原因：仍有外部调用方依赖该端点；处置方式按
``doc/roadmap/02-阶段S1-架构整改.md`` 的 WP-1.5：标注为旧链路 → 逐步下线。
新增能力一律不要写在这里。
"""
