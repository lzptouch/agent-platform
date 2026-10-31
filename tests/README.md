# 端到端测试套件（Web + 桌面端）

> 依据：AI Agent 自动化测试统一提示词模板（已转录进 [`../doc/testing/00-全面测试计划.md`](../doc/testing/00-全面测试计划.md)）**全局头部固定规则** + **模块 A（Web / Playwright）** + **模块 C（桌面端 / Electron）** + **附加专项：稳定性、录屏**。
> 剩余工作与批次见 [`../doc/plan/`](../doc/plan/README.md)；分层与门禁见 [`../doc/design/10-测试与验收策略.md`](../doc/design/10-测试与验收策略.md)；可执行测试计划见 [`../doc/testing/00-全面测试计划.md`](../doc/testing/00-全面测试计划.md)。
> 整理日期：2026-10-26　最近更新：2026-10-28（批次 01 交付）　对应基线：commit `c4dac22`

---

## 一、测试概要与前置依赖清单

| 项 | 说明 |
| --- | --- |
| 被测对象 | agent-platform：**Web 形态**（Vue3 + Element Plus）+ **桌面形态**（Agent Desktop，Electron 壳 + FastAPI sidecar） |
| 测试框架 | Playwright（Python，`backend/.venv` 内已安装）+ pytest；桌面壳另有 vitest 单测 |
| 浏览器 | Chromium（已安装于 `%LOCALAPPDATA%\ms-playwright`） |
| 运行依赖 | ① 后端可启动（`backend/.venv` 依赖齐全）；② `frontend/dist` 存在（后端托管 SPA）；③ 桌面运行时用例另需 Electron 运行时与已构建壳 |
| 数据隔离 | 所有测试数据写入独立临时目录与独立 SQLite；用例外壳脚本只读仓库内文件 |
| 产出目录 | `tests/report/`（截图、trace、Markdown 报告；已 gitignore） |
| 上传上限 | e2e 环境把单文件上限调到 **1MB**、单请求上限 **2MB**（`UPLOAD_MAX_FILE_BYTES` / `UPLOAD_MAX_REQUEST_BYTES`，见 `common/harness.py`），避免为验证 413 真传 50MB；**默认值 50MB / 100MB 由后端单测冻结** |

**前置依赖自检命令**

```bash
# 后端依赖与 pytest
cd backend && .venv/Scripts/python.exe -c "import fastapi, sqlalchemy, apscheduler, mcp; print('deps ok')"
# Playwright 与浏览器
backend/.venv/Scripts/python.exe -c "from playwright.sync_api import sync_playwright; print('pw ok')"
ls "$LOCALAPPDATA/ms-playwright"   # 应有 chromium-*
# Electron 运行时（桌面运行时用例需要）
ls frontend/desktop/node_modules/electron/dist/electron.exe
```

---

## 二、测试用例表

### 2.1 Web 形态（`tests/web/test_web_regression.py`）

| 编号 | 用例 | 层次 | 类型 | 覆盖点 |
| --- | --- | --- | --- | --- |
| WEB-01 | 健康检查可用且结构正确 | 接口 | 正向 | `/api/v1/health` 真实字段（不再硬编码 MCP 数） |
| WEB-02 | 未知资源返回 404/422 | 接口 | 反向 | 错误路径处理 |
| WEB-03 | 会话创建/回读/改名/删除 + 非法 mode 被拒 | 接口 | 正向+反向+边界 | `SessionCreate/Update` 契约；删除后 404 |
| WEB-04 | 技能资源路径穿越被拦截 | 接口 | 安全 | `../../core/config.py` 不得泄露 |
| WEB-05 | 权限规则可读；非法 decision 返回 422 | 接口 | 正向+反向 | 三态权限契约 |
| WEB-06 | 非法 cron 表达式校验为不通过 | 接口 | 边界+反向 | 调度入参校验 |
| WEB-07 | 同名定时任务重复提交有明确处置；work 模式未显式确认 `allow_unattended_tools` 被拒 | 接口 | 重复提交+安全 | 幂等与无人值守安全约束 |
| WEB-08 | 文件上传/下载/删除闭环 | 接口 | 正向 | 文件链路 + 数据隔离 |
| WEB-10 | 首页渲染出主工作台 | UI | 正向 | SPA 可用、元素可识别 |
| WEB-11 | 工作模式入口可见 | UI | 正向 | 三态模式入口 |
| WEB-12 | 对话入口可用（流式回复或可读错误） | UI | 正向+异常 | 对话主流程；无模型时须有可读错误而非白屏 |
| WEB-13 | 接口不可达时页面仍有内容（不白屏） | UI | 弱网/断网 | `route.abort()` 注入 |
| WEB-14 | 超长文本与特殊字符输入不崩溃 | UI | 边界 | 5000 字符 + XSS 形态载荷（仅功能校验） |
| WEB-15 | 接口返回条数与 UI 入口一致 | 接口+UI | 一致性 | 接口与渲染同源校验 |
| WEB-31 | 超大文件上传返回 413 + 统一错误体，且不留半成品 | 接口 | 边界 | 批次 01 / WP-2 单文件大小上限（e2e 环境上限 1MB） |
| WEB-32 | 可执行文件 / 白名单外类型上传被拒且未落盘 | 接口 | 反向+安全 | 批次 01 / WP-2 扩展名与 MIME 白名单 |
| WEB-33 | 速记形态只渲染输入区（无侧栏 / 无对话流） | UI | 正向 | 批次 02 `?compose=1` |
| WEB-34 | 附件超 50 个给出可读提示且不发上传请求 | UI | 边界 | 批次 02 附件上限 |

### 2.2 桌面形态（`tests/desktop/test_desktop_regression.py`）

| 编号 | 用例 | 层次 | 类型 | 覆盖点 |
| --- | --- | --- | --- | --- |
| DESK-01 | 打包资源齐备且配置指向 `resources/` | 静态 | 正向 | 曾因 `.gitignore` 的 `build/` 规则被屏蔽 |
| DESK-02 | 忽略规则已并入被跟踪的根 `.gitignore` | 静态 | 正向 | 新克隆也不会误提交安装包 |
| DESK-03 | 壳单测与类型检查通过 | 静态 | 正向 | 桌面端此前零测试 |
| DESK-04 | 事件桥契约：发送方与接收方均存在 | 静态 | 正向 | `agent:backend-event` / `agent:backend-state` |
| DESK-05 | `run-state` 写入/清理与孤儿回收入口齐备 | 静态 | 正向 | 孤儿 sidecar 回收 |
| DESK-10 | 应用启动并完成握手 | 运行时 | 正向 | Electron 启动 + 后端握手 |
| DESK-11 | sidecar 运行态被记录 | 运行时 | 正向 | 孤儿回收的数据来源 |
| DESK-12 | 退出后 `run-state` 被清理 | 运行时 | 正向 | 不残留孤儿记录 |
| DESK-13 | 在世交互静态契约齐备 | 静态 | 正向 | 速记窗 compose 形态 / Boss Key / 通知跳转 / preload 通道 |

> DESK-10/11 依赖 Electron 运行时；缺失时按 **环境问题** 跳过并如实标注，不计为通过。

---

## 三、可运行自动化脚本

| 脚本 | 作用 |
| --- | --- |
| `common/harness.py` | 后端进程编排（自绑端口 + 显式就绪等待）、截图、trace 落盘、缺陷分类（业务 Bug / 脚本问题 / 环境问题）与 Markdown 报告生成 |
| `web/test_web_regression.py` | Web 端 34 条用例（模块 A2 + 稳定性专项） |
| `desktop/test_desktop_regression.py` | 桌面端 10 条用例（模块 C2；运行时用例缺 Electron 时按环境问题跳过） |

**运行方式**

```bash
# 全量套件（Web + 桌面）
backend/.venv/Scripts/python.exe -m pytest tests -q

# 仅 Web
backend/.venv/Scripts/python.exe -m pytest tests/web -q

# 仅桌面
backend/.venv/Scripts/python.exe -m pytest tests/desktop -q

# 其它层（回归基线）
cd backend && .venv/Scripts/python.exe -m pytest tests/ -q     # 单元 + 集成
cd frontend/desktop && npm test                                # 壳单测
cd frontend/web/vue-element-plus && npm test                    # 前端单测
```

**约定（继承全局头部固定规则）**
1. 定位优先 `role` / 文本 / 稳定属性；不写硬编码 XPath 与像素坐标；
2. 等待用显式条件（`wait_for_load_state` / `wait_for_timeout` 兜底），不堆 sleep；
3. 关键步骤与失败必截图；失败自动保存 trace（`tests/report/web-trace.zip`）；
4. 用例数据隔离；只写独立测试目录；
5. 脚本可独立运行，依赖与前置条件见本篇第一节。

---

## 四、Markdown 测试报告模板

每次运行自动生成 `tests/report/report-<套件>-<时间戳>.md`，结构固定：

```markdown
# 测试报告 · <套件>

> 被测对象 / 生成时间 / 报告格式

## 一、测试概要
| 指标 | 值 |     # 用例总数 / 成功 / 失败 / 跳过 / 三类缺陷计数

## 二、测试用例表
| 编号 | 用例 | 层次 | 结果 | 分类 | 级别 | 说明 | 证据 |

## 三、脚本与运行方式
## 四、缺陷清单      # 仅 FAIL 用例，附证据路径
## 五、备注          # 本轮范围、遗留项、下一阶段需补充的断言
```

---

## 五、附加专项

| 专项 | 本轮落地情况 |
| --- | --- |
| 稳定性 | 已落地：后端启动显式就绪等待；Playwright 默认 15s 超时；后端健康探活由应用自身负责 |
| 录屏 | 已落地：失败自动保存 trace（Playwright tracing，截图+快照） |
| 性能埋点 | 部分落地：报告记录用例耗时字段；页面加载/接口耗时的完整埋点随 S7 可观测能力接入 |
| 混沌 | 部分落地：WEB-13 注入接口不可达；随机延迟与误点击待 S8 之后补充 |

---

## 六、本轮结果（2026-10-28 · 批次 01~03 交付后）

| 套件 | 用例 | 通过 | 失败 | 跳过（环境） |
| --- | --- | --- | --- | --- |
| Web 端 | 34 | 34 | 0 | 0 |
| 桌面端 | 10 | 10 | 0 | 0 |
| 后端 pytest | 366 | 366 | 0 | 0 |
| 桌面壳 vitest | 45 | 45 | 0 | 0 |
| 前端 vitest | 83 | 83 | 0 | 0 |

**本轮新增**：批次 01（执行边界与上传限制）——后端 `tests/test_boundaries.py` 21 例、
e2e WEB-31/32、前端 `upload-policy.spec.ts` 6 例；
批次 02（桌面在世交互与速记）——壳 `settings/shortcuts/tray/notifications` 4 个测试文件 18 例、
前端 `compose-mode/ComposerInput/RoundGroup` 13 例、e2e WEB-33/34 与 DESK-13；
批次 03（数据一致性与调度细节）——后端 `tests/test_s5_consistency.py` 19 例
（入库幂等 / 日志落盘 / `run_id` 对齐 / 时区配额 / 周期巡检 / 脚本幂等 / 危险工具开关 / 迁移链冒烟）。

**遗留**：① 桌面运行时用例需先 `cd frontend/desktop && npm run build` 并下载 Electron 运行时；
② S1 起补统一错误体断言（`code`/`message`/`request_id`）；③ 契约检查（`npm run test:contract`）需纳入 CI 门禁；
④ 批次 01 的上传白名单不含 `.zip`（Skill 包走 `/skills/import` 独立端点）；
⑤ 批次 03 的 Milvus 侧（`insert_chunks` / `delete_by_doc_id`）未真机验证——本机无 `milvus_lite`，
幂等逻辑在台账与调用序列层面验证；
⑥ 批次 03 修掉了 e2e 骨架的**管道死锁**（后端 stdout 原先从不抽干，缓冲满会阻塞后端 → 接口大面积超时）。
