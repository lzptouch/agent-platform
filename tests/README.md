# tests/ —— 全部测试代码与文档（2026-11-02 起统一归拢）

> **归拢说明**：本目录是仓库**唯一的测试根目录**——各端 vitest 单测（`unit/`）、
> 根级 pytest E2E（`desktop/` `packaged/` `visual/`）、大模型端到端（`e2e/`）、
> 测试脚本（`scripts/`）、测试文档（`docs/`：testing/00 计划 · test-runs/ 证据链 ·
> traceability.md）与报告产出（`report/`）全部集中于此。
> `apps/*` 的 `npm test` 通过各自 `vitest.config.ts` 指向 `tests/unit/`。
>
> **改造要点（design/16 §11.10 · P8-04）**：旧 Python 后端（`backend/`）退场 →
> 本目录的 Playwright 骨架改用**独立 venv**（`.venv-e2e/`），只依赖
> `pytest` + `playwright`；Web / Docker 形态的用例（`web/` / `deploy/`）
> 随形态退场而**删除**；`native/`（测的是 Python 执行器内部）由
> `tests/unit/server/domain.test.ts` 的沙箱用例等价覆盖。

---

| 项 | 说明 |
| --- | --- |
| 被测对象 | **桌面形态**：Agent Desktop（Electron 壳 + 内嵌 TypeScript 后端 sidecar） |
| 测试框架 | Playwright（Python，**独立 venv** `.venv-e2e/`）+ pytest；壳与后端另有 vitest 单测 |
| 浏览器 | Chromium（`python -m playwright install chromium`） |
| 运行依赖 | ① `apps/server` / `apps/ui` / `apps/desktop` 依赖已安装；② `apps/ui/dist` 存在（后端托管 SPA）；③ 桌面运行时用例另需 Electron 运行时与已构建壳 |
| 数据隔离 | 所有测试数据写入独立临时目录与独立 SQLite；用例外壳脚本只读仓库内文件 |
| 产出目录 | `tests/report/`（截图、trace、Markdown 报告；已 gitignore） |

---

## [1] 前置依赖自检

```bash
# Playwright 与浏览器（独立 venv）
python3 -m venv .venv-e2e
.venv-e2e/bin/python -m pip install --upgrade pip
.venv-e2e/bin/python -m pip install pytest playwright pytest-timeout
.venv-e2e/bin/python -m playwright install chromium

# Electron 运行时（桌面运行时用例需要）
ls apps/desktop/node_modules/electron/dist/electron

# TS 后端与前端产物
cd apps/server && npm run build && cd ../..
cd apps/ui && npm run build && cd ../..
```

> **不再需要** `backend/.venv`：旧 Python 后端已退场。

---

## [2] 目录与层标记

| 目录 | 层标记 | 说明 |
| --- | --- | --- |
| `tests/unit/server/` | — | TS 后端 vitest（契约 + 数据层 + 领域语义；`cd apps/server && npm test`） |
| `tests/unit/desktop/` | — | Electron 壳 vitest（`cd apps/desktop && npm test`） |
| `tests/unit/ui/` | — | 前端 vitest（`cd apps/ui && npm test`） |
| `tests/desktop/` | `e2e` | 桌面**开发态**端到端（拉起壳 → 交互 → 断言） |
| `tests/packaged/` | `e2e` | **安装包**端到端（双击 → 建库 → 对话 → 退出） |
| `tests/visual/` | `e2e` | **视觉基线**（19 视图 diff < 2%） |
| `tests/e2e/` | — | 大模型端到端（Node + Playwright 驱动真实安装包） |
| `tests/scripts/` | — | 校验 / 验证脚本（`check_*` 门禁 · `verify_*` · `ui/smoke.mjs` · `ui/ui_probe/`） |
| `tests/docs/` | — | 测试文档（`testing/00` 计划 · `test-runs/` 证据链 · `traceability.md`） |
| `tests/report/` | — | 报告与截图产出（`runs/` `archive/` `shots/`；已 gitignore） |
| `tests/common/` | — | 公共骨架（`harness.py` / `report.py` / `classify.py`） |

标记按**目录**自动打标（见 `tests/conftest.py`），保证「无未打标用例」。

> **`tests/unit/{desktop,ui}/node_modules` 是两个已提交的软链**（→ `apps/desktop|ui/node_modules`）：
> 单测文件迁出 `apps/` 后，裸导入（`electron` / `pinia` / `@vue/test-utils` …）
> 与 `vi.mock("electron")` 需要从这里向上解析依赖。删除后重建：
> `ln -sfn ../../../apps/desktop/node_modules tests/unit/desktop/node_modules`
> （ui 同理）。Windows 检出需开启开发者模式才能创建软链。

---

## [3] 运行

```bash
# 全部
.venv-e2e/bin/python -m pytest tests -q

# 分目录
.venv-e2e/bin/python -m pytest tests/desktop -q
.venv-e2e/bin/python -m pytest tests/packaged -q
.venv-e2e/bin/python -m pytest tests/visual -q

# 按层标记
.venv-e2e/bin/python -m pytest tests -m e2e -q
```

---

## [4] 结果汇总

```bash
python3 tests/scripts/collect_test_report.py
# → tests/report/runs/<runId>-<commit>-<platform>-<arch>/
#    report.json / index.md / junit.xml / classify.json
```

汇总层定义见 `tests/scripts/collect_test_report.py`：
`server-unit`（TS 后端 vitest）· `ui-unit` · `shell-unit` ·
`desktop-e2e` · `packaged-e2e` · `visual-layer`。

---

## [5] 相关文档

| 文档 | 内容 |
| --- | --- |
| `tests/docs/testing/00-全面测试计划.md` | 分层策略与用例总表 |
| `tests/docs/test-runs/P9-final/README.md` | 改造后全量回归报告 |
| `deploy/README.md` | 发布手册（含安装包实机验收清单） |
