/**
 * 启动 TS 后端，逐个 GET 端点打一遍，**导出每个响应的顶层键**。
 *
 * 供 `scripts/check_python_parity.py` 与改造前（Python）的响应键做对比。
 * 静态解析源码不可靠（`return` 可能在 helper 里、或写成 `reply.send({...})`），
 * 因此这里**以运行时实际返回为准**。
 *
 * 用法：node --experimental-strip-types scripts/dump_response_keys.mjs <out.json>
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const OUT = process.argv[2] ?? "/tmp/ts-response-keys.json";
process.env.AGENT_DATA_DIR = path.join(os.tmpdir(), "agent-parity-probe");
process.env.AGENT_DESKTOP = "0";

const { buildApp } = await import("../apps/server/src/http/app.ts");
const { getDb } = await import("../apps/server/src/db/client.ts");
const { runMigrations } = await import("../apps/server/src/db/migrate.ts");

// 建库 + 迁移（不引 tests/setup.ts —— 它依赖 vitest 运行时）
getDb();
runMigrations();
const app = await buildApp();
await app.ready();

/** 契约里的全部 GET 路径（去掉参数段）。 */
const spec = JSON.parse(
  fs.readFileSync(path.join(import.meta.dirname, "..", "contract", "openapi.json"), "utf-8"),
);

const results = {};
/** SSE / 长轮询端点：`inject` 会一直挂着 → 跳过。 */
const SKIP = new Set(["/api/v1/desktop/events"]);
for (const p of Object.keys(spec.paths)) {
  if (!spec.paths[p].get) continue;
  if (SKIP.has(p)) continue;
  // 路径参数 → 用占位值（多数端点只校验存在性）
  const url = p.replace(/\{[^}]+\}/g, "probe-id");
  try {
    // 超时保护：某些端点可能很慢
    const res = await app.inject({
      method: "GET",
      url,
      signal: AbortSignal.timeout(8000),
    });
    let keys = [];
    try {
      const body = res.json();
      keys = body && typeof body === "object" && !Array.isArray(body) ? Object.keys(body) : [];
    } catch {
      keys = [];
    }
    results[`GET ${p}`] = { status: res.statusCode, keys, isArray: Array.isArray(res.json?.() ?? null) };
  } catch (err) {
    results[`GET ${p}`] = { status: -1, keys: [], error: String(err).slice(0, 120) };
  }
}

fs.writeFileSync(OUT, JSON.stringify(results, null, 2), "utf-8");
console.log(`已导出 ${Object.keys(results).length} 个端点的响应键 → ${OUT}`);
await app.close();
process.exit(0);
