/**
 * 权限路由（契约对齐：app/api/v1/permissions.py）。
 *
 * 端点：`GET /rules` · `PUT /rules` · `DELETE /rules` · `GET /decisions`
 *      · `POST /decisions` · `GET /sandbox`
 */
import type { FastifyInstance } from "fastify";
import { HttpError } from "../../shared/errors.js";
import { getPermissionService } from "../../domain/security/permission-service.js";
import { DECISIONS } from "../../domain/security/permissions.js";
import { detectPython } from "../../workers/sandbox.js";
import { settings } from "../../shared/config.js";

export async function registerPermissionRoutes(app: FastifyInstance): Promise<void> {
  app.get("/api/v1/permissions/rules", async () => {
    const svc = getPermissionService();
    return {
      rules: svc.listRules(),
      effective_level: svc.effectiveLevel(),
    };
  });

  app.put("/api/v1/permissions/rules", async (req) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const svc = getPermissionService();
    // 档位批量设置
    if (body.level !== undefined) {
      const level = String(body.level);
      if (!["readonly", "ask", "allow"].includes(level)) {
        throw new HttpError(422, `未知的权限档位: ${level}`);
      }
      return svc.setLevel(level);
    }
    const scope = String(body.scope ?? "").trim();
    const target = String(body.target ?? "").trim();
    const decision = String(body.decision ?? "").trim();
    if (!DECISIONS.includes(decision as (typeof DECISIONS)[number])) {
      throw new HttpError(422, `未知的决定: ${decision}`);
    }
    try {
      const rule = svc.setRule(
        scope,
        target,
        decision,
        body.workspace_id ? String(body.workspace_id) : null,
      );
      return { ok: true, rule, effective_level: svc.effectiveLevel() };
    } catch (err) {
      throw new HttpError(422, (err as Error).message);
    }
  });

  app.delete("/api/v1/permissions/rules", async (req) => {
    const q = req.query as Record<string, string>;
    const scope = String(q.scope ?? "").trim();
    const target = String(q.target ?? "").trim();
    const svc = getPermissionService();
    const deleted = svc.deleteRule(
      scope,
      target,
      q.workspace_id ? String(q.workspace_id) : null,
    );
    if (!deleted) throw new HttpError(404, "规则不存在");
    return { ok: true, effective_level: svc.effectiveLevel() };
  });

  app.get("/api/v1/permissions/decisions", async () => {
    const svc = getPermissionService();
    return { items: svc.pendingDecisions() };
  });

  app.post("/api/v1/permissions/decisions", async (req) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const decisionId = Number(body.decision_id ?? body.id ?? 0);
    const choice = String(body.choice ?? body.decision ?? "").trim();
    if (!decisionId) throw new HttpError(422, "缺少 decision_id");
    const svc = getPermissionService();
    const resolved = svc.resolveDecision(decisionId, choice);
    if (!resolved) throw new HttpError(404, "待审批记录不存在或已过期");
    return { ok: true, decision_id: decisionId, choice };
  });

  app.get("/api/v1/permissions/sandbox", async () => {
    const python = detectPython();
    return {
      available: true,
      python_available: Boolean(python),
      python_path: python,
      resource_limits: settings.exec_resource_limits,
      limits: {
        cpu_seconds: settings.exec_cpu_seconds,
        memory_bytes: settings.exec_memory_bytes,
        open_files: settings.exec_open_files,
        file_size_bytes: settings.exec_file_size_bytes,
        max_output_bytes: settings.exec_max_output_bytes,
        timeout_seconds: settings.exec_timeout,
      },
    };
  });
}
