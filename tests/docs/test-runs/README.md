# 测试记录总索引

> **依据**：`doc/design/16-桌面一体化改造方案与实施计划.md` §1.3（D2 测试过程与结果必须记录）· §12.4 · §12.5
> **纪律**：本目录**只增不改**（§12.4.2 规则 8）；发现错记须新建 `correction.md` 说明。

---

## 索引

| 阶段 | 日期 | 范围 | 结论 | 报告 |
| --- | --- | --- | --- | --- |
| **P0-baseline** | 2026-11-01 | 改造前全量基线（pytest 695 · UI vitest 102 · 壳 vitest 60 · 冒烟 38 断言） | ✅ **通过**（692 pass / 3 skip / 0 fail） | [P0-baseline/README.md](P0-baseline/README.md) |
| **P9-final** | 2026-11-01 | 改造后全量回归（TS 后端 vitest **69** · UI vitest **102** · 壳 vitest **62** · 冒烟 **38/38** · 契约闸门 1~4） | ✅ **通过**（详见报告 §1） | [P9-final/README.md](P9-final/README.md) |
| **P9-final · 大模型端到端** | 2026-11-01 | Playwright 驱动**真实安装包**（模拟点击与输入 + 21 张截图） | ✅ **20/20**（实测发现并修复 9 个缺陷） | [P9-final/E2E-LLM-验收报告.md](P9-final/E2E-LLM-验收报告.md) |

---

## 目录结构约定（design §12.4.1）

```
tests/docs/test-runs/
├── README.md                          ← 本索引
├── <阶段>-<日期>/
│   ├── README.md                      ← 阶段报告（9 个小节齐全，§12.5）
│   ├── environment.json               ← OS / Node / Electron / commit / 数据快照
│   ├── commands.txt                   ← 逐条可复制执行的复现命令
│   ├── results.csv                    ← 逐用例结果（到「用例」这一级）
│   ├── feature-results.csv            ← 逐功能项 rollup
│   ├── diffs.csv                      ← 差异台账（等价 / 豁免 / 缺陷）
│   ├── raw/                           ← 原始输出（不截断、不加工）
│   └── screenshots/                   ← 视觉基线 / 对比图
```

---

## 功能基线判据

| 文件 | 作用 |
| --- | --- |
| `../../baseline/features.csv` | **唯一**的「功能一致」判据来源（185 项：126 API + 26 事件 + 19 UI 视图 + 14 非 HTTP 能力） |
| `../../contract/openapi.json` | L1 契约判据（98 路径 / 126 操作） |
| `../../contract/events.json` | L1 契约判据（26 事件 + 4 SSE 协议） |
| `../../contract/errors.json` | L1 契约判据（13 错误码 + HTTP 映射） |
| `../../contract/tables.sql` | L1 契约判据（22 表 DDL） |

---

## 差异三分类（design §12.3.2）

| 分类 | 定义 | 处置 | 允许数量 |
| --- | --- | --- | --- |
| **等价** | 形式不同但对外可感知行为一致 | 记录即可 | 不限 |
| **豁免** | 有意为之的差异（需理由 + 影响面 + 批准人 + 负责人 + 期限） | **人工逐条批准** | 每条五要素齐全 |
| **缺陷** | 功能缺失 / 行为错误 / 性能显著劣化 | **必须修复**并重跑 | **0** |

> **红线**：任何「能用但不一样」若影响用户可感知结果，一律归入**缺陷**，不允许塞进「等价」或「豁免」。
