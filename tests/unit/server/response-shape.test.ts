/**
 * **响应形状**契约测试（P8-02 实测发现的契约违规的固化）。
 *
 * 闸门 1 只校验「路径 + 方法是否注册」，**不校验响应形状** →
 * TS 后端把 `GET /teams` 实现成 `{items:[...]}`（契约要求**裸数组**）→
 * 前端 `teams.value = await teamsList()` 拿到**对象** → el-table 抛
 * `Me is not iterable`。
 *
 * 本测试**启动真实 Fastify 实例**，按 `contract/openapi.json` 声明的响应类型
 * 逐个断言实际返回的形状（数组 / 对象），并覆盖桌面态的关键字段。
 */
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { FastifyInstance } from "fastify";
import { buildApp } from "../../../apps/server/src/http/app.js";
import { ensureSchema } from "./setup.js";

const CONTRACT_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../contract",
);

interface Schema {
  type?: string;
  $ref?: string;
  properties?: Record<string, unknown>;
  items?: Schema;
  additionalProperties?: boolean;
}

let app: FastifyInstance;
let spec: {
  paths: Record<string, Record<string, { responses?: Record<string, unknown> }>>;
  components?: { schemas?: Record<string, Schema> };
};

function resolve(node: Schema | undefined): Schema | undefined {
  if (!node) return undefined;
  if (!node.$ref) return node;
  const name = node.$ref.split("/").pop() ?? "";
  return spec.components?.schemas?.[name];
}

/** 取某端点 200 响应的 schema。 */
function responseSchema(pathStr: string, method: string): Schema | undefined {
  const op = spec.paths[pathStr]?.[method.toLowerCase()];
  const raw = op?.responses?.["200"] as
    | { content?: Record<string, { schema?: Schema }> }
    | undefined;
  return resolve(raw?.content?.["application/json"]?.schema);
}

/** 契约声明为「裸数组」的端点（响应不是对象包装）。 */
function arrayEndpoints(): Array<{ path: string; method: string }> {
  const out: Array<{ path: string; method: string }> = [];
  for (const [p, item] of Object.entries(spec.paths)) {
    for (const [m, op] of Object.entries(item)) {
      if (!["get", "post", "put", "delete", "patch"].includes(m)) continue;
      if (responseSchema(p, m)?.type === "array") out.push({ path: p, method: m });
    }
  }
  return out;
}

beforeAll(async () => {
  ensureSchema();
  spec = JSON.parse(fs.readFileSync(path.join(CONTRACT_DIR, "openapi.json"), "utf-8"));
  app = await buildApp();
  await app.ready();
});

afterAll(async () => {
  await app?.close();
});

describe("响应形状 · 契约声明为裸数组的端点", () => {
  it("契约里确实存在数组型端点（否则本测试形同虚设）", () => {
    expect(arrayEndpoints().length).toBeGreaterThan(0);
  });

  it("每个数组型端点实际都返回**数组**（不是 {items:[...]}）", async () => {
    const eps = arrayEndpoints();
    const failures: string[] = [];
    for (const { path: p, method } of eps) {
      const res = await app.inject({ method: method as never, url: p });
      if (res.statusCode !== 200) {
        failures.push(`${method.toUpperCase()} ${p} → HTTP ${res.statusCode}`);
        continue;
      }
      const body = res.json();
      if (!Array.isArray(body)) {
        failures.push(
          `${method.toUpperCase()} ${p} → 返回 ${typeof body}（应为数组）`,
        );
      }
    }
    expect(failures.join("; ")).toBe("");
  });
});

describe("响应形状 · 桌面端关键字段", () => {
  it("GET /api/v1/desktop/status 含 runtime / components / security", async () => {
    const res = await app.inject({ method: "GET", url: "/api/v1/desktop/status" });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    // 前端 `desktop.status.runtime.python` → 缺 runtime 会抛 undefined 读取错误
    expect(body.runtime).toBeTruthy();
    expect(body.runtime).toHaveProperty("node");
    expect(body.runtime).toHaveProperty("executable");
    expect(body.components).toBeTruthy();
    expect(body.components).toHaveProperty("playwright_chromium");
    expect(body.security).toHaveProperty("auth_required");
    expect(body).toHaveProperty("mode");
    expect(body).toHaveProperty("protocol");
  });

  it("GET /api/v1/desktop/components 含 playwright_chromium.{installed,path,size_bytes}", async () => {
    const res = await app.inject({ method: "GET", url: "/api/v1/desktop/components" });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.playwright_chromium).toBeTruthy();
    expect(body.playwright_chromium).toHaveProperty("installed");
    expect(body.playwright_chromium).toHaveProperty("path");
    expect(body.playwright_chromium).toHaveProperty("size_bytes");
  });
});
