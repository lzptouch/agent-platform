/**
 * 领域服务语义测试（对应 Python 侧 `backend/tests/` 的核心断言）。
 *
 * 覆盖：会话 / 运行账本 / 权限引擎 / 工具注册表 / 调度器 / RAG 切块与 BM25 /
 * 沙箱边界 / 事件契约。
 */
import { describe, expect, it } from "vitest";
import { ensureSchema } from "./setup.js";
import { sessionService } from "../src/domain/session/service.js";
import { getDb } from "../src/db/client.js";
import { runService } from "../src/domain/run/service.js";
import {
  decide,
  BUILTIN_RULES,
  READONLY_TOOLS,
  DANGEROUS_TOOLS,
  type Rule,
} from "../src/domain/security/permissions.js";
import { PermissionService } from "../src/domain/security/permission-service.js";
import {
  BUILTIN_TOOLS,
  RAG_TOOLS,
  WEB_TOOLS,
  mergeTools,
  LazyToolLoader,
  assertProfileConsistency,
} from "../src/domain/tools/registry.js";
import { computeNextRun } from "../src/domain/scheduler/service.js";
import { chunkText, tokenize, Bm25Index } from "../src/domain/rag/store.js";
import { loopFingerprint } from "../src/domain/agent/loop.js";
import { isBlockedCommand, detectEscape, limitsFromSettings } from "../src/workers/sandbox.js";
import { estimateTokens } from "../src/domain/exec/tokens.js";
import { calculateCost, getPrice } from "../src/domain/accounting/pricing.js";
import { splitCommandSegments, normalizePath, isLocalAddress } from "../src/domain/security/policy.js";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const CONTRACT_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../contract",
);
const events = JSON.parse(
  fs.readFileSync(path.join(CONTRACT_DIR, "events.json"), "utf-8"),
) as {
  agentEvents: Array<{ name: string; payloadFields: string[] }>;
  sse: Array<{ endpoint: string }>;
};

describe("会话服务", () => {
  it("创建会话：mode=plan 归一为 work + plan_first=1", () => {
    ensureSchema();
    const out = sessionService.create("plan", "标题");
    expect(out.mode).toBe("plan");
    expect(out.plan_first).toBe(true);
  });

  it("非法模式抛错", () => {
    expect(() => sessionService.create("bogus" as never)).toThrow(/非法模式/);
  });

  it("消息序号连续递增（唯一约束不冲突）", () => {
    ensureSchema();
    const s = sessionService.create("chat");
    const m1 = sessionService.appendMessage(s.id, "user", "你好");
    const m2 = sessionService.appendMessage(s.id, "assistant", "在");
    expect(m1.seq).toBe(1);
    expect(m2.seq).toBe(2);
  });

  it("软删除后会话视为不存在（404 语义）", () => {
    ensureSchema();
    const s = sessionService.create("chat");
    expect(sessionService.delete(s.id)).toBe(true);
    expect(sessionService.get(s.id)).toBeNull();
  });

  it("物理删除（purge）会清掉消息", () => {
    ensureSchema();
    const s = sessionService.create("chat");
    sessionService.appendMessage(s.id, "user", "内容");
    expect(sessionService.purge(s.id)).toBe(true);
    expect(sessionService.get(s.id)).toBeNull();
  });

  it("历史回放只含 user / assistant，且首条必须是 user", () => {
    ensureSchema();
    const s = sessionService.create("chat");
    sessionService.appendMessage(s.id, "user", "问题");
    sessionService.appendMessage(s.id, "assistant", "回答");
    const history = sessionService.buildHistory(s.id);
    expect(history.map((h) => h.role)).toEqual(["user", "assistant"]);
  });

  it("列表按模式过滤，回收站维度独立于归档", () => {
    ensureSchema();
    const a = sessionService.create("chat");
    sessionService.create("work");
    sessionService.update(a.id, { archived: true });
    const active = sessionService.list("chat", 1, 20);
    expect(active.items.some((s) => s.id === a.id)).toBe(false);
    const withArchived = sessionService.list("chat", 1, 20, true);
    expect(withArchived.items.some((s) => s.id === a.id)).toBe(true);
  });
});

describe("运行账本服务", () => {
  it("创建运行并落 runs 表", () => {
    ensureSchema();
    const run = runService.createRun({ trigger: "api" });
    expect(run).not.toBeNull();
    expect(run!.status).toBe("queued");
    expect(runService.getRun(run!.id)!.id).toBe(run!.id);
  });

  it("(task_id, scheduled_for) 幂等：重复创建返回 null", () => {
    ensureSchema();
    // 外键约束开启（与 Python 侧一致）→ 先建定时任务
    const db = getDb();
    db.prepare(
      `INSERT INTO scheduled_tasks (id, name, prompt, mode, plan_first, team_id, skills_json,
        enable_json, schedule_kind, cron_expr, interval_seconds, rrule_expr, timezone, enabled,
        allow_unattended_tools, allow_dangerous_tools, daily_run_limit, next_run_at, last_run_at,
        last_status, last_error, run_count, consecutive_failures, backoff_until, delivery_json,
        created_at, updated_at)
       VALUES ('task-1', '任务', '提示', 'work', 0, NULL, '[]', '{}', 'cron', '0 9 * * *',
        NULL, NULL, 'UTC', 1, 0, 0, 100, NULL, NULL, 'never', NULL, 0, 0, NULL, '{}', ?, ?)`,
    ).run(new Date().toISOString(), new Date().toISOString());

    const first = runService.createRun({
      trigger: "schedule",
      taskId: "task-1",
      scheduledFor: "2026-01-01T00:00:00Z",
    });
    const second = runService.createRun({
      trigger: "schedule",
      taskId: "task-1",
      scheduledFor: "2026-01-01T00:00:00Z",
    });
    expect(first).not.toBeNull();
    expect(second).toBeNull();
  });

  it("事件按 seq 连续写入并可分页回放", () => {
    ensureSchema();
    const run = runService.createRun({ trigger: "api" })!;
    runService.appendEvents(run.id, [
      { type: "round_start", round: 1 },
      { type: "model_text", content: "你好" },
    ]);
    const { items, lastSeq } = runService.listEvents(run.id);
    expect(items.length).toBe(2);
    expect(items[0].seq).toBe(1);
    expect(items[1].type).toBe("model_text");
    expect(lastSeq).toBe(2);
  });

  it("终态守卫：已 interrupted 的 run 不被 finish 覆盖", () => {
    ensureSchema();
    const run = runService.createRun({ trigger: "api" })!;
    runService.interruptRun(run.id);
    runService.finish(run.id, "success", "完成");
    expect(runService.getRun(run.id)!.status).toBe("interrupted");
  });

  it("Plan 状态机：approve → queued，reject → rejected", () => {
    ensureSchema();
    const run = runService.createRun({ trigger: "api" })!;
    runService.savePlan(run.id, [{ id: 1, title: "步骤", detail: "" }]);
    expect(runService.getRun(run.id)!.status).toBe("awaiting_approval");
    runService.approvePlan(run.id);
    expect(runService.getRun(run.id)!.status).toBe("queued");

    const run2 = runService.createRun({ trigger: "api" })!;
    runService.savePlan(run2.id, []);
    runService.rejectRun(run2.id, "用户拒绝");
    expect(runService.getRun(run2.id)!.status).toBe("rejected");
  });
});

describe("权限引擎", () => {
  const rules: Rule[] = BUILTIN_RULES.map(([scope, pattern, decision, risk, priority]) => ({
    id: null,
    scope,
    pattern,
    decision,
    risk,
    workspace_id: null,
    priority,
  }));

  it("只读工具直接放行", () => {
    for (const tool of READONLY_TOOLS) {
      const d = decide({ tool }, rules);
      expect(d.decision, `工具 ${tool}`).toBe("allow");
    }
  });

  it("禁止路径命中 deny", () => {
    const d = decide({ tool: "write_file", path: `${process.env.HOME}/.ssh/id_rsa` }, rules);
    expect(d.decision).toBe("deny");
  });

  it("危险命令前缀命中 deny", () => {
    const d = decide({ tool: "execute_bash", command: "rm -rf /" }, rules);
    expect(d.decision).toBe("deny");
  });

  it("工作区内路径放行（工作区内常规读写零弹窗）", () => {
    const root = "/tmp/ws-root";
    const d = decide({ tool: "write_file", path: `${root}/report.md`, workspace_root: root }, rules);
    expect(d.decision).toBe("allow");
  });

  it("工作区外写路径 → ask", () => {
    const d = decide(
      { tool: "write_file", path: "/etc/hosts", workspace_root: "/tmp/ws-root" },
      rules,
    );
    expect(d.decision).toBe("ask");
  });

  it("高危动作默认拒绝", () => {
    const d = decide({ tool: "write_file", action: "batch_delete" }, rules);
    expect(d.decision).toBe("deny");
  });

  it("工具级 deny 立即生效", () => {
    const custom: Rule[] = [
      ...rules,
      { id: 1, scope: "tool", pattern: "write_file", decision: "deny", risk: "critical", workspace_id: null, priority: 1 },
    ];
    const d = decide({ tool: "write_file", path: "/tmp/ws-root/a.txt", workspace_root: "/tmp/ws-root" }, custom);
    expect(d.decision).toBe("deny");
  });

  it("权限档位聚合：readonly / ask / allow", () => {
    const svc = new PermissionService(120);
    ensureSchema();
    svc.ensureBuiltinRules();
    expect(["readonly", "ask", "allow"]).toContain(svc.effectiveLevel());
    expect(DANGEROUS_TOOLS.size).toBe(3);
  });
});

describe("工具注册表", () => {
  it("内置工具 8 个（含延迟装载的 tool_search / tool_load）", () => {
    expect(BUILTIN_TOOLS.length).toBe(8);
    expect(BUILTIN_TOOLS.map((t) => t.name)).toContain("tool_search");
    expect(BUILTIN_TOOLS.map((t) => t.name)).toContain("tool_load");
  });

  it("chat 档案只含只读内置工具 + rag_query", () => {
    const tools = mergeTools(null, {
      enableRag: true,
      profile: "chat",
    });
    const names = tools.map((t) => t.name);
    expect(names).toContain("read_file");
    expect(names).toContain("list_directory");
    expect(names).toContain("rag_query");
    expect(names).not.toContain("rag_ingest");
    expect(names).not.toContain("write_file");
  });

  it("work 档案含全部内置 + RAG + Web 工具", () => {
    const tools = mergeTools(null, {
      enableRag: true,
      enableWebResearch: true,
      profile: "work",
    });
    const names = tools.map((t) => t.name);
    expect(names.length).toBe(BUILTIN_TOOLS.length + RAG_TOOLS.length + WEB_TOOLS.length);
  });

  it("chat 档案含写类工具时断言失败", () => {
    expect(() =>
      assertProfileConsistency(
        [{ name: "write_file", description: "", input_schema: { type: "object", properties: {} } }],
        "chat",
      ),
    ).toThrow(/写类工具/);
  });

  it("延迟装载：检索返回候选，load 返回完整 Schema", () => {
    const loader = new LazyToolLoader([...BUILTIN_TOOLS, ...RAG_TOOLS, ...WEB_TOOLS]);
    const hits = loader.search("文件");
    expect(hits.length).toBeGreaterThan(0);
    const loaded = loader.load(["read_file"]);
    expect(loaded[0].name).toBe("read_file");
    expect(loader.loadedNames()).toContain("read_file");
  });
});

describe("调度器", () => {
  it("cron 触发可算出下次运行时间", () => {
    const next = computeNextRun(
      { schedule_kind: "cron", cron_expr: "0 9 * * *", interval_seconds: null, rrule_expr: null, timezone: "Asia/Shanghai" },
      new Date("2026-01-01T00:00:00Z"),
    );
    expect(next).toBeTruthy();
  });

  it("interval 触发按秒数推进", () => {
    const next = computeNextRun(
      { schedule_kind: "interval", cron_expr: null, interval_seconds: 3600, rrule_expr: null, timezone: "UTC" },
      new Date("2026-01-01T00:00:00Z"),
    );
    expect(next).toBe("2026-01-01T01:00:00.000Z");
  });

  it("非法表达式返回 null（不抛错）", () => {
    const next = computeNextRun(
      { schedule_kind: "cron", cron_expr: "不是 cron", interval_seconds: null, rrule_expr: null, timezone: "UTC" },
    );
    expect(next).toBeNull();
  });
});

describe("RAG 切块与 BM25", () => {
  it("切块保留内容且不超过 chunk_size", () => {
    const text = "a".repeat(2500);
    const chunks = chunkText(text, 1000);
    expect(chunks.length).toBeGreaterThanOrEqual(3);
    expect(chunks.every((c) => c.length <= 1000)).toBe(true);
  });

  it("中文可被分词", () => {
    const tokens = tokenize("本地文档库检索");
    expect(tokens.length).toBeGreaterThan(0);
  });

  it("BM25 能命中包含关键词的文档", () => {
    const index = new Bm25Index();
    index.rebuild(["苹果 手机 发布会", "香蕉 水果 价格", "本地 文档 库"]);
    const scores = index.search("文档");
    expect(scores.size).toBeGreaterThan(0);
    expect([...scores.keys()][0]).toBe(2);
  });
});

describe("沙箱边界", () => {
  it("命令黑名单命中", () => {
    expect(isBlockedCommand("rm -rf /")).toBeTruthy();
    expect(isBlockedCommand("mkfs.ext4")).toBeTruthy();
    expect(isBlockedCommand("ls -la")).toBeNull();
  });

  it("路径逃逸检测", () => {
    expect(detectEscape("/etc/passwd", "/tmp/ws")).toBe(true);
    expect(detectEscape("sub/file.txt", "/tmp/ws")).toBe(false);
  });

  it("资源限额与 §2.6 一致", () => {
    const limits = limitsFromSettings();
    expect(limits.cpuSeconds).toBe(60);
    expect(limits.memoryBytes).toBe(1024 * 1024 * 1024);
    expect(limits.openFiles).toBe(256);
    expect(limits.fileSizeBytes).toBe(64 * 1024 * 1024);
    expect(limits.maxOutputBytes).toBe(65536);
    expect(limits.timeoutSeconds).toBe(180);
  });
});

describe("Agent 事件与工具", () => {
  it("循环指纹稳定（同输入同指纹）", () => {
    const a = loopFingerprint("read_file", { file_path: "/a/b.txt" });
    const b = loopFingerprint("read_file", { file_path: "/a/b.txt" });
    expect(a).toBe(b);
    expect(a).not.toBe(loopFingerprint("read_file", { file_path: "/a/c.txt" }));
  });

  it("命令拆分与归一化", () => {
    expect(splitCommandSegments("a && b; c")).toEqual(["a", "b", "c"]);
  });

  it("本地地址判定", () => {
    expect(isLocalAddress("127.0.0.1")).toBe(true);
    expect(isLocalAddress("example.com")).toBe(false);
  });

  it("路径归一化得到绝对路径", () => {
    expect(normalizePath("/a/../b")).toContain("/b");
  });
});

describe("计量", () => {
  it("token 估算非零", () => {
    expect(estimateTokens("hello world")).toBeGreaterThan(0);
  });

  it("单价快照与成本随改价隔离", () => {
    const price = getPrice("qwen-plus");
    const [cost, snapshot] = calculateCost("qwen-plus", 1000, 1000);
    expect(cost).toBeCloseTo(price.input_per_1k + price.output_per_1k, 8);
    expect(snapshot.provider).toBe("dashscope");
  });

  it("未知模型回落兜底单价", () => {
    expect(getPrice("不存在的模型").provider).toBe("unknown");
  });
});

describe("事件契约", () => {
  it("冻结的事件清单含 26 种（含 loop_detected）", () => {
    expect(events.agentEvents.length).toBe(26);
    const names = events.agentEvents.map((e) => e.name);
    expect(names).toContain("loop_detected");
    expect(names).toContain("model_text");
    expect(names).toContain("tool_call");
    expect(names).toContain("tool_result");
    expect(names).toContain("done");
  });

  it("SSE 协议冻结为 4 条", () => {
    expect(events.sse.length).toBe(4);
    const endpoints = events.sse.map((s) => s.endpoint);
    expect(endpoints).toContain("POST /api/v1/agent/run");
    expect(endpoints).toContain("GET /api/v1/desktop/events");
  });
});
