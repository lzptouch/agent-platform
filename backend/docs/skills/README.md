# agent skill — 项目总索引

> **项目定位**：研究 Claude Code 风格的 Agent Skill 体系——把可复用的能力抽象成可发现、可触发、可观测的 Skill 文件夹。

## 项目结构

```
agent skill/
├── pdf/                 # PDF 处理 Skill（多文件 + LICENSE + forms.md + reference.md）
├── frontend-design/    # 前端设计 Skill（反 "AI slop" 美学）
├── ralph-loop/          # 自我循环改进 Skill
├── skill-creator/       # Skill 创建的元 Skill（最复杂）
└── local_skills_agent_上传.zip  # 项目原始 zip 备份
```

## 4 个 Skill 一句话总结

| Skill | 一句话定位 | 关键能力 |
|-------|-----------|----------|
| **pdf** | PDF 文本/表格/表单处理 | pypdf + pdfplumber + reportlab + OCR |
| **frontend-design** | 反"AI slop"前端美学 | 大胆风格 + 独特字体 + 集中动画 |
| **ralph-loop** | Agent 自我循环改进 | 执行→评估→差距→调整→再执行 |
| **skill-creator** | 创建新 Skill 的元 Skill | 测试用例 + 评估 + 迭代优化 |

## Skill 文档模板

每个 Skill 文件夹都遵循 Anthropic 官方规范：

```
skill-name/
├── SKILL.md       (required, YAML frontmatter + Markdown)
├── LICENSE.txt    (required)
├── references/    (optional, 高级 API 文档)
├── assets/         (optional, 模板/字体/图标)
└── scripts/        (optional, 可直接执行的脚本)
```

## 各 Skill 文档位置

| Skill | 文档 |
|-------|------|
| pdf | [`pdf/doc/README.md`](../pdf/doc/README.md) |
| frontend-design | [`frontend-design/doc/README.md`](../frontend-design/doc/README.md) |
| ralph-loop | [`ralph-loop/doc/README.md`](../ralph-loop/doc/README.md) |
| skill-creator | [`skill-creator/doc/README.md`](../skill-creator/doc/README.md) |

## 启动方式

每个 Skill 独立使用，无需安装额外依赖（除非 SKILL.md 中提到）。

```bash
# 例如使用 pdf skill
cp -r pdf ~/.claude/skills/pdf
# Claude Desktop 会自动发现

# 或作为提示词注入
cat pdf/SKILL.md
```

## 本章设计原理与依据

1. **核心思想**：Skill 是 Agent 的"知识外挂"。
   **本项目中体现**：把 PDF 处理 / 前端美学 / 自我循环 等专家知识沉淀为 Markdown 文件。
   **为什么有效**：Skill 比 fine-tuning 便宜、可热更新、人类可读可改。
   **佐证来源**：[官方] Anthropic Skills Documentation。

2. **核心思想**：Skill 设计应"目的 > 形式"。
   **本项目中体现**：SKILL.md 顶层必含 "When to use" / "核心原则"。
   **为什么有效**：让 LLM 准确理解触发场景，避免误用。
   **佐证来源**：[博客] Anthropic Skill Design Best Practices。

3. **核心思想**：Few-shot 示例是触发准确性的关键。
   **本项目中体现**：skill-creator 强调用测试用例作为示例文档。
   **为什么有效**：示例比规则更有效；隐含边界条件。
   **佐证来源**：[论文] Few-Shot Prompting (Brown et al., 2020)。

4. **核心思想**：渐进披露降低 token 消耗。
   **本项目中体现**：SKILL.md < 500 行，详细引用放 references/。
   **为什么有效**：description 决定触发，详细内容按需加载。
   **佐证来源**：[官方] Anthropic Skills Spec — Progressive Disclosure。

5. **核心思想**：Skill 元能力（创建 Skill）是体系自演进关键。
   **本项目中体现**：skill-creator 用同一 Skill 机制创建新 Skill。
   **为什么有效**：避免"鸡生蛋"问题；体系自我扩展。
   **佐证来源**：[论文] Meta-Learning (Thrun & Pratt, 1998)。

## 引用

- [官方] Anthropic Skills Documentation
- [官方] Claude Code Skills Spec
- [博客] Anthropic Skill Design Best Practices
- [论文] Few-Shot Prompting (Brown et al., 2020)
- [论文] Meta-Learning (Thrun & Pratt, 1998)
