/**
 * Team 路由（契约对齐：app/api/v1/teams.py）。
 *
 * 端点：`GET /` · `POST /` · `GET /{id}` · `PUT /{id}` · `DELETE /{id}`
 *      · `POST /{id}/toggle` · `POST /{id}/resolve`
 */
import type { FastifyInstance } from "fastify";
import { HttpError } from "../../shared/errors.js";
import { teamService } from "../../domain/team/service.js";

export async function registerTeamRoutes(app: FastifyInstance): Promise<void> {
  // ⚠️ **响应形状必须与冻结契约一致**：`contract/openapi.json` 里
  // `GET /api/v1/teams` 的 200 响应是 **array**（Python 侧 `response_model=list[TeamOut]`）
  // → 必须返回**裸数组**。
  // 此前返回 `{items:[...]}` → 前端 `teams.value = await teamsList()` 拿到的是
  // **对象** → el-table 抛 `Me is not iterable`（P8-02 实测）。
  app.get("/api/v1/teams", async () => teamService.list());

  app.post("/api/v1/teams", async (req, reply) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const name = String(body.name ?? "").trim();
    if (!name) throw new HttpError(422, "缺少 name");
    const team = teamService.create({
      name,
      description: String(body.description ?? ""),
      prompt_prefix: String(body.prompt_prefix ?? ""),
      strategy: String(body.strategy ?? "none"),
      members: Array.isArray(body.members) ? (body.members as string[]) : [],
    });
    return reply.code(201).send(team);
  });

  app.get("/api/v1/teams/:team_id", async (req) => {
    const teamId = String((req.params as Record<string, string>).team_id);
    const team = teamService.get(teamId);
    if (!team) throw new HttpError(404, "团队不存在");
    return team;
  });

  app.put("/api/v1/teams/:team_id", async (req) => {
    const teamId = String((req.params as Record<string, string>).team_id);
    const body = (req.body ?? {}) as Record<string, unknown>;
    const team = teamService.update(teamId, {
      description: body.description !== undefined ? String(body.description) : undefined,
      prompt_prefix:
        body.prompt_prefix !== undefined ? String(body.prompt_prefix) : undefined,
      strategy: body.strategy !== undefined ? String(body.strategy) : undefined,
      members: Array.isArray(body.members) ? (body.members as string[]) : undefined,
    });
    if (!team) throw new HttpError(404, "团队不存在");
    return team;
  });

  app.delete("/api/v1/teams/:team_id", async (req) => {
    const teamId = String((req.params as Record<string, string>).team_id);
    if (!teamService.delete(teamId)) throw new HttpError(404, "团队不存在");
    return { ok: true };
  });

  app.post("/api/v1/teams/:team_id/toggle", async (req) => {
    const teamId = String((req.params as Record<string, string>).team_id);
    const body = (req.body ?? {}) as Record<string, unknown>;
    const team = teamService.toggle(
      teamId,
      body.enabled !== undefined ? Boolean(body.enabled) : undefined,
    );
    if (!team) throw new HttpError(404, "团队不存在");
    return team;
  });

  app.post("/api/v1/teams/:team_id/resolve", async (req) => {
    const teamId = String((req.params as Record<string, string>).team_id);
    const body = (req.body ?? {}) as Record<string, unknown>;
    const team = teamService.get(teamId);
    if (!team) throw new HttpError(404, "团队不存在");
    const resolved = teamService.resolve(teamId, String(body.query ?? ""));
    return { team_id: teamId, ...resolved };
  });
}
