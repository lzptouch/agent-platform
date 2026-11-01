/**
 * 工作空间路由（契约对齐：app/api/v1/workspace.py）。
 *
 * 端点：`GET /workspaces` · `POST /workspaces` · `GET /workspaces/{id}/manifest`
 *      · `PUT /workspaces/{id}/manifest` · `POST /workspaces/{id}/switch`
 *      · `POST /workspaces/{id}/archive` · `GET /changes/{id}/diff`
 *      · `POST /changes/{id}/revert`
 */
import fs from "node:fs";
import path from "node:path";
import type { FastifyInstance } from "fastify";
import { HttpError } from "../../shared/errors.js";
import { workspaceService } from "../../domain/workspace/service.js";
import { readManifest, writeManifest, validateManifest } from "../../domain/workspace/manifest.js";
import { getDb } from "../../db/client.js";

export async function registerWorkspaceRoutes(app: FastifyInstance): Promise<void> {
  app.get("/api/v1/workspaces", async (req) => {
    const q = req.query as Record<string, string>;
    const items = workspaceService.list(q.include_archived === "true");
    // ⚠️ **必须带 `current`**（契约对齐：Python 侧返回 `{items, current}`）→
    //    前端 `WorkspacePicker` 读 `data.current` 来高亮当前空间。
    const current = workspaceService.current();
    return { items, current: current?.id ?? null };
  });

  app.post("/api/v1/workspaces", async (req, reply) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const name = String(body.name ?? "").trim();
    if (!name) throw new HttpError(422, "缺少 name");
    const ws = workspaceService.create(
      name,
      body.root_path ? String(body.root_path) : null,
    );
    return reply.code(201).send(ws);
  });

  app.get("/api/v1/workspaces/:workspace_id/manifest", async (req) => {
    const wsId = String((req.params as Record<string, string>).workspace_id);
    const ws = workspaceService.get(wsId);
    if (!ws) throw new HttpError(404, "工作空间不存在");
    const container = path.dirname(ws.root_path);
    const dirName = path.basename(ws.root_path);
    return {
      workspace_id: wsId,
      manifest: readManifest(container, dirName),
    };
  });

  app.put("/api/v1/workspaces/:workspace_id/manifest", async (req) => {
    const wsId = String((req.params as Record<string, string>).workspace_id);
    const ws = workspaceService.get(wsId);
    if (!ws) throw new HttpError(404, "工作空间不存在");
    const body = (req.body ?? {}) as Record<string, unknown>;
    const updates = body.manifest ?? body;
    try {
      validateManifest(updates);
    } catch (err) {
      throw new HttpError(422, (err as Error).message);
    }
    const container = path.dirname(ws.root_path);
    const dirName = path.basename(ws.root_path);
    const manifest = writeManifest(container, dirName, updates);
    return { ok: true, workspace_id: wsId, manifest };
  });

  app.post("/api/v1/workspaces/:workspace_id/switch", async (req) => {
    const wsId = String((req.params as Record<string, string>).workspace_id);
    try {
      const ws = workspaceService.switch(wsId);
      return { ok: true, workspace_id: ws.id, workspace_dir: ws.root_path };
    } catch (err) {
      throw new HttpError(400, (err as Error).message);
    }
  });

  app.post("/api/v1/workspaces/:workspace_id/archive", async (req) => {
    const wsId = String((req.params as Record<string, string>).workspace_id);
    if (!workspaceService.archive(wsId)) throw new HttpError(404, "工作空间不存在");
    return { ok: true, workspace_id: wsId };
  });

  app.get("/api/v1/changes/:change_id/diff", async (req) => {
    const changeId = Number((req.params as Record<string, string>).change_id);
    const db = getDb();
    const row = db.prepare("SELECT * FROM changes WHERE id = ?").get(changeId) as
      | {
          id: number;
          path: string;
          op: string;
          before_hash: string | null;
          after_hash: string | null;
          snapshot_ref: string | null;
          tool: string;
        }
      | undefined;
    if (!row) throw new HttpError(404, "变更不存在");
    let before: string | null = null;
    let after: string | null = null;
    if (row.snapshot_ref && fs.existsSync(row.snapshot_ref)) {
      before = fs.readFileSync(row.snapshot_ref, "utf-8");
    }
    if (fs.existsSync(row.path)) {
      after = fs.readFileSync(row.path, "utf-8");
    }
    return {
      change_id: row.id,
      path: row.path,
      op: row.op,
      tool: row.tool,
      before_hash: row.before_hash,
      after_hash: row.after_hash,
      before,
      after,
      diff: before !== null && after !== null ? simpleDiff(before, after) : null,
    };
  });

  app.post("/api/v1/changes/:change_id/revert", async (req) => {
    const changeId = Number((req.params as Record<string, string>).change_id);
    const db = getDb();
    const row = db.prepare("SELECT * FROM changes WHERE id = ?").get(changeId) as
      | { id: number; path: string; snapshot_ref: string | null; op: string }
      | undefined;
    if (!row) throw new HttpError(404, "变更不存在");
    if (!row.snapshot_ref || !fs.existsSync(row.snapshot_ref)) {
      throw new HttpError(409, "该变更没有可用的快照，无法回退");
    }
    fs.copyFileSync(row.snapshot_ref, row.path);
    db.prepare("UPDATE changes SET op = 'revert' WHERE id = ?").run(row.id);
    return { ok: true, change_id: row.id, path: row.path };
  });
}

/** 极简行级 diff（避免引入依赖）。 */
function simpleDiff(before: string, after: string): string[] {
  const beforeLines = before.split("\n");
  const afterLines = after.split("\n");
  const out: string[] = [];
  const max = Math.max(beforeLines.length, afterLines.length);
  for (let i = 0; i < max; i += 1) {
    if (beforeLines[i] === afterLines[i]) continue;
    if (beforeLines[i] !== undefined) out.push(`- ${beforeLines[i]}`);
    if (afterLines[i] !== undefined) out.push(`+ ${afterLines[i]}`);
  }
  return out;
}
