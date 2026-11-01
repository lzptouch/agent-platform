# 需求追溯表（自动生成 · 禁手改）

> 由 `scripts/check_traceability.py` 生成（`python scripts/check_traceability.py`）。
> 推导链：`design/01` 的需求 → 差距编号 → `plan/` 工作项 → **测试用例 ID**。
> 口径：**已实现（✅）的需求必须有对应用例**；未实现（⏳/⛔）的需求标注承接批次。

| 需求 | 标题 | 状态 | 对应用例 | 承接批次 |
| --- | --- | --- | --- | --- |
| F-SEC-01 | 权限判定对**所有形态**生效，不限于桌面 | ✅ | code:tests/test_p5_batch.py | — |
| F-SEC-02 | 默认绑定 `127.0.0.1`；CORS 需显式白名单 | ✅ | SEC-01<br>SEC-WS-04<br>SEC-RULE-01<br>SEC-DANGER-01<br>SEC-WS-05… | — |
| F-SEC-03 | 规则模型支持 file/command/tool/network 四类 scope | ✅ | SEC-01<br>SEC-WS-04<br>SEC-RULE-01<br>SEC-DANGER-01<br>SEC-WS-05… | — |
| F-SEC-04 | 规则支持优先级、风险等级、作用域（全局/工作空间） | ✅ | SEC-01<br>SEC-WS-04<br>SEC-RULE-01<br>SEC-DANGER-01<br>SEC-WS-05… | — |
| F-SEC-05 | `ask` 必须**阻塞等待**用户决策 | ✅ | SEC-01<br>SEC-WS-04<br>SEC-RULE-01<br>SEC-DANGER-01<br>SEC-WS-05… | — |
| F-SEC-06 | 审批超时按**拒绝**处理 | ✅ | SEC-01<br>SEC-WS-04<br>SEC-RULE-01<br>SEC-DANGER-01<br>SEC-WS-05… | — |
| F-SEC-07 | 每次判定写入决策日志（含命中规则与原因） | ✅ | SEC-01<br>SEC-WS-04<br>SEC-RULE-01<br>SEC-DANGER-01<br>SEC-WS-05… | — |
| F-SEC-08 | 路径归一化（符号链接、`..`、Windows 大小写、UNC） | ✅ | SEC-01<br>SEC-WS-04<br>SEC-RULE-01<br>SEC-DANGER-01<br>SEC-WS-05… | — |
| F-SEC-09 | 命令策略升级为规则集，串联命令逐段判定 | ✅ | SEC-01<br>SEC-WS-04<br>SEC-RULE-01<br>SEC-DANGER-01<br>SEC-WS-05… | — |
| F-SEC-10 | 禁止路径（凭据/配置/系统目录）直接拒绝且不询问 | ✅ | SEC-01<br>SEC-WS-04<br>SEC-RULE-01<br>SEC-DANGER-01<br>SEC-WS-05… | — |
| F-SEC-11 | 工作区可写根白名单全形态默认开启 | ✅ | SEC-WS-05 | P1-09 |
| F-SEC-12 | 沙箱能力**诚实化**：探测真实能力并返回可读说明 | ✅ | SEC-01<br>SEC-WS-04<br>SEC-RULE-01<br>SEC-DANGER-01<br>SEC-WS-05… | — |
| F-SEC-13 | 临时决定带过期时间；会话级决定不落库 | ✅ | SEC-01<br>SEC-WS-04<br>SEC-RULE-01<br>SEC-DANGER-01<br>SEC-WS-05… | — |
| F-SEC-14 | 动作级 JSONL 审计（时间/run/工具/参数/裁决/规则/耗时） | ✅ | SEC-01<br>SEC-WS-04<br>SEC-RULE-01<br>SEC-DANGER-01<br>SEC-WS-05… | — |
| F-SEC-15 | 写前自动快照 + 快照预算 + LRU 清理 | ✅ | SEC-SCAN-01<br>SEC-SCAN-02<br>SEC-SCAN-03 | P2-07 |
| F-SEC-16 | 敏感信息（密钥/凭证）识别与三种处置 | ✅ | SEC-SCAN-01<br>SEC-SCAN-02<br>SEC-SCAN-03 | P2-07 |
| F-SEC-17 | 权限服务单例 + 规则缓存 | ✅ | SEC-01<br>SEC-WS-04<br>SEC-RULE-01<br>SEC-DANGER-01<br>SEC-WS-05… | — |
| F-WS-01 | 工作空间是一等资源（列表/创建/切换/归档） | ✅ | WS-CWD-01<br>WS-BIND-01<br>WS-MANIFEST-01<br>WS-SAVEAS-01<br>DESK-EVENT-01… | — |
| F-WS-02 | 一任务一工作空间，run 期间锁定 | ✅ | WS-CWD-01<br>WS-BIND-01<br>WS-MANIFEST-01<br>WS-SAVEAS-01<br>DESK-EVENT-01… | — |
| F-WS-03 | 未指定目录时自动创建独立工作目录 | ✅ | WS-CWD-01<br>WS-BIND-01<br>WS-MANIFEST-01<br>WS-SAVEAS-01<br>DESK-EVENT-01… | — |
| F-WS-04 | manifest 记录可写根、默认策略、模型、技能、扩展 | ✅ | WS-CWD-01<br>WS-BIND-01<br>WS-MANIFEST-01<br>WS-SAVEAS-01<br>DESK-EVENT-01… | — |
| F-WS-05 | 逐文件变更记录（前后哈希、快照引用、工具、操作） | ✅ | WS-CWD-01<br>WS-BIND-01<br>WS-MANIFEST-01<br>WS-SAVEAS-01<br>DESK-EVENT-01… | — |
| F-WS-06 | 文本文件行级 diff；二进制给摘要 | ✅ | WS-CWD-01<br>WS-BIND-01<br>WS-MANIFEST-01<br>WS-SAVEAS-01<br>DESK-EVENT-01… | — |
| F-WS-07 | 变更可回退，回退本身留痕 | ✅ | WS-CWD-01<br>WS-BIND-01<br>WS-MANIFEST-01<br>WS-SAVEAS-01<br>DESK-EVENT-01… | — |
| F-WS-08 | 产物独立建模（类型/大小/预览/来源 run） | ✅ | LEDGER-ART-01 | P2-12 |
| F-WS-09 | 产物可另存到用户指定位置 | ✅ | WS-CWD-01<br>WS-BIND-01<br>WS-MANIFEST-01<br>WS-SAVEAS-01<br>DESK-EVENT-01… | 01 |
| F-RUN-01 | 前端"停止"必须调用后端 cancel | ✅ | RUN-CANCEL-01<br>RUN-CLEANUP-01<br>RUN-LOG-01<br>RUN-TASKS-01<br>RUN-SIDEBAR-01… | 01 |
| F-RUN-02 | cancel 在**工具边界**生效 | ✅ | RUN-CANCEL-01<br>RUN-CLEANUP-01<br>RUN-LOG-01<br>RUN-TASKS-01<br>RUN-SIDEBAR-01… | — |
| F-RUN-03 | steer 入口在界面可见 | ✅ | RUN-LOOP-01<br>RUN-LOOP-02 | P3-03 |
| F-RUN-04 | steer 在工具边界注入下一轮 | ✅ | RUN-LOOP-01<br>RUN-LOOP-02 | P3-03 |
| F-RUN-05 | 阻塞命令期间如实提示生效时机 | ✅ | RUN-LOOP-01<br>RUN-LOOP-02 | P3-03 |
| F-RUN-06 | 多次 steer 顺序不丢不错配 | ✅ | RUN-LOOP-01<br>RUN-LOOP-02 | P3-03 |
| F-RUN-07 | 交互与调度共享并发预算 | ✅ | RUN-CONC-01<br>RUN-CONC-02 | P3-01 |
| F-RUN-08 | 可并行观察多个运行中任务 | ✅ | RUN-CANCEL-01<br>RUN-CLEANUP-01<br>RUN-LOG-01<br>RUN-TASKS-01<br>RUN-SIDEBAR-01… | — |
| F-RUN-09 | `run_events` 增加 `steer_injected` 等事件类型且不破坏既有语义 | ✅ | RUN-CANCEL-01<br>RUN-CLEANUP-01<br>RUN-LOG-01<br>RUN-TASKS-01<br>RUN-SIDEBAR-01… | — |
| F-CTX-01 | 工具按需装载：常驻工具目录 + `tool_search`/`tool_load` | ✅ | EXT-TOOL-01 | P2-02 |
| F-CTX-02 | 上下文有 token 预算（字符预算之外） | ✅ | CTX-TRIM-01<br>CTX-TRIM-02 | P3-05 |
| F-CTX-03 | 保留最近 N 轮原文，历史按需摘要 | ✅ | CTX-SUMMARY-01<br>CTX-DEAD-01<br>CTX-LRU-01<br>SSE-RECONNECT-01<br>SSE-DONE-01… | — |
| F-CTX-04 | 两级压缩（compact 70% / contextSummary 85%） | ✅ | CTX-SUMMARY-01 | P2-03 |
| F-CTX-05 | 压缩采用固定九段结构化模板 | ✅ | CTX-SUMMARY-01 | P2-03 |
| F-CTX-06 | 压缩器 0 工具权限 | ✅ | CTX-SUMMARY-01 | P2-03 |
| F-CTX-07 | 三层记忆（用户 / 工作区 / 项目） | ✅ | CTX-SUMMARY-01<br>CTX-DEAD-01<br>CTX-LRU-01<br>SSE-RECONNECT-01<br>SSE-DONE-01… | — |
| F-CTX-08 | 记忆预筛每次 ≤5 条 | ✅ | CTX-SUMMARY-01<br>CTX-DEAD-01<br>CTX-LRU-01<br>SSE-RECONNECT-01<br>SSE-DONE-01… | — |
| F-CTX-09 | 逐次 LLM 调用计量（token + 单价快照 + 成本） | ✅ | CTX-SUMMARY-01<br>CTX-DEAD-01<br>CTX-LRU-01<br>SSE-RECONNECT-01<br>SSE-DONE-01… | — |
| F-CTX-10 | 任务前后显示消耗区间与明细 | ✅ | CTX-SUMMARY-01<br>CTX-DEAD-01<br>CTX-LRU-01<br>SSE-RECONNECT-01<br>SSE-DONE-01… | — |
| F-EXT-01 | SKILL.md 规范（front matter + scripts/references/assets） | ✅ | EXT-SKILL-INDEX-01<br>EXT-SKILL-SPEC-01<br>EXT-SKILL-SPEC-02 | P2-05 |
| F-EXT-02 | 技能索引期只读 front matter | ✅ | EXT-SKILL-INDEX-01<br>EXT-SKILL-SPEC-01<br>EXT-SKILL-SPEC-02 | P2-05 |
| F-EXT-03 | 角色（专家）层：身份/边界/方法论/工具集/风格 | ✅ | EXT-ROLE-GONE-01<br>EXT-TEAM-01<br>EXT-TEAM-02 | P2-10 |
| F-EXT-04 | 专家团三种编排：parallel / sequential / review | ⏳ | EXT-ROLE-GONE-01<br>EXT-TEAM-01<br>EXT-TEAM-02 | P2-10 |
| F-EXT-05 | 插件包（技能+MCP+命令+Hooks+角色）原子安装 | ✅ | EXT-WR-03<br>EXT-TOOL-01<br>EXT-DR-SCORE-01<br>EXT-DR-FACTCHECK-01<br>EXT-DR-01… | — |
| F-EXT-06 | 插件包版本回滚 | ✅ | EXT-WR-03<br>EXT-TOOL-01<br>EXT-DR-SCORE-01<br>EXT-DR-FACTCHECK-01<br>EXT-DR-01… | — |
| F-EXT-07 | 技能安全扫描：脚本/网络/删除/敏感路径/凭据/混淆/体积 | ✅ | EXT-WR-03<br>EXT-TOOL-01<br>EXT-DR-SCORE-01<br>EXT-DR-FACTCHECK-01<br>EXT-DR-01… | — |
| F-EXT-08 | 技能工具调用受同一套权限规则约束 | ✅ | EXT-WR-03<br>EXT-TOOL-01<br>EXT-DR-SCORE-01<br>EXT-DR-FACTCHECK-01<br>EXT-DR-01… | — |
| F-EXT-09 | 多角色共享黑板 + 任务依赖图 | ⏳ | DESK-14<br>EXT-BOARD-01<br>EXT-DR-01<br>EXT-TEAM-GONE-01<br>EXT-TEAM-ORCH-01 | P2-09 |
| F-EXT-10 | 上下文收费站：子 Agent 原始推理不进主上下文 | ✅ | EXT-TOLLGATE-01<br>EXT-TOLLGATE-02 | P2-08 |
| F-EXT-11 | 通信通道：定向消息 + 通知 | ✅ | EXT-TOLLGATE-01<br>EXT-TOLLGATE-02 | P2-08 |
| F-EXT-12 | 模型按角色分档（轻/中/强），轻量角色 0 工具 | ✅ | EXT-WR-03<br>EXT-TOOL-01<br>EXT-DR-SCORE-01<br>EXT-DR-FACTCHECK-01<br>EXT-DR-01… | 02 |
| F-SCH-01 | 调度规则支持"每周多天合并"表达 | ✅ | SCH-RRULE-01<br>SCH-RRULE-04 | P2-16 |
| F-SCH-02 | 结果推送三通道（本地通知 / IM Bot / 移动端） | ✅ | SCH-DELIVERY-01<br>SCH-DELIVERY-02<br>SCH-IDEM-01<br>SCH-IDEM-02 | P3-02 |
| F-SCH-03 | 推送失败重试 3 次（指数退避），不影响任务状态 | ✅ | SCH-DELIVERY-01<br>SCH-DELIVERY-02<br>SCH-IDEM-01<br>SCH-IDEM-02 | P3-02 |
| F-SCH-04 | 后端通知**实装**（现状只有存储字段） | ✅ | SCH-DELIVERY-01<br>SCH-DELIVERY-02<br>SCH-IDEM-01<br>SCH-IDEM-02 | P3-02 |
| F-SCH-05 | MCP 支持 STDIO / SSE / HTTP | ✅ | EXT-MCP-POOL-01<br>EXT-MCP-POOL-02<br>OBS-METRIC-01 | P2-01 |
| F-SCH-06 | MCP 配置两级合并（用户级 + 项目级） | ✅ | EXT-MCP-POOL-01<br>EXT-MCP-POOL-02<br>OBS-METRIC-01 | P2-01 |
| F-SCH-07 | MCP 状态灯真实反映连接状态与失败原因 | ✅ | SCH-LEASE-01<br>SCH-01<br>SCH-14<br>OPS-CLASSIFY-01<br>OPS-MARKER-01… | — |
| F-SCH-08 | MCP 连接复用，不每次调用新建会话 | ✅ | EXT-MCP-POOL-01<br>EXT-MCP-POOL-02<br>OBS-METRIC-01 | P2-01 |
| F-SCH-09 | 错过触发的补偿语义明确（窗口内补跑、窗口外记 skipped） | ✅ | SCH-LEASE-01<br>SCH-01<br>SCH-14<br>OPS-CLASSIFY-01<br>OPS-MARKER-01… | — |
| F-SCH-10 | 结构化日志 + 请求 ID + 基础指标 | ✅ | SCH-LEASE-01<br>SCH-01<br>SCH-14<br>OPS-CLASSIFY-01<br>OPS-MARKER-01… | 04 |
| F-SCH-11 | 无人值守时 `ask` 降级为 deny 并记录 | ✅ | SCH-LEASE-01<br>SCH-01<br>SCH-14<br>OPS-CLASSIFY-01<br>OPS-MARKER-01… | — |
| F-UX-01 | 三栏工作台（左任务 / 中对话 / 右结果） | ✅ | UX-FIRSTTOKEN-01<br>UX-WSPICKER-01<br>DOM-04<br>DOM-08<br>DOM-01… | — |
| F-UX-02 | 结果区四视图（产物/文件/变更/浏览器） | ✅ | UX-FIRSTTOKEN-01<br>UX-WSPICKER-01<br>DOM-04<br>DOM-08<br>DOM-01… | 02 |
| F-UX-03 | 权限选择器统一为三态，与后端同源 | ✅ | UX-FIRSTTOKEN-01<br>UX-WSPICKER-01<br>DOM-04<br>DOM-08<br>DOM-01… | — |
| F-UX-04 | 权限审批卡（含影响预览与倒计时） | ✅ | UX-FIRSTTOKEN-01<br>UX-WSPICKER-01<br>DOM-04<br>DOM-08<br>DOM-01… | — |
| F-UX-05 | 每轮耗时三态展示 | ✅ | UX-FIRSTTOKEN-01<br>UX-WSPICKER-01<br>DOM-04<br>DOM-08<br>DOM-01… | — |
| F-UX-06 | 完成轮自动折叠并摘要 | ✅ | UX-FIRSTTOKEN-01<br>UX-WSPICKER-01<br>DOM-04<br>DOM-08<br>DOM-01… | — |
| F-UX-07 | 速记形态（`?compose=1`）只渲染输入区 | ✅ | UX-FIRSTTOKEN-01<br>UX-WSPICKER-01<br>DOM-04<br>DOM-08<br>DOM-01… | — |
| F-UX-08 | 在世交互补齐（托盘唤起、开机自启、Boss Key、后台静默） | ✅ | UX-FIRSTTOKEN-01<br>UX-WSPICKER-01<br>DOM-04<br>DOM-08<br>DOM-01… | — |
| F-UX-09 | 系统通知点击可跳转到对应运行 | ✅ | UX-FIRSTTOKEN-01<br>UX-WSPICKER-01<br>DOM-04<br>DOM-08<br>DOM-01… | — |
| F-UX-10 | "空间（Spaces）"不得为假数据 | ✅ | UX-FIRSTTOKEN-01<br>UX-WSPICKER-01<br>DOM-04<br>DOM-08<br>DOM-01… | — |
| F-UX-11 | 输入区常驻四控件：工作空间、权限、模式、模型 | ✅ | UX-FIRSTTOKEN-01<br>UX-WSPICKER-01<br>DOM-04<br>DOM-08<br>DOM-01… | — |
| F-UX-12 | 工作区选择器接入真实数据源 | ✅ | UX-FIRSTTOKEN-01<br>UX-WSPICKER-01<br>DOM-04<br>DOM-08<br>DOM-01… | — |
| F-UX-13 | 附件拖拽全页命中、上限 50、长文本折叠 | ✅ | UX-FIRSTTOKEN-01<br>UX-WSPICKER-01<br>DOM-04<br>DOM-08<br>DOM-01… | — |
| F-ENG-01 | 桌面打包资源目录不与 `.gitignore` 冲突 | ✅ | OPS-CLASSIFY-01<br>OPS-MARKER-01<br>OPS-DOCNUM-01<br>OPS-TRACE-01<br>API-UPLOAD-01… | — |
| F-ENG-02 | 补齐图标/安装脚本/签名文件，可产出安装包 | ⏳ | —（功能尚未交付） | 06 |
| F-ENG-03 | 启动页文件存在并纳入构建 | ✅ | OPS-CLASSIFY-01<br>OPS-MARKER-01<br>OPS-DOCNUM-01<br>OPS-TRACE-01<br>API-UPLOAD-01… | — |
| F-ENG-04 | 桌面事件桥贯通（后端 SSE → 壳 → 渲染） | ✅ | DESK-EVENT-01<br>code:tests/desktop/test_event_bridge.py | P5-11 |
| F-ENG-05 | 后端状态变化广播到渲染进程 | ✅ | OPS-CLASSIFY-01<br>OPS-MARKER-01<br>OPS-DOCNUM-01<br>OPS-TRACE-01<br>API-UPLOAD-01… | — |
| F-ENG-06 | 孤儿 sidecar 可被回收 | ✅ | DESK-ORPHAN-01 | P5-12 |
| F-ENG-07 | 桌面壳引入 vitest 并有单测 | ✅ | OPS-CLASSIFY-01<br>OPS-MARKER-01<br>OPS-DOCNUM-01<br>OPS-TRACE-01<br>API-UPLOAD-01… | — |
| F-ENG-08 | e2e 脚本跨平台可执行 | ✅ | OPS-CLASSIFY-01<br>OPS-MARKER-01<br>OPS-DOCNUM-01<br>OPS-TRACE-01<br>API-UPLOAD-01… | — |
| F-ENG-09 | 只存在一套 Agent 主循环 | ✅ | OPS-CLASSIFY-01<br>OPS-MARKER-01<br>OPS-DOCNUM-01<br>OPS-TRACE-01<br>API-UPLOAD-01… | — |
| F-ENG-10 | 配置只有一处真相，无 import 期快照、无全局可变配置 | ✅ | OPS-CLASSIFY-01<br>OPS-MARKER-01<br>OPS-DOCNUM-01<br>OPS-TRACE-01<br>API-UPLOAD-01… | — |
| F-ENG-11 | 全局异常处理 + 统一错误码 + 请求 ID | ✅ | OPS-CLASSIFY-01<br>OPS-MARKER-01<br>OPS-DOCNUM-01<br>OPS-TRACE-01<br>API-UPLOAD-01… | — |
| F-ENG-12 | 依赖清单单一真相并有锁文件 | ✅ | OPS-CLASSIFY-01<br>OPS-MARKER-01<br>OPS-DOCNUM-01<br>OPS-TRACE-01<br>API-UPLOAD-01… | — |
| F-ENG-13 | 基线数字与实测一致（含既有失败已修） | ✅ | code:tests/test_p5_batch.py | 05 |
| F-ENG-14 | 遗留无运行环境组件移出 `app/` | ✅ | OPS-CLASSIFY-01<br>OPS-MARKER-01<br>OPS-DOCNUM-01<br>OPS-TRACE-01<br>API-UPLOAD-01… | 05 |

**统计**：✅ 92 / ⏳ 3 / ⛔ 0（共 95 条）；已实现需求的用例覆盖率 100.0%（其中**条目级**（plan 推导链）30 条、**域级**（testing/00 用例族）62 条）。

