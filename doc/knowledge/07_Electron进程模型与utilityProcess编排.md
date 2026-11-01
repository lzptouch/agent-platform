# Electron 进程模型与 utilityProcess 编排

> **依据代码**：`apps/desktop/src/main/`、`apps/desktop/src/shared/protocol.ts`、`apps/server/src/main.ts`、`apps/server/src/http/bootstrap.ts`（2026-11-01）
> **原理主题**：Electron 多进程模型；以 `utilityProcess` 承载 Node 后端 sidecar 的
> 编排模式（握手 / 探活 / 熔断 / 孤儿回收 / 引导守卫）。
>
> 事实层（每个机制的参数与代码位置）见 `../analysis/13_桌面壳与进程编排.md`；
> 本篇讲「为什么」。

---

## 一、Electron 的进程模型

| 进程 | 数量 | 运行环境 | 本项目角色 |
|---|---|---|---|
| 主进程（main） | 1 | Node + Electron API | 窗口/托盘/热键/更新/编排 sidecar |
| 渲染进程（renderer） | 每窗口 1 | Chromium（隔离） | Vue 3 应用（`apps/ui`） |
| utility 进程 | 任意 | **纯 Node**（Electron 内嵌运行时） | **TS 后端 sidecar** |

渲染进程默认无 Node 能力（`contextIsolation`），经 preload 的
`contextBridge` 白名单桥与主进程 IPC 通信——本项目的 IPC 全部登记在
`main/ipc.ts`，preload 不直接暴露 `ipcRenderer`。

## 二、为什么后端用 `utilityProcess.fork()` 而不是 `spawn node`

1. **零环境假设**：用户机器不必装 Node——utilityProcess 用的是 Electron
   内嵌的 Node 运行时，随安装包分发；
2. **生命周期托管**：`child.kill()` 即可结束，退出事件由主进程统一收到；
3. **崩溃隔离**：后端崩了不带走壳（反之亦然），壳负责重启；
4. 代价：ABI 是 Electron 的（`NODE_MODULE_VERSION 130`），与系统 Node（137）
   不同 → 原生模块要双 ABI（见 `10_双ABI原生模块与数据层.md`）。

## 三、握手协议：为什么是一行 stdout

后端就绪的充分信息（**OS 分配的端口**、数据目录、版本、pid）只有后端自己
绑完套接字才知道。`AGENT_DESKTOP_READY {json}` 一行 stdout 是最小自描述协议：

- **不依赖 Electron 消息通道的时序**（通道建立与后端就绪无因果关系）；
- **裸跑可观测**：开发态 `node main.js` 也打这行，测试/排错不需要 Electron；
- 凭据**不在**载荷里——令牌与 nonce 只走环境变量（`AGENT_DESKTOP_TOKEN` /
  `AGENT_DESKTOP_BOOTSTRAP_NONCE`）。

## 四、引导与守卫：nonce → Cookie 的三段式

桌面后端的威胁模型是「**本机其他进程/网页**」而非公网：

1. **一次性 nonce 引导**：`/​__desktop/bootstrap?t=<nonce>` 校验通过即作废
   （防重放），换 HttpOnly + SameSite=Strict 的会话 Cookie；
2. **常驻令牌走 Header**（`X-Agent-Desktop-Token`）：壳的 Node 侧请求用，
   **永不出现在 URL**（URL 会进历史/日志/跳转）；
3. **Host 白名单**：只接受 `127.0.0.1`/`localhost` 且端口==本进程端口——
   防 **DNS rebinding**（恶意网页把域名解析到 127.0.0.1 后借浏览器发请求，
   Host 头是恶意域名 + 端口 → 421）；
4. Cookie 值是**独立随机数**（不派生自令牌）→ Cookie 泄露不能反推令牌；
   比较一律常量时间（`crypto.timingSafeEqual`）。

## 五、监护：探活 / 重启 / 熔断

- **探活**：30s 一次 `GET /__desktop/ping`（带令牌）；连续 3 次失败判挂死；
- **重启退避**：1s → 2s → 4s；
- **熔断**：连续失败 3 次进入 `degraded`（不再重启，把控制权还给用户）；
- **关键设计：握手成功不复位熔断计数**——「起来→秒崩」循环每次握手都成功，
  一复位就无限重启；只有**持续健康 ≥60s**才算真稳住（`protocol.ts:21-27`）。

## 六、孤儿回收：为什么不能信 pid

应用被强杀（kill -9 / 断电）时 sidecar 可能残留。下次启动要回收它，但
**pid 会被操作系统复用**——直接 `kill(pid)` 可能误杀无关进程。
所以 `run-state.json` 不只记 pid，还记 **started_at 与解释器全路径**：
回收前读进程命令行，含 sidecar 入口 `main.js` 或记录的 exe 才动手
（`backend.ts:582`）；确认不了归属就**放弃并保留记录**（下次再试）。
删除 run-state 只发生在「确认进程已退出」或「应用正常退出」之后。

## 七、电源与补跑

笔记本合盖休眠期间，定时任务全部错过。`powerMonitor`：
挂起 → 状态置 `degraded`（防止探活把「休眠」误判为「挂死」）；
唤醒 → 重新探活 + 调 `/desktop/scheduler/resume-scan` 补跑窗口内错过的任务
（默认 6h）——补跑的幂等由调度槽位唯一约束兜底（`../analysis/08` §4）。

## 八、业界对照

| 产品形态 | 后端承载 |
|---|---|
| VS Code 扩展宿主 | extension host 进程（Node） |
| 各类「Electron + Python sidecar」应用 | `spawn` 打包的解释器 |
| 本项目 | `utilityProcess.fork`（Electron 内嵌 Node，免打包解释器） |

## 参考

- `../analysis/00` §7 R-18（Electron 官方文档）
- `../analysis/13`（机制与参数的事实清单）
- `../design/03`（壳与后端进程编排设计）
