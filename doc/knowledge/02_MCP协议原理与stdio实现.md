# MCP 协议原理与 stdio 实现

> **依据代码**：`apps/server/src/mcp/{manager.ts,servers/*.ts}`、`apps/server/src/http/routes/mcp-servers.ts`、`apps/server/src/domain/tools/registry.ts`（2026-11-01 复核重写）
> **原理主题**：Model Context Protocol 的传输与工具反射模型；本项目「进程内内置
> Server + 外部 Server 配置管理」的混合形态。

---

## 一、MCP 协议原理（30 秒版）

MCP（Model Context Protocol，Anthropic 2024 开放规范）把「工具提供方」标准化为
**Server**，宿主（Host）通过 **Client** 与之通信：

- **传输层**：`stdio`（子进程 stdin/stdout 跑换行分隔的 JSON-RPC）/
  `sse` / `http`（网络 Server）；
- **握手**：`initialize` 交换协议版本与能力 → `notifications/initialized`；
- **工具反射**：`tools/list` 返回 `{name, description, inputSchema}`（JSON Schema）；
- **调用**：`tools/call` 带参数 → 返回内容块数组；
- 意义：**工具生态与宿主解耦**——任何 MCP Server 都能插进任何 MCP 宿主，
  宿主不需要为每个工具写适配代码。

## 二、本项目的实现形态

### 2.1 内置 Server：进程内对象（当前唯一可调用路径）

`mcp/servers/` 下 3 个内置 Server 是**进程内 TS 对象**
（`BuiltinMcpServer { name, tools, call() }`，`manager.ts:289`），
不经 stdio、不经 JSON-RPC：

| Server | 工具数 | 工具 |
|---|---|---|
| `search` | 2 | `web_search`（Serper）、`fetch_page`（抓正文） |
| `weather` | 1 | `get_weather`（NWS / 高德地理编码） |
| `xiaohongshu` | 7 | search / note_detail / user_profile / comments / publish / login_status / login |

**为什么进程内**：这三个是平台自有高频能力，进程内实现省掉每次调用的
进程握手与序列化开销，且随包内置、零配置（`02` §八 的权衡）。
工具 Schema 与 MCP 的 `tools/list` 形态完全一致（`ToolSchema` 就是
`{name, description, input_schema}`）——将来想拆出去做独立 stdio Server，
协议面无需改动。

### 2.2 外部 Server：配置与进程管理在位，协议腿未接线

- **两级配置**：`~/.agent/mcp.json`（全局）+ `<项目根>/mcp.json`（项目级，
  同名覆盖，`manager.ts:82`）；
- **生命周期**：`start()` spawn 子进程（`detached` 进程组）、`stop()` 杀整组
  （不留僵尸）；`closeAllSessions()` 进程退出时回收；
- **⚠️ 未接线**：`listToolsWithSchema()` 只认内置 Server（`manager.ts:167`），
  `callTool()` 对非内置返回「未连接或未实现」——即**没有发起 JSON-RPC 握手与
  tools/list**；`@modelcontextprotocol/sdk` 在 `package.json` 声明但全仓无 import。
  配置校验（缺 command/url 报错）与状态面（enabled/connected/tool_count）是真实的。

### 2.3 工具合并进 Agent（`domain/tools/registry.ts:266`）

```
mergeTools(mcpManager, { enableMcp, mcpServers, profile, ... })
  └─ 对每个启用的 Server：listToolsWithSchema()
       └─ 以 `mcp_<server>__<tool>` 命名空间并入工具清单
          （description 前缀 `[MCP:<server>]`，来源着色 source="mcp"）
```

- **命名空间**防重名：`mcp_search__web_search` 不会撞内置工具；
- chat 档案跳过非只读 Server（`read_only` 配置位）；
- 单 Server 失败只告警不阻塞（隔离性）。

### 2.4 管理 API（9 端点）

`GET /mcp_servers`（内置 + 配置合并视图）、`GET /config`（合并结果 + 来源路径 +
配置错误）、`POST /config/reload`、`POST /reload`（清工具缓存）、
`GET /{name}`、`POST /{name}/start|stop`、`GET /{name}/tools`、
`POST /{name}/call`（内置 Server 真实执行）。

## 三、原理：为什么是「两级配置 + 同名覆盖」

工具配置有两类来源：用户级（我常用地图/搜索，全项目通用）与项目级
（这个工作区专用的内部 Server）。**同名项目级覆盖全局**与 npm/tsconfig 的
层级习惯一致；合并发生在读取时（`loadConfig()`），两份文件保持各自可编辑。

## 四、原理：工具反射 vs 静态声明

MCP 的 `tools/list` 是**运行时反射**（Server 活着才能列出工具）；
本项目的内置 Server 是**静态反射**（工具 Schema 随代码注册，无需启动子进程）——
管理界面 `GET /mcp_servers/{name}/tools` 因此可以「不启动也可见」。
对外部 Server，静态反射不可行（必须握手），这正是协议腿缺位的实质影响：
外部 Server 的工具清单与调用当前不可用（`../analysis/02` §2.4）。

## 五、业界对照

| 宿主 | 传输 | 工具命名 |
|---|---|---|
| Claude Desktop | stdio（主要） | server 维度分组展示 |
| Cursor | stdio / sse | 前缀命名空间 |
| 本项目 | 进程内（内置）+ stdio/sse/http（配置面） | `mcp_<server>__<tool>` 扁平命名空间 |

## 参考

- `../analysis/00` §7 R-09（MCP 官方规范）
- `../analysis/02` §二（MCP 链事实与边界）
