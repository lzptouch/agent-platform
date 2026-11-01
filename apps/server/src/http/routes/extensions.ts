/**
 * 扩展路由（契约对齐：app/api/v1/extensions.py）。
 *
 * 端点：`POST /orchestrate` · `GET /roles` · `POST /roles` · `PATCH /roles/{id}`
 *      · `DELETE /roles/{id}` · `GET /plugins` · `POST /plugins/scan`
 *      · `POST /plugins/install` · `POST /plugins/rollback`
 *      · `GET /boards/{id}/items` · `POST /boards/{id}/items`
 *      · `POST /boards/{id}/items/{iid}/complete` · `GET /boards/{id}/messages`
 */
import fs from "node:fs";
import path from "node:path";
import type { FastifyInstance } from "fastify";
import { HttpError } from "../../shared/errors.js";
import { getDb, toJson, fromJson } from "../../db/client.js";
import { newId, utcNow, type RoleRow, type PluginRow, type BoardItemRow } from "../../db/schema.js";
import { settings } from "../../shared/config.js";
import { getLogger } from "../../shared/logger.js";
import { scanDirectory } from "../../domain/skill/scanner.js";

const logger = getLogger("routes.extensions");

export async function registerExtensionRoutes(app: FastifyInstance): Promise<void> {
  // ---------- 角色 ----------
  app.get("/api/v1/roles", async () => {
    const db = getDb();
    const rows = db.prepare("SELECT * FROM roles ORDER BY id").all() as RoleRow[];
    return { items: rows.map(roleToOut), total: rows.length };
  });

  app.post("/api/v1/roles", async (req, reply) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const name = String(body.name ?? "").trim();
    if (!name) throw new HttpError(422, "缺少 name");
    const db = getDb();
    const exists = db.prepare("SELECT id FROM roles WHERE name = ?").get(name);
    if (exists) throw new HttpError(409, `角色已存在: ${name}`);
    const now = utcNow();
    db.prepare(
      `INSERT INTO roles (name, title, identity, expertise, boundaries, workflow, output_style,
        tools_json, skills_json, model_tier, builtin, enabled, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, ?, ?)`,
    ).run(
      name,
      String(body.title ?? ""),
      String(body.identity ?? ""),
      toJson(body.expertise ?? []),
      toJson(body.boundaries ?? []),
      toJson(body.workflow ?? []),
      String(body.output_style ?? ""),
      toJson(body.tools ?? []),
      toJson(body.skills ?? []),
      String(body.model_tier ?? "standard"),
      now,
      now,
    );
    const row = db.prepare("SELECT * FROM roles WHERE name = ?").get(name) as RoleRow;
    return reply.code(201).send(roleToOut(row));
  });

  app.patch("/api/v1/roles/:role_id", async (req) => {
    const roleId = Number((req.params as Record<string, string>).role_id);
    const body = (req.body ?? {}) as Record<string, unknown>;
    const db = getDb();
    const row = db.prepare("SELECT * FROM roles WHERE id = ?").get(roleId) as RoleRow | undefined;
    if (!row) throw new HttpError(404, "角色不存在");
    // 名称创建后不可改名
    if (body.name !== undefined && String(body.name) !== row.name) {
      throw new HttpError(422, "角色名称创建后不可更改");
    }
    db.prepare(
      `UPDATE roles SET title = ?, identity = ?, expertise = ?, boundaries = ?, workflow = ?,
        output_style = ?, tools_json = ?, skills_json = ?, model_tier = ?, enabled = ?, updated_at = ?
       WHERE id = ?`,
    ).run(
      body.title !== undefined ? String(body.title) : row.title,
      body.identity !== undefined ? String(body.identity) : row.identity,
      body.expertise !== undefined ? toJson(body.expertise) : row.expertise_json,
      body.boundaries !== undefined ? toJson(body.boundaries) : row.boundaries_json,
      body.workflow !== undefined ? toJson(body.workflow) : row.workflow_json,
      body.output_style !== undefined ? String(body.output_style) : row.output_style,
      body.tools !== undefined ? toJson(body.tools) : row.tools_json,
      body.skills !== undefined ? toJson(body.skills) : row.skills_json,
      body.model_tier !== undefined ? String(body.model_tier) : row.model_tier,
      body.enabled !== undefined ? (body.enabled ? 1 : 0) : row.enabled,
      utcNow(),
      roleId,
    );
    const updated = db.prepare("SELECT * FROM roles WHERE id = ?").get(roleId) as RoleRow;
    return roleToOut(updated);
  });

  app.delete("/api/v1/roles/:role_id", async (req) => {
    const roleId = Number((req.params as Record<string, string>).role_id);
    const db = getDb();
    const row = db.prepare("SELECT * FROM roles WHERE id = ?").get(roleId) as RoleRow | undefined;
    if (!row) throw new HttpError(404, "角色不存在");
    if (row.builtin) throw new HttpError(422, "内置角色不可删除");
    db.prepare("DELETE FROM roles WHERE id = ?").run(roleId);
    return { ok: true, deleted: roleId };
  });

  // ---------- 插件 ----------
  app.get("/api/v1/plugins", async () => {
    const db = getDb();
    const rows = db.prepare("SELECT * FROM plugins ORDER BY id DESC").all() as PluginRow[];
    return { items: rows.map(pluginToOut), total: rows.length };
  });

  // ⚠️ **响应形状必须与契约一致**（Python 侧 `plugins/scan` 返回
  //    `ScanResult.as_dict()`：`{level, findings[], scanned_files, total_bytes,
  //    requires_confirmation, rejected_by_default}`）→ 前端 `PluginsView` 直接读
  //    `scanResult.level` / `.rejected_by_default` / `.findings[]`。
  app.post("/api/v1/plugins/scan", async (req) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const target = String(body.path ?? "").trim();
    if (!target) throw new HttpError(422, "缺少 path");
    if (!fs.existsSync(target)) throw new HttpError(404, `路径不存在: ${target}`);
    return scanDirectory(target);
  });

  app.post("/api/v1/plugins/install", async (req) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const name = String(body.name ?? "").trim();
    const version = String(body.version ?? "0.0.0").trim();
    if (!name) throw new HttpError(422, "缺少 name");
    const db = getDb();
    const now = utcNow();
    db.prepare(
      `INSERT INTO plugins (name, version, source, status, scan_result, manifest_json,
        installed_at, created_at, updated_at)
       VALUES (?, ?, ?, 'local', 'installed', ?, ?, ?, ?)`,
    ).run(
      name,
      version,
      toJson(body.manifest ?? {}),
      now,
      now,
      now,
    );
    const row = db
      .prepare("SELECT * FROM plugins WHERE name = ? AND version = ?")
      .get(name, version) as PluginRow;
    return pluginToOut(row);
  });

  app.post("/api/v1/plugins/rollback", async (req) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const name = String(body.name ?? "").trim();
    const db = getDb();
    const rows = db
      .prepare("SELECT * FROM plugins WHERE name = ? ORDER BY id DESC")
      .all(name) as PluginRow[];
    if (rows.length < 2) throw new HttpError(409, "没有可回滚的历史版本");
    const current = rows[0];
    const previous = rows[1];
    db.prepare("UPDATE plugins SET status = 'rolled_back', updated_at = ? WHERE id = ?").run(
      utcNow(),
      current.id,
    );
    db.prepare("UPDATE plugins SET status = 'installed', updated_at = ? WHERE id = ?").run(
      utcNow(),
      previous.id,
    );
    return { ok: true, rolled_back_to: pluginToOut(previous) };
  });

  // ---------- 黑板 ----------
  app.get("/api/v1/boards/:board_id/items", async (req) => {
    const boardId = String((req.params as Record<string, string>).board_id);
    const db = getDb();
    const rows = db
      .prepare("SELECT * FROM board_items WHERE board_id = ? ORDER BY id")
      .all(boardId) as BoardItemRow[];
    return { items: rows.map(boardItemToOut), total: rows.length };
  });

  app.post("/api/v1/boards/:board_id/items", async (req, reply) => {
    const boardId = String((req.params as Record<string, string>).board_id);
    const body = (req.body ?? {}) as Record<string, unknown>;
    const title = String(body.title ?? "").trim();
    if (!title) throw new HttpError(422, "缺少 title");
    const db = getDb();
    const now = utcNow();
    db.prepare(
      `INSERT INTO board_items (board_id, title, detail, status, assignee, deps_json,
        result_json, created_at, updated_at)
       VALUES (?, ?, ?, 'pending', ?, ?, '{}', ?, ?)`,
    ).run(
      boardId,
      title,
      String(body.detail ?? ""),
      body.assignee ? String(body.assignee) : null,
      toJson(body.deps ?? []),
      now,
      now,
    );
    const row = db.prepare("SELECT * FROM board_items ORDER BY id DESC LIMIT 1").get() as BoardItemRow;
    return reply.code(201).send(boardItemToOut(row));
  });

  app.post("/api/v1/boards/:board_id/items/:item_id/complete", async (req) => {
    const params = req.params as Record<string, string>;
    const itemId = Number(params.item_id);
    const body = (req.body ?? {}) as Record<string, unknown>;
    const db = getDb();
    const row = db.prepare("SELECT * FROM board_items WHERE id = ?").get(itemId) as
      | BoardItemRow
      | undefined;
    if (!row) throw new HttpError(404, "任务项不存在");
    const result = body.result ?? {};
    db.prepare(
      "UPDATE board_items SET status = 'done', result_json = ?, updated_at = ? WHERE id = ?",
    ).run(toJson(result), utcNow(), itemId);
    const updated = db.prepare("SELECT * FROM board_items WHERE id = ?").get(itemId) as BoardItemRow;
    return boardItemToOut(updated);
  });

  app.get("/api/v1/boards/:board_id/messages", async (req) => {
    const boardId = String((req.params as Record<string, string>).board_id);
    const db = getDb();
    const rows = db
      .prepare("SELECT * FROM agent_messages WHERE board_id = ? ORDER BY id")
      .all(boardId) as Array<Record<string, unknown>>;
    return {
      items: rows.map((r) => ({
        ...r,
        refs: fromJson<unknown[]>(r.refs_json as string, []),
      })),
      total: rows.length,
    };
  });

  // ---------- 多 Agent 编排 ----------
  app.post("/api/v1/orchestrate", async (req) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const strategy = String(body.strategy ?? "parallel");
    if (!["parallel", "sequential", "review"].includes(strategy)) {
      throw new HttpError(422, "strategy 必须是 parallel / sequential / review 之一");
    }
    const roles = Array.isArray(body.roles) ? (body.roles as string[]) : [];
    const task = String(body.task ?? "");
    if (!task) throw new HttpError(422, "缺少 task");
    const boardId = newId();
    logger.info("编排任务已受理", { boardId, strategy, roles: roles.length });
    return {
      ok: true,
      board_id: boardId,
      strategy,
      roles,
      task,
      status: "queued",
      created_at: utcNow(),
    };
  });
}

function roleToOut(row: RoleRow): Record<string, unknown> {
  return {
    id: row.id,
    name: row.name,
    title: row.title,
    identity: row.identity,
    expertise: fromJson<string[]>(row.expertise_json, []),
    boundaries: fromJson<string[]>(row.boundaries_json, []),
    workflow: fromJson<string[]>(row.workflow_json, []),
    output_style: row.output_style,
    tools: fromJson<string[]>(row.tools_json, []),
    skills: fromJson<string[]>(row.skills_json, []),
    model_tier: row.model_tier,
    builtin: Boolean(row.builtin),
    enabled: Boolean(row.enabled),
    created_at: row.created_at,
    updated_at: row.updated_at,
  };
}

function pluginToOut(row: PluginRow): Record<string, unknown> {
  return {
    id: row.id,
    name: row.name,
    version: row.version,
    source: row.source,
    status: row.status,
    scan_result: fromJson<Record<string, unknown>>(row.scan_result, {}),
    manifest: fromJson<Record<string, unknown>>(row.manifest_json, {}),
    installed_at: row.installed_at,
    created_at: row.created_at,
    updated_at: row.updated_at,
  };
}

function boardItemToOut(row: BoardItemRow): Record<string, unknown> {
  return {
    id: row.id,
    board_id: row.board_id,
    title: row.title,
    detail: row.detail,
    status: row.status,
    assignee: row.assignee,
    deps: fromJson<unknown[]>(row.deps_json, []),
    result: fromJson<Record<string, unknown>>(row.result_json, {}),
    created_at: row.created_at,
    updated_at: row.updated_at,
  };
}
