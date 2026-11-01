# Agent Skill — ralph-loop

> **位置说明**：本目录是 `agent skill/` 项目的 4 个 Skill 之一（其他为 pdf、frontend-design、skill-creator）。

## Skill 定位

`ralph-loop/` 是 Agent 自我循环改进的 Skill：通过反复执行-评估-调整循环，让 Agent 在多次迭代中逐步优化输出。

**核心思想**：
- 执行一次 → 评估质量 → 找出差距 → 自动调整 → 再执行
- 类似 RLHF 的"自对弈"思路但更轻量
- 适合 prompt engineering、代码生成、文本润色

**技术组件**：
- 执行器（run_agent / run_code）
- 评估器（eval_output）
- 差距分析器（identify_gaps）
- 调整器（refine_input）

## 文件清单
- `SKILL.md` — Skill 入口

## 文档清单
- `00-README.md` — 索引（详细）

## 核心原理
1. **ReAct 风格循环**：每轮 Thought → Action → Observation → Evaluation。
2. **质量阈值控制**：score >= threshold 才停止。
3. **历史轨迹保留**：每轮结果累积，便于事后复盘。
4. **自适应参数**：根据反馈调整 temperature / max_tokens。
5. **早停保护**：max_iterations 防止无限循环。

## 引用
- [博客] Anthropic Skill Design
- [论文] ReAct — Yao et al.
