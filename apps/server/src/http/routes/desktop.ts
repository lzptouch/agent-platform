/**
 * 桌面端路由（契约对齐：app/api/v1/desktop.py）。
 *
 * 端点：`GET /status` · `GET /components` · `GET /preferences` · `PUT /preferences`
 *      · `GET /workspace` · `PUT /workspace` · `GET /events`（SSE）
 *      · `POST /shutdown` · `GET /permissions` · `PUT /permissions`
 *      · `POST /permissions/decision` · `POST /scheduler/resume-scan`
 */
import type { FastifyInstance } from "fastify";
import { HttpError } from "../../shared/errors.js";
import { sse } from "../sse.js";
import { bus } from "../events.js";
import { getDb, fromJson, toJson } from "../../db/client.js";
import { utcNow, type DesktopPreferenceRow } from "../../db/schema.js";
import { settings } from "../../shared/config.js";
import { getPermissionService } from "../../domain/security/permission-service.js";
import { DECISIONS } from "../../domain/security/permissions.js";
import { workspaceService } from "../../domain/workspace/service.js";
import { schedulerService } from "../../domain/scheduler/service.js";
import fs from "node:fs";
import path from "node:path";

const EVENT_POLL_INTERVAL_MS = 300;
const EVENT_MAX_SECONDS = 3600;

export async function registerDesktopRoutes(app: FastifyInstance): Promise<void> {
  app.get("/api/v1/desktop/status", async () => {
    const db = getDb();
    const pref = db.prepare("SELECT * FROM desktop_preferences WHERE id = 1").get() as
      | DesktopPreferenceRow
      | undefined;
    const permissionService = getPermissionService();
    const current = workspaceService.current();
    // ⚠️ **响应形状必须与冻结契约一致**（Python 侧 `DesktopService.status()`）：
    //   mode / app_version / backend_version / protocol / started_at / data_dir /
    //   workspace_dir / runtime / components / scheduler / security
    // 此前缺 `runtime` 与 `components` → 前端 `desktop.status.runtime.python`
    // 抛 `Cannot read properties of undefined`（P8-02 实测）。
    const components = desktopComponents();
    return {
      mode: pref?.remote_mode ? "remote" : "local",
      app_version: settings.app_version,
      backend_version: settings.app_version,
      protocol: settings.desktop_protocol,
      started_at: utcNow(),
      data_dir: settings.user_data_dir,
      workspace_dir: current?.root_path ?? settings.default_workspace_dir,
      // **单运行时**（design/16）：不再有 Python → `python` 置 null，另报 Node
      runtime: {
        python: null,
        node: process.version,
        executable: process.execPath,
        frozen: false,
      },
      components,
      scheduler: schedulerService.health(),
      security: {
        auth_required: settings.desktop_mode,
        cors_origins: settings.cors_origin_list,
        permission_level: permissionService.effectiveLevel(),
      },
      // 扩展字段（契约允许 additionalProperties）
      desktop_mode: settings.desktop_mode,
      has_api_key: settings.has_api_key,
      preferences: pref ? preferencesToOut(pref) : null,
    };
  });

  // ⚠️ 契约要求 `components.playwright_chromium.{installed,path,size_bytes}`
  //    （Python 侧 `DesktopService.components()`）→ 此前返回的是另一套形状，
  //    前端读不到（design/16 §7.2）。
  app.get("/api/v1/desktop/components", async () => desktopComponents());

  app.get("/api/v1/desktop/preferences", async () => {
    const db = getDb();
    const pref = db.prepare("SELECT * FROM desktop_preferences WHERE id = 1").get() as
      | DesktopPreferenceRow
      | undefined;
    return preferencesToOut(pref ?? defaultPreferences());
  });

  app.put("/api/v1/desktop/preferences", async (req) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const db = getDb();
    const current =
      (db.prepare("SELECT * FROM desktop_preferences WHERE id = 1").get() as
        | DesktopPreferenceRow
        | undefined) ?? defaultPreferences();
    const next = { ...preferencesToOut(current) };
    if (body.workspace_dir !== undefined) next.workspace_dir = String(body.workspace_dir);
    if (body.default_mode !== undefined) next.default_mode = String(body.default_mode);
    if (body.danger_tools !== undefined) next.danger_tools = Number(body.danger_tools);
    if (body.notify_on_run !== undefined) next.notify_on_run = Number(body.notify_on_run);
    if (body.notify_channel !== undefined) next.notify_channel = String(body.notify_channel);
    if (body.remote_mode !== undefined) next.remote_mode = Number(body.remote_mode);
    if (body.remote_base !== undefined) next.remote_base = String(body.remote_base);

    const now = utcNow();
    db.prepare(
      `INSERT INTO desktop_preferences (id, workspace_dir, default_mode, danger_tools,
        notify_on_run, notify_channel, remote_mode, remote_base, updated_at)
       VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(id) DO UPDATE SET workspace_dir = excluded.workspace_dir,
         default_mode = excluded.default_mode, danger_tools = excluded.danger_tools,
         notify_on_run = excluded.notify_on_run, notify_channel = excluded.notify_channel,
         remote_mode = excluded.remote_mode, remote_base = excluded.remote_base,
         updated_at = excluded.updated_at`,
    ).run(
      next.workspace_dir,
      next.default_mode,
      next.danger_tools,
      next.notify_on_run,
      next.notify_channel,
      next.remote_mode,
      next.remote_base,
      now,
    );
    const updated = db.prepare("SELECT * FROM desktop_preferences WHERE id = 1").get() as DesktopPreferenceRow;
    return { ok: true, preferences: preferencesToOut(updated) };
  });

  app.get("/api/v1/desktop/workspace", async () => {
    const current = workspaceService.current();
    return {
      workspace_dir: current?.root_path ?? settings.default_workspace_dir,
      workspace_id: current?.id ?? null,
      workspaces: workspaceService.list(),
    };
  });

  app.put("/api/v1/desktop/workspace", async (req) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const target = String(body.path ?? "").trim();
    if (!target) throw new HttpError(400, "缺少 path");
    let ws;
    try {
      ws = workspaceService.switch(target);
    } catch (err) {
      throw new HttpError(400, (err as Error).message);
    }
    bus.publish("workspace_changed", { workspace_dir: ws.root_path });
    return { ok: true, workspace_id: ws.id, workspace_dir: ws.root_path };
  });

  // SSE：`max_events` 为**有界模式**（可测性要求）
  app.get("/api/v1/desktop/events", async (req, reply) => {
    const q = req.query as Record<string, string>;
    const afterId = Number(q.after_id ?? 0) || 0;
    const maxEvents = q.max_events ? Number(q.max_events) : null;
    const channel = sse(reply);
    let cursor = afterId;
    let sent = 0;
    const deadline = Date.now() + EVENT_MAX_SECONDS * 1000;

    const push = (payload: Record<string, unknown>): boolean => {
      channel.send("message", payload);
      sent += 1;
      return maxEvents !== null && sent >= maxEvents;
    };

    try {
      if (push({ type: "hello", protocol: 1, backend_version: settings.app_version })) {
        return reply;
      }
      while (Date.now() < deadline) {
        for (const event of bus.since(cursor)) {
          cursor = event.id;
          if (push(event as unknown as Record<string, unknown>)) return reply;
        }
        if (push({ type: "heartbeat", ts: new Date().toISOString() })) return reply;
        await new Promise((r) => setTimeout(r, EVENT_POLL_INTERVAL_MS));
      }
    } finally {
      channel.end();
    }
    return reply;
  });

  app.post("/api/v1/desktop/shutdown", async () => ({
    ok: true,
    message: "shutdown requested",
  }));

  app.get("/api/v1/desktop/permissions", async () => {
    const svc = getPermissionService();
    return {
      rules: svc.listRules(),
      effective_level: svc.effectiveLevel(),
      sandbox_available: true,
    };
  });

  app.put("/api/v1/desktop/permissions", async (req) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const scope = String(body.scope ?? "").trim();
    const target = String(body.target ?? "").trim();
    const decision = String(body.decision ?? "").trim();
    if (!DECISIONS.includes(decision as (typeof DECISIONS)[number])) {
      throw new HttpError(422, `未知的决定: ${decision}`);
    }
    const svc = getPermissionService();
    try {
      const rule = svc.setRule(scope, target, decision);
      return { ok: true, rule, effective_level: svc.effectiveLevel() };
    } catch (err) {
      throw new HttpError(422, (err as Error).message);
    }
  });

  app.post("/api/v1/desktop/permissions/decision", async (req) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const decision = String(body.decision ?? "").trim();
    const scope = String(body.scope ?? "").trim();
    const target = String(body.target ?? "").trim();
    if (!["once", "always", "deny"].includes(decision)) {
      throw new HttpError(422, "decision 必须是 once / always / deny");
    }
    if (!scope || !target) throw new HttpError(422, "缺少 scope / target");
    const svc = getPermissionService();
    // **只有 always / deny 才落库**；once 不写规则表
    if (decision === "always" || decision === "deny") {
      try {
        svc.setRule(scope, target, decision === "always" ? "allow" : "deny");
      } catch (err) {
        throw new HttpError(422, (err as Error).message);
      }
    }
    return {
      ok: true,
      decision,
      expires_at: null,
      persisted: decision === "always" || decision === "deny",
    };
  });

  app.post("/api/v1/desktop/scheduler/resume-scan", async (req) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const rawSince = String(body.missed_since ?? "").trim();
    let since: Date;
    if (rawSince) {
      const parsed = new Date(rawSince);
      if (Number.isNaN(parsed.getTime())) {
        throw new HttpError(422, "missed_since 必须是 ISO8601");
      }
      since = parsed;
    } else {
      since = new Date();
    }
    const result = schedulerService.rescueMissedRuns(since);
    bus.publish("scheduler_rescued", { rescued: result.rescued });
    return { ok: true, ...result };
  });
}

function defaultPreferences(): DesktopPreferenceRow {
  return {
    id: 1,
    workspace_dir: "",
    default_mode: "chat",
    danger_tools: 0,
    notify_on_run: 1,
    notify_channel: "system",
    remote_mode: 0,
    remote_base: "",
    updated_at: utcNow(),
  };
}

function preferencesToOut(row: DesktopPreferenceRow): Record<string, unknown> {
  return {
    workspace_dir: row.workspace_dir,
    default_mode: row.default_mode,
    danger_tools: Boolean(row.danger_tools),
    notify_on_run: Boolean(row.notify_on_run),
    notify_channel: row.notify_channel,
    remote_mode: Boolean(row.remote_mode),
    remote_base: row.remote_base,
    updated_at: row.updated_at,
  };
}

/**
 * 已安装组件状态（契约对齐：Python 侧 `DesktopService.components()`）。
 *
 * 契约形状：`{ playwright_chromium: { installed, path, size_bytes } }`；
 * 另附**能力开关**（mcp / rag / web_research）—— 契约允许 additionalProperties。
 */
function desktopComponents(): Record<string, unknown> {
  const browsersRoot = (process.env.PLAYWRIGHT_BROWSERS_PATH ?? "").trim();
  let installed = false;
  let sizeBytes = 0;
  if (browsersRoot && fs.existsSync(browsersRoot)) {
    try {
      installed = fs.readdirSync(browsersRoot).length > 0;
      const walk = (dir: string): void => {
        for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
          const p = path.join(dir, entry.name);
          if (entry.isDirectory()) walk(p);
          else {
            try {
              sizeBytes += fs.statSync(p).size;
            } catch {
              // 忽略不可读文件
            }
          }
        }
      };
      walk(browsersRoot);
    } catch {
      installed = false;
    }
  }
  return {
    playwright_chromium: {
      installed,
      path: browsersRoot,
      size_bytes: sizeBytes,
    },
    // 能力开关（单运行时下 Python 已退场）
    python: { available: false, required: false },
    mcp: { available: true, required: false },
    rag: { available: settings.has_api_key, required: false },
    web_research: { available: settings.web_search_available, required: false },
  };
}
