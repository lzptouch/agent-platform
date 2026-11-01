# 根级 E2E 测试（desktop / packaged / visual）

> **改造要点（design/16 §11.10 · P8-04）**：旧 Python 后端（`backend/`）退场 →
> 本目录的 Playwright 骨架改用**独立 venv**（`.venv-e2e/`），只依赖
> `pytest` + `playwright`；Web / Docker 形态的用例（`web/` / `deploy/`）
> 随形态退场而**删除**；`native/`（测的是 Python 执行器内部）由
> `apps/server/tests/domain.test.ts` 的沙箱用例等价覆盖。

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
| `tests/desktop/` | `e2e` | 桌面**开发态**端到端（拉起壳 → 交互 → 断言） |
| `tests/packaged/` | `e2e` | **安装包**端到端（双击 → 建库 → 对话 → 退出） |
| `tests/visual/` | `e2e` | **视觉基线**（19 视图 diff < 2%） |
| `tests/common/` | — | 公共骨架（`harness.py` / `report.py` / `classify.py`） |

标记按**目录**自动打标（见 `tests/conftest.py`），保证「无未打标用例」。

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
python3 scripts/collect_test_report.py
# → tests/report/runs/<runId>-<commit>-<platform>-<arch>/
#    report.json / index.md / junit.xml / classify.json
```

汇总层定义见 `scripts/collect_test_report.py`：
`server-unit`（TS 后端 vitest）· `ui-unit` · `shell-unit` ·
`desktop-e2e` · `packaged-e2e` · `visual-layer`。

---

## [5] 相关文档

| 文档 | 内容 |
| --- | --- |
| `doc/testing/00-全面测试计划.md` | 分层策略与用例总表 |
| `doc/test-runs/P9-final/README.md` | 改造后全量回归报告 |
| `deploy/README.md` | 发布手册（含安装包实机验收清单） |
