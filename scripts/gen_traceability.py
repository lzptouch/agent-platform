"""生成 doc/roadmap/11-需求-阶段-测试追溯矩阵.md（一次性工具，可重跑）。"""
from pathlib import Path
import io, re, collections

# **E9**：此前是 CWD 相对路径 → 换个目录跑即 FileNotFoundError。
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = str(REPO_ROOT / 'doc/design/01-功能需求规格.md')
OUT = 'doc/roadmap/11-需求-阶段-测试追溯矩阵.md'

T = {
'F-SEC-01': ('backend/tests/integration/test_permission_web_mode.py', 'Web 形态越界写被拦截并记决策'),
'F-SEC-02': ('backend/tests/integration/test_cors_and_bind.py', '未配置 CORS 拒绝跨域；默认绑定 127.0.0.1'),
'F-SEC-03': ('backend/tests/unit/test_permission_decide.py', '四类 scope 规则可创建、查询、启停'),
'F-SEC-04': ('backend/tests/unit/test_permission_decide.py', '同 pattern 不同工作空间可有不同裁决'),
'F-SEC-05': ('backend/tests/integration/test_permission_approval.py', '命中 ask 时动作不执行，审批卡弹出'),
'F-SEC-06': ('backend/tests/integration/test_permission_approval.py', '120s 无响应则动作被拒（decided_by=timeout）'),
'F-SEC-07': ('backend/tests/integration/test_audit_log.py', '决策日志含命中规则与人类可读原因'),
'F-SEC-08': ('backend/tests/unit/test_permission_normalize.py', '凭据路径与符号链接越界均被拒'),
'F-SEC-09': ('backend/tests/integration/test_policy_enforcement.py', 'rm -rf / 与串联命令逐段被拒'),
'F-SEC-10': ('backend/tests/integration/test_policy_enforcement.py', '禁止路径命中即 deny 且不询问'),
'F-SEC-11': ('backend/tests/integration/test_policy_enforcement.py', '工作区外写默认询问；区内常规读写零弹窗'),
'F-SEC-12': ('backend/tests/unit/test_sandbox_capability.py', '无沙箱时返回 policy_only 与替代说明'),
'F-SEC-13': ('backend/tests/integration/test_permission_approval.py', '过期后重新询问；会话级规则重启后消失'),
'F-SEC-14': ('backend/tests/integration/test_audit_log.py', '任一 run 的受控动作可按时间序还原'),
'F-SEC-15': ('backend/tests/integration/test_snapshot_and_changes.py', '修改前生成快照；超预算清理并写审计'),
'F-SEC-16': ('backend/tests/unit/test_sensitive_scan.py', '三种处置生效；密文参与上下文且输出可还原'),
'F-SEC-17': ('backend/tests/unit/test_permission_service_singleton.py', '单次工具调用不再新建服务与全表扫描'),
'F-WS-01': ('backend/tests/integration/test_workspace_api.py', '工作空间可创建/切换/归档'),
'F-WS-02': ('backend/tests/integration/test_run_workspace_lock.py', '运行中切换工作空间不影响当前 run'),
'F-WS-03': ('backend/tests/unit/test_workspace_manifest.py', '新任务自动得到独立工作目录'),
'F-WS-04': ('backend/tests/unit/test_workspace_manifest.py', 'manifest 可读可改且变更即生效'),
'F-WS-05': ('backend/tests/integration/test_snapshot_and_changes.py', '改 3 个文件则变更列表 3 条'),
'F-WS-06': ('backend/tests/unit/test_diff.py', '文本行级 diff；二进制给摘要'),
'F-WS-07': ('backend/tests/integration/test_change_revert.py', '回退后内容一致并出现 revert 记录'),
'F-WS-08': ('backend/tests/integration/test_artifacts.py', '产物视图只列交付物'),
'F-WS-09': ('apps/ui/src/components/ResultArtifacts.spec.ts', '另存到用户指定位置'),
'F-RUN-01': ('backend/tests/integration/test_run_cancel.py', '点停止后 run 变 interrupted 且不再调工具'),
'F-RUN-02': ('backend/tests/integration/test_run_cancel.py', '命令结束后终止；UI 显示正在停止'),
'F-RUN-03': ('apps/ui/src/views/workspace-interrupt.spec.ts', '运行中可输入追加指令'),
'F-RUN-04': ('backend/tests/integration/test_run_steer.py', '注入后下一轮 prompt 含该指令'),
'F-RUN-05': ('apps/ui/src/views/workspace-interrupt.spec.ts', '提示"将在当前命令结束后生效"'),
'F-RUN-06': ('backend/tests/integration/test_run_steer.py', '连发 3 条按序注入 3 轮'),
'F-RUN-07': ('backend/tests/integration/test_concurrency_budget.py', 'SSE 与调度共享信号量'),
'F-RUN-08': ('backend/tests/integration/test_runs_status_filter.py', '/runs/active 返回运行中任务与进度'),
'F-RUN-09': ('backend/tests/integration/test_run_steer.py', 'steer_injected 可回放且旧解析器不报错'),
'F-CTX-01': ('backend/tests/unit/test_tool_catalog.py', '首轮上下文不含全部工具 Schema'),
'F-CTX-02': ('backend/tests/unit/test_context_budget.py', '超预算触发裁剪'),
'F-CTX-03': ('backend/tests/unit/test_context_budget.py', '摘要后仍能回答"刚才为什么那样做"'),
'F-CTX-04': ('backend/tests/unit/test_compression.py', '超阈值自动压缩并落事件'),
'F-CTX-05': ('backend/tests/unit/test_compression.py', '压缩结果含九段且可展开查看'),
'F-CTX-06': ('backend/tests/unit/test_context_roles.py', '压缩角色工具集为空'),
'F-CTX-07': ('backend/tests/integration/test_memory_index.py', '记忆有作用域与索引表'),
'F-CTX-08': ('backend/tests/unit/test_memory_selector.py', '单次注入记忆文件数 ≤5'),
'F-CTX-09': ('backend/tests/integration/test_llm_call_accounting.py', 'llm_calls 可加总核对；历史金额不随单价变'),
'F-CTX-10': ('apps/ui/src/components/RunCostBar.spec.ts', '发起前显示区间，完成后显示实际'),
'F-EXT-01': ('backend/tests/unit/test_skill_spec.py', 'SKILL.md 可校验、可导入、可导出'),
'F-EXT-02': ('backend/tests/unit/test_skill_spec.py', '索引体积远小于正文；命中才读全文'),
'F-EXT-03': ('backend/tests/integration/test_roles_api.py', '角色 CRUD；工具集按最小权限声明'),
'F-EXT-04': ('backend/tests/unit/test_orchestrator.py', '三种编排均可产出汇总'),
'F-EXT-05': ('backend/tests/integration/test_plugin_install.py', '安装失败完整回滚到原版本'),
'F-EXT-06': ('backend/tests/integration/test_plugin_install.py', '可回滚到上一版本并记录'),
'F-EXT-07': ('backend/tests/unit/test_scanner.py', '扫描结果可查；high/critical 默认拒装'),
'F-EXT-08': ('backend/tests/integration/test_permission_skill.py', '技能不能绕过权限'),
'F-EXT-09': ('backend/tests/unit/test_blackboard.py', '依赖未完成的项不启动'),
'F-EXT-10': ('backend/tests/integration/test_context_tollgate.py', '主上下文只含压缩通知'),
'F-EXT-11': ('backend/tests/unit/test_blackboard.py', '两种通道可区分，通知带结构化引用'),
'F-EXT-12': ('backend/tests/unit/test_role_model_tier.py', '角色定义含模型档；调用档位符合'),
'F-SCH-01': ('backend/tests/unit/test_rrule.py', '"每周一三五 09:00"为一条规则、三个槽位'),
'F-SCH-02': ('backend/tests/integration/test_scheduler_delivery.py', '推送含任务名、状态、耗时、摘要、产物链接'),
'F-SCH-03': ('backend/tests/integration/test_scheduler_delivery.py', '推送失败落事件，任务仍为 success'),
'F-SCH-04': ('backend/tests/integration/test_scheduler_delivery.py', 'notify_on_run 打开后真的会通知'),
'F-SCH-05': ('backend/tests/unit/test_mcp_transport.py', '三种传输均可列出并调用工具'),
'F-SCH-06': ('backend/tests/unit/test_mcp_config_merge.py', '项目级覆盖用户级'),
'F-SCH-07': ('backend/tests/unit/test_mcp_config_merge.py', '断开时显示红色与可读原因'),
'F-SCH-08': ('backend/tests/unit/test_mcp_transport.py', '连续调用复用同一会话'),
'F-SCH-09': ('backend/tests/integration/test_scheduler_rescue.py', '休眠唤醒后补偿行为符合定义'),
'F-SCH-10': ('backend/tests/unit/test_structured_logging.py', '可按 request_id/run_id 检索；/metrics 可用'),
'F-SCH-11': ('backend/tests/integration/test_unattended_policy.py', '定时任务不因等待审批而挂起'),
'F-UX-01': ('apps/ui/src/layouts/WorkspaceLayout.spec.ts', '截图断言三区可见且可折叠'),
'F-UX-02': ('apps/ui/src/components/ResultPanel.spec.ts', '四个 Tab 均可切换且有数据源'),
'F-UX-03': ('apps/ui/src/components/ContextBar.spec.ts', '工作台与设置页显示一致'),
'F-UX-04': ('apps/ui/src/components/PermissionCard.spec.ts', '审批流 e2e 通过'),
'F-UX-05': ('apps/ui/src/components/ChatMessage.spec.ts', '三段时间可见并定格'),
'F-UX-06': ('apps/ui/src/components/ChatMessage.spec.ts', '折叠后可展开，内容不丢'),
'F-UX-07': ('apps/ui/src/views/compose-mode.spec.ts', '速记窗只渲染输入区'),
'F-UX-08': ('apps/desktop/src/main/shortcuts.test.ts', '每项有设置入口与验收步骤'),
'F-UX-09': ('apps/desktop/src/main/notifications.test.ts', '通知点击聚焦窗口并定位任务'),
'F-UX-10': ('apps/ui/src/stores/workspace.spec.ts', '不再有 localStorage 假数据'),
'F-UX-11': ('apps/ui/src/components/ContextBar.spec.ts', '四控件齐备且位置固定'),
'F-UX-12': ('apps/ui/src/components/WorkspacePicker.spec.ts', '可选择并绑定到新任务'),
'F-UX-13': ('apps/ui/src/components/ComposerInput.spec.ts', '附件上限与长文本折叠有明确反馈'),
'F-ENG-01': ('backend/tests/integration/test_packaging_prereq.py', 'git check-ignore 对 apps/desktop/resources 无命中'),
'F-ENG-02': ('backend/tests/integration/test_packaging_prereq.py', 'npm run dist:win 成功'),
'F-ENG-03': ('apps/desktop/src/main/window.test.ts', '启动页加载成功'),
'F-ENG-04': ('apps/desktop/src/main/backend-event.test.ts', 'e2e 断言事件到达渲染进程'),
'F-ENG-05': ('apps/desktop/src/main/state.test.ts', 'sidecar 崩溃时 UI 显示降级态'),
'F-ENG-06': ('apps/desktop/src/main/runstate.test.ts', '强杀后重启能回收并记录'),
'F-ENG-07': ('apps/desktop/package.json#test', '用例 ≥15 且全绿'),
'F-ENG-08': ('scripts/ui/ui_probe/test_crossplatform.py', 'Windows/Linux 均可执行'),
'F-ENG-09': ('backend/tests/unit/test_single_main_loop.py', '主循环入口唯一；/agent/chat 写账本'),
'F-ENG-10': ('backend/tests/unit/test_config_single_source.py', '无 import 期快照、无全局可变配置'),
'F-ENG-11': ('backend/tests/unit/test_errors.py', '错误响应含 code/message/request_id'),
'F-ENG-12': ('backend/tests/integration/test_deps_sync.py', '依赖集合一致；uv.lock 入库'),
'F-ENG-13': ('scripts/checks/test_doc_numbers.py', '文档计数与 CI 输出一致'),
'F-ENG-14': ('backend/tests/unit/test_package_hygiene.py', '主包无无运行环境组件'),
}

rows = re.findall(r'^\| (F-[A-Z]{2,3}-\d\d) \|(.*?)\|(.*?)\|(.*?)\|(.*?)\|(.*?)\|$',
                   io.open(SRC, encoding='utf-8').read(), re.M)
lines = []
missing = []
for rid, req, acc, pri, stage, gap in rows:
    stage = stage.strip().replace('**', '')
    t = T.get(rid)
    if not t:
        missing.append(rid)
        t = ('—', '—')
    lines.append((rid, stage, t[0], t[1]))

cnt = collections.Counter(x[1] for x in lines)
head = """# 11 · 需求-阶段-测试追溯矩阵（Traceability Matrix）

> **依据**：`../design/01-功能需求规格.md`（95 条需求与阶段归属）、各阶段文件的测试计划（`01`~`09`）、`../design/09-差距矩阵与整改清单.md`（74 条差距）。
> **整理日期**：2026-10-26　**对应基线**：commit `c4dac22`
> **本篇作用**：**一条需求 → 一个阶段 → 一个测试文件 → 一条可执行断言**。任一需求都能回答"谁验它、怎么验"；任一测试文件都能反查"它保护哪条需求"。
> **生成方式**：需求与阶段取自 `../design/01`（自动解析），测试文件与验收要点按阶段测试计划登记；需求新增或阶段调整时**必须同步本表**（流程见 `00-执行总纲.md` §9）。

---

## 一、覆盖概览

| 阶段 | 需求数 | 测试文件（主） | 门槛 |
| --- | --- | --- | --- |
"""
thresholds = {'S0': 'L0+L1+L5；壳单测 ≥15', 'S1': 'L0~L3；契约检查', 'S2': 'L0~L4；判定单测 ≥20',
              'S3': 'L0~L4；快照/回退集成', 'S4': 'L0~L4；cancel/steer 集成', 'S5': 'L0~L4；50 轮上下文回归',
              'S6': 'L0~L4；插件/黑板/收费站', 'S7': 'L0~L4；既有调度 14 例必绿', 'S8': 'L0~L5；vitest ≥40'}
for p in ['S0', 'S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7', 'S8']:
    head += f"| {p} | {cnt.get(p, 0)} | 见下表 | {thresholds[p]} |\n"
head += f"| **合计** | **{sum(cnt.values())}** | | |\n\n"

head += """## 二、逐条追溯

| 需求 ID | 阶段 | 主要测试文件 | 验收要点 |
| --- | --- | --- | --- |
"""
body = ''
for rid, stage, tf, acc in lines:
    body += f"| {rid} | {stage} | `{tf}` | {acc} |\n"

tail = """
---

## 三、使用规则

1. **写测试前**：先在本表登记"需求 ID → 测试文件"，再写用例；未登记的测试视为孤儿用例（评审时删除或补登需求）。
2. **阶段验收时**：逐条核对本表该阶段的所有行——**每行都要有对应的测试文件存在且该用例通过**。
3. **需求变更时**：先改 `../design/01`（编号与阶段）→ 再改本表 → 再改阶段文件的测试计划；三处不一致即视为规格不自洽。
4. **缺口检测**：任一需求在本表没有测试文件（显示 `—`）即为**未覆盖需求**，不得进入阶段出口。

---

## 四、差距 → 需求映射说明

`../design/09` 的 76 条差距（`G-` 功能 42 / `A-` 架构 21 / `E-` 桌面壳 13）已在 `../design/01` 的"差距"列逐条指向需求编号；本表再把需求指向测试文件，形成**差距 → 需求 → 阶段 → 测试 → 代码**的完整链路。链路断点即为质量缺口。
"""
if missing:
    tail += f"\n> ⚠ 本次生成时发现未登记测试文件的需求：{', '.join(missing)}\n"
io.open(OUT, 'w', encoding='utf-8').write(head + body + tail)
print('written', OUT, 'rows', len(lines), 'missing', missing)
