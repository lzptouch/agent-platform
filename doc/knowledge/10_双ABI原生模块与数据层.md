# 双 ABI 原生模块与 SQLite 数据层

> **依据代码**：`apps/server/src/db/{native,client,migrate,baseline-sql}.ts`、`scripts/rebuild-native.mjs`（2026-11-01）
> **原理主题**：① Node 原生模块的 ABI 与「同一份安装、两种运行时」问题；
> ② better-sqlite3 的同步 API + WAL + 单写者模型。

---

## 一、ABI 问题：为什么一份 node_modules 不能通吃

Node 原生模块（`.node` 文件）是按 **`NODE_MODULE_VERSION`（ABI）**编译的：

| 运行时 | ABI |
|---|---|
| 系统 Node v22+（开发 / vitest / 冒烟） | **137** |
| Electron 33 内嵌 Node 20.18（打包态 sidecar） | **130** |

二进制只对编译时的 ABI 有效：Electron 里加载 Node 版的 `better_sqlite3.node`
会抛 `ERR_DLOPEN_FAILED`。本项目**同一个后端**要在这两种运行时里跑
（开发态用系统 Node，打包态被 `utilityProcess` 用 Electron 运行时拉起）。

## 二、本项目的解法：双 ABI 预建 + 显式加载

1. **构建期**：`scripts/rebuild-native.mjs` 对 better-sqlite3 分别构建两遍，
   产物复制到 `apps/server/.native/abi-<130|137>/better_sqlite3.node`；
2. **运行期**：`db/native.ts` 按 `process.versions.modules` 选出匹配当前运行时的
   二进制；
3. **加载**：用 better-sqlite3 v11 的 **`nativeBinding` 选项**显式传入已加载的 addon——
   完全绕开 `bindings` 包的路径猜测（否则 Electron 下会猜到 Node 版二进制）。

主库（`db/client.ts:42`）与向量库（`domain/rag/store.ts:204`）共用该加载器。
这是桌面一体化改造的关键坑位（design/16 R5）：不这么做，打包态一碰数据库就崩。

## 三、SQLite 运行参数（`db/client.ts:36-50`）

```ts
db.pragma("journal_mode = WAL");      // 写前日志：读不阻塞写
db.pragma("synchronous = NORMAL");    // WAL 下的稳妥档（FULL 更慢）
db.pragma("foreign_keys = ON");       // 外键约束必须显式开（SQLite 默认关！）
db.pragma("busy_timeout = 5000");     // 写锁等待 5s
```

- **WAL**：读（SSE tail、列表页）与写（事件落账）并发；代价是 `-wal/-shm`
  伴生文件（备份时要一起拷，`db/migrate.ts:65`）；
- **foreign_keys=ON**：SQLite 的历史包袱是默认关外键；不开则级联与约束静默失效；
- **busy_timeout**：单写者模型下的第一道吸收。

## 四、单写者与写锁退避

SQLite 同一时刻只有一个写事务。桌面的写尖峰来自：调度器 tick、Agent 事件
批量落账、权限决策写库同时发生 → `SQLITE_BUSY/LOCKED`。
本项目显式退避（`withWriteRetry()`，`client.ts:93`）：50 → 100 → 200ms 重试 3 次。

为什么敢用**忙等**：better-sqlite3 是同步 API，退避窗口（毫秒级）内阻塞
事件循环的影响可忽略；换来的是代码里**没有异步竞态**——`db.transaction(fn)()`
的原子性可以直接推理。

## 五、迁移策略：基线一次到位 + 旧库自动备份

- 不引第三方迁移 runner：自建 `__migrations(version, applied_at)`；
- 新库：`baseline-sql.ts` 一次建到最终态（22 表 + 约束 + 索引）；
- **旧库检测**（`migrate.ts:104`）：业务表存在但基线未标记 → 旧版遗留库 →
  先备份（`app.db.bak-<ts>`，含 WAL/SHM，保留最近 3 份）再标记基线；
- 判定的顺序陷阱：`hasSessions` 必须在创建 `__migrations` 表**之前**读取
  （否则空表误导判定）——这类「顺序即正确性」的点都写在代码注释里。

## 六、业界对照

| 方案 | 原生依赖 | 并发模型 | 本项目取舍 |
|---|---|---|---|
| better-sqlite3 | ✅ 一个 | 同步，单连接 | **采用**（桌面单机最优） |
| node:sqlite（Node 22 内置） | ❌ | 同步 | 实验期 API，Electron 内嵌版本不含 |
| sql.js（WASM） | ❌ | 全内存 + 落盘手动 | 持久化语义弱 |
| Postgres | 外部服务 | 完整 MVCC | 桌面安装包不可带服务 |

## 参考

- `../analysis/00` §7 R-02（better-sqlite3）、R-04（SQLite WAL）
- `../analysis/04`（数据模型事实）
- `../analysis/13` §九（为什么 sidecar 是 Electron 运行时）
