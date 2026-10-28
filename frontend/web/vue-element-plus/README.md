# web/vue-element-plus · 默认前端

仓库中**唯一**的前端实现，也是默认前端：Vue 3 + TypeScript + Vite + Element Plus + Pinia + Vue Router。

| 层 | 目录 / 文件 |
|---|---|
| 入口 | `src/main.ts`、`index.html` |
| 路由 | `src/router/index.ts`（15 个视图 + 11 条旧路径重定向） |
| 状态 | `src/stores/{config,flags,session,workspace}.ts`（4 个 Pinia store） |
| API | `src/api/{client,endpoints,sse,types}.ts`（58 端点常量 + 自研 SSE 消费） |
| 视图 | `src/views/`（Workspace / Work / Chat / Capabilities / Teams / Skills / MCP / Schedules / Research / RAG / WebResearch / Files / SystemStatus / WRChat / Settings） |
| 组件 | `src/components/`（13 个：ChatMessage / MarkdownView / ProcessSteps / PlanCard / RunTimeline / ArtifactStrip / composer/*6 / layout/SideNav） |
| 布局 | `src/layouts/`（WorkspaceLayout / AdminLayout） |
| 样式 | `src/styles/tokens.css`（CSS 变量 + `prefers-color-scheme` 暗色） |

## 启动

```bash
npm install
npm run dev          # http://127.0.0.1:5185/ ，代理 /api → 127.0.0.1:18040
npm run build        # vue-tsc 类型检查 + vite build → dist/
npm run preview      # 预览构建产物
```

## 构建到 frontend/dist（供后端 / Nginx 托管）

```bash
# 从仓库根目录执行
node frontend/scripts/build-frontend.mjs
```

容器化部署由 `deploy/frontend/Dockerfile` 在镜像内完成同样的构建，无需本命令。

## 关键实现说明

| 关注点 | 实现 |
|---|---|
| SSE 事件去重 | `api/sse.ts` 按 `stage + timestamp` 去重（只用 `stage` 作 key 会丢事件） |
| 断流恢复 | `streamResearchWithReconnect()` 包裹 SSE，回查任务状态后重新订阅 |
| 任务切换 | `useResearchTask` 按 `taskId` 管理独立 `AbortController`，切任务不阻塞 |
| 取消能力 | 所有流式请求持有 `AbortController`，输入框提供「停止生成」 |
| 事件覆盖 | `ChatView.vue` 的 switch 覆盖全部 18 种 Agent SSE 事件（`plan`/`reflection_plan` 共用分支） |
| Markdown 渲染 | `markdown-it` + `highlight.js` + DOMPurify（`MarkdownView.vue`） |
| 暗色模式 | CSS 变量 + `prefers-color-scheme` |

## 后端接口同步清单

每次后端变更时按此表人工同步：

| 端点 / 字段 | 文件 |
|---|---|
| 58 个端点常量 | `src/api/endpoints.ts` |
| 18 个 Agent SSE 事件类型 | `src/api/types.ts`（17 个 TS 类型）、`src/api/sse.ts`、`src/views/{ChatView,WorkView,WorkspaceView}.vue` |
| 24 个 Research stage | `src/views/ResearchView.vue` 中的 `STAGE_LABEL` |
| Types | `src/api/types.ts` |

契约以项目文档集为准：[`../../../doc/analysis/05_HTTP接口总览.md`](../../../doc/analysis/05_HTTP接口总览.md)（HTTP 接口总览）、
[`../../../doc/analysis/06_前端架构与接口契约.md`](../../../doc/analysis/06_前端架构与接口契约.md)（前端契约与 SSE 消费）、
[`../../../doc/analysis/03_Agent执行引擎与事件协议.md`](../../../doc/analysis/03_Agent执行引擎与事件协议.md)（SSE 事件协议）。
设计 Token 的唯一事实源即 `src/styles/tokens.css` 本文件。
