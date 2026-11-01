# Agent Skill — skill-creator

> **位置说明**：本目录是 `agent skill/` 项目的 4 个 Skill 之一（其他为 pdf、frontend-design、ralph-loop）。

## Skill 定位

`skill-creator/` 是创建新 Skill 的 Skill——"Skill 创建 Skill"，是 Skill 体系中的元能力。

**核心能力**：
- 理解用户意图 → 起草 Skill 文档
- 测试用例设计与运行
- 定量评估（pass rate）
- 自我迭代优化（reflection）
- 自动评估描述触发准确性（description optimization）

**Skill 文档结构**：
```
skill-name/
├── SKILL.md (required, < 500 lines)
├── LICENSE.txt
├── references/  # optional, advanced docs
├── assets/      # optional, templates/fonts
└── scripts/     # optional, deterministic tasks
```

## 文件清单
- `SKILL.md` — Skill 入口（核心方法论）
- `LICENSE.txt` — 许可
- `references/schemas.md` — JSON schemas
- `eval-viewer/` — 评估 UI 生成器
- `agents/` — grader / analyzer / comparator 子 agent

## 文档清单
- `00-README.md` — 索引（详细）

## 核心原理
1. **Skill 文档就是契约**：name + description 决定何时触发。
2. **Few-shot 示例**：测试用例作为示例文档。
3. **渐进披露**：SKILL.md < 500 行，详细引用放入 references/。
4. **description 优化**：评估触发准确率，反复改写 description。
5. **迭代循环**：起草 → 测试 → 评估 → 修改 → 重测。

## 引用
- [官方] Anthropic Skill Creator
- [博客] Skill Design Best Practices
