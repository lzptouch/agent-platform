"""给 `doc/design/09-差距矩阵与整改清单.md` 的每条差距加「状态」列。

状态取值（依据：**当前代码 + 阶段执行记录 + 测试**）：
- `✅ 已实现` —— 代码有生效逻辑且有测试覆盖；
- `⏳ 部分` —— 有骨架但未闭环/未接线（写明缺口）；
- `⛔ 未实现` —— 明确未做（写明去处：plan 批次）。

用法：python doc/plan/_gate/mark_gap_status.py
"""
from __future__ import annotations

import io
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / "doc" / "design" / "09-差距矩阵与整改清单.md"

#: 逐条覆盖（阶段默认之外的例外；依据当前代码与执行记录）
OVERRIDE: dict[str, tuple[str, str]] = {
    # 阶段默认 ✅，但当前只是骨架
    "G-36": ("⏳ 部分", "三传输已实现（stdio/SSE/HTTP），但 SSE/HTTP 为协议映射骨架，真实 SSE 流需 SDK 服务端支持 → `../plan/05`"),
    "G-38": ("✅ 已实现", "S7 起连接复用（`_connection_pool`），不再每次新建子进程；STDIO 子进程可回收"),
    "G-39": ("⛔ 未实现", "托盘速记 / Boss Key / 通知跳转 / 开机自启未接通 → `../plan/02`"),
    "G-42": ("⏳ 部分", "`stores/rounds.ts` 折叠状态与单测已就绪，但**未接线到消息流**（无人调用）→ `../plan/02`"),
    "E-06": ("✅ 已实现", "S8 已诚实化：无签名证书与发布通道 → 明确不做自动更新，并删除误导注释；将来要做见 `../plan/06`"),
    "E-07": ("⛔ 未实现", "`?compose=1` 速记形态未实现 → `../plan/02`"),
}

#: 按阶段给出的默认状态与依据
BY_STAGE: dict[str, tuple[str, str]] = {
    "S0": ("✅ 已实现", "S0 交付（断链修复 + 基线归零 + 打包自检 9/9）"),
    "S1": ("✅ 已实现", "S1 交付（错误体 / 暴露面 / 权限全形态 / mode 统一 / 配置单源 / LLM 工厂 / 账本 / 前端清理）"),
    "S2": ("✅ 已实现", "S2 交付（判定引擎 + 阻塞审批 + 决策留痕 + 沙箱诚实化）"),
    "S3": ("✅ 已实现", "S3 交付（工作空间 / 写前快照 / 变更 / 回退 / 产物 / 敏感处置）"),
    "S4": ("✅ 已实现", "S4 交付（取消真中止 / steer 保序 / 并发预算 / 运行中查询）"),
    "S5": ("✅ 已实现", "S5 交付（工具目录 / 预算裁剪 / 九段压缩 / 三层记忆 / 计量单价）"),
    "S6": ("✅ 已实现", "S6 交付（技能规范 / 角色 / 插件扫描安装回滚 / 黑板 / 消息收费站 / 编排）"),
    "S7": ("✅ 已实现", "S7 交付（RRULE / 投递三通道 / 无人值守降级 / MCP 连接复用 / 结构化日志 / 指标）"),
    "S8": ("✅ 已实现", "S8 交付（三栏折叠持久化 / 耗时三态 / 更新通道诚实化 / 体积预算 / 路由兜底 / 统一侧栏）"),
}

ROW = re.compile(
    r"^\| ((?:G|A|E)-\d+) \| ([^|]+) \| ([^|]*) \| ([^|]*) \| ([^|]*?) \| ([^|]*?) \|\s*$",
    re.M,
)


def main() -> int:
    text = io.open(DOC, encoding="utf-8").read()
    if "「状态」列" in text:
        print("already marked, skip")
        return 0

    stats = {"✅ 已实现": 0, "⏳ 部分": 0, "⛔ 未实现": 0}

    def repl(m: re.Match[str]) -> str:
        code, gap, fact, target, stage, prio = (g.strip() for g in m.groups())
        if code in OVERRIDE:
            status, note = OVERRIDE[code]
        else:
            # 按阶段取第一个匹配的默认
            status, note = "✅ 已实现", ""
            for key in ("S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"):
                if key in stage:
                    status, note = BY_STAGE[key]
                    break
        stats[status] += 1
        return f"| {code} | {gap} | {fact} | {target} | {stage} | {prio} | **{status}** {note} |"

    new_text = ROW.sub(repl, text)
    # 表头补一列
    new_text = new_text.replace(
        "| # | 差距 | 当前事实（证据） | 目标形态 | 阶段 | 优先级 |",
        "| # | 差距 | 当前事实（证据） | 目标形态 | 阶段 | 优先级 | 状态（2026-10-28 按代码复核） |",
    )
    new_text = new_text.replace(
        "| # | 差距 | 当前事实 | 目标形态 | 阶段 | 优先级 |",
        "| # | 差距 | 当前事实 | 目标形态 | 阶段 | 优先级 | 状态（2026-10-28 按代码复核） |",
    )
    io.open(DOC, "w", encoding="utf-8").write(new_text)
    print("marked", sum(stats.values()), "gaps:", {k.encode("unicode_escape").decode(): v for k, v in stats.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
