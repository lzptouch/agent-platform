/**
 * Skill 路由（契约对齐：app/api/v1/skills.py）。
 *
 * 端点：`GET /` · `POST /` · `GET /{name}` · `PUT /{name}` · `DELETE /{name}`
 *      · `POST /{name}/toggle` · `POST /{name}/validate` · `GET /{name}/export`
 *      · `GET /{name}/files/{resource_path}` · `POST /import` · `POST /reload`
 */
import fs from "node:fs";
import path from "node:path";
import AdmZip from "adm-zip";
import type { FastifyInstance } from "fastify";
import { HttpError } from "../../shared/errors.js";
import { skillManager, parseFrontmatter } from "../../domain/skill/manager.js";
import { settings } from "../../shared/config.js";
import { getLogger } from "../../shared/logger.js";

const logger = getLogger("routes.skills");

export async function registerSkillRoutes(app: FastifyInstance): Promise<void> {
  app.get("/api/v1/skills", async () => ({
    total: skillManager.listSummaries().length,
    skills: skillManager.listSummaries(),
  }));

  app.post("/api/v1/skills", async (req, reply) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const name = String(body.name ?? "").trim();
    if (!name) throw new HttpError(422, "缺少 name");
    const skill = skillManager.createSkill(
      name,
      String(body.description ?? ""),
      body.content !== undefined ? String(body.content) : undefined,
    );
    return reply.code(201).send(skill);
  });

  app.get("/api/v1/skills/:name", async (req) => {
    const name = String((req.params as Record<string, string>).name);
    const skill = skillManager.getSkill(name);
    if (!skill) throw new HttpError(404, "Skill 不存在");
    return skill;
  });

  app.put("/api/v1/skills/:name", async (req) => {
    const name = String((req.params as Record<string, string>).name);
    const body = (req.body ?? {}) as Record<string, unknown>;
    const skill = skillManager.updateSkill(name, {
      description: body.description !== undefined ? String(body.description) : undefined,
      content: body.content !== undefined ? String(body.content) : undefined,
    });
    if (!skill) throw new HttpError(404, "Skill 不存在");
    return skill;
  });

  app.delete("/api/v1/skills/:name", async (req) => {
    const name = String((req.params as Record<string, string>).name);
    if (!skillManager.deleteSkill(name)) throw new HttpError(404, "Skill 不存在");
    return { ok: true, deleted: name };
  });

  app.post("/api/v1/skills/:name/toggle", async (req) => {
    const name = String((req.params as Record<string, string>).name);
    const body = (req.body ?? {}) as Record<string, unknown>;
    const skill = skillManager.toggleSkill(
      name,
      body.enabled !== undefined ? Boolean(body.enabled) : undefined,
    );
    if (!skill) throw new HttpError(404, "Skill 不存在");
    return skill;
  });

  app.post("/api/v1/skills/:name/validate", async (req) => {
    const name = String((req.params as Record<string, string>).name);
    const skill = skillManager.getSkill(name);
    if (!skill) throw new HttpError(404, "Skill 不存在");
    const fm = parseFrontmatter(skill.content);
    const issues: string[] = [];
    if (!fm.name) issues.push("缺少 frontmatter.name");
    if (!fm.description) issues.push("缺少 frontmatter.description");
    return { valid: issues.length === 0, issues, frontmatter: fm };
  });

  app.get("/api/v1/skills/:name/export", async (req, reply) => {
    const name = String((req.params as Record<string, string>).name);
    const exported = skillManager.exportSkill(name);
    if (!exported) throw new HttpError(404, "Skill 不存在");
    const zip = new AdmZip();
    for (const file of exported.files) {
      zip.addFile(file.path, Buffer.from(file.content, "utf-8"));
    }
    return reply
      .code(200)
      .type("application/zip")
      .header("Content-Disposition", `attachment; filename="${name}.zip"`)
      .send(zip.toBuffer());
  });

  // 单段资源路径（与 OpenAPI 的 `{resource_path}` 参数一一对应）
  app.get("/api/v1/skills/:name/files/:resource_path", async (req) => {
    const params = req.params as Record<string, string>;
    const name = params.name;
    const resourcePath = params.resource_path ?? "";
    const resource = skillManager.readResource(name, resourcePath);
    if (!resource) throw new HttpError(404, "资源不存在");
    return { name, path: resourcePath, content: resource.content };
  });

  // 多段资源路径（`a/b/c.md`）
  app.get("/api/v1/skills/:name/files/*", async (req) => {
    const params = req.params as Record<string, string>;
    const name = params.name;
    const resourcePath = (params["*"] ?? "").replace(/^\//, "");
    const resource = skillManager.readResource(name, resourcePath);
    if (!resource) throw new HttpError(404, "资源不存在");
    return { name, path: resourcePath, content: resource.content };
  });

  app.post("/api/v1/skills/import", async (req) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const content = body.content ?? body.zip_base64;
    if (!content) throw new HttpError(422, "缺少 content（zip 的 base64）");
    let zip: AdmZip;
    try {
      zip = new AdmZip(Buffer.from(String(content), "base64"));
    } catch {
      throw new HttpError(422, "zip 解析失败");
    }
    const entries = zip.getEntries();
    if (!entries.some((e) => e.entryName.endsWith("SKILL.md"))) {
      throw new HttpError(422, "压缩包中缺少 SKILL.md");
    }
    // 路径穿越拦截
    for (const entry of entries) {
      if (entry.entryName.includes("..") || path.isAbsolute(entry.entryName)) {
        throw new HttpError(422, `压缩包含非法路径: ${entry.entryName}`);
      }
    }
    const root = entryName(entries[0].entryName);
    const target = path.join(settings.custom_skills_dir, root);
    fs.mkdirSync(target, { recursive: true });
    for (const entry of entries) {
      if (entry.isDirectory) continue;
      const rel = entry.entryName.startsWith(`${root}/`)
        ? entry.entryName.slice(root.length + 1)
        : entry.entryName;
      if (!rel) continue;
      const dest = path.join(target, rel);
      if (!dest.startsWith(target)) throw new HttpError(422, "非法路径");
      fs.mkdirSync(path.dirname(dest), { recursive: true });
      fs.writeFileSync(dest, entry.getData());
    }
    skillManager.syncToDb();
    return { ok: true, imported: root, path: target };
  });

  app.post("/api/v1/skills/reload", async () => {
    const result = skillManager.syncToDb();
    logger.info("Skill 已重新加载", { synced: result.synced });
    return { ok: true, ...result, skills: skillManager.listSummaries() };
  });
}

/** 取压缩包根目录名。 */
function entryName(firstEntry: string): string {
  const parts = firstEntry.split("/").filter(Boolean);
  return parts.length > 1 ? parts[0] : (parts[0] ?? "skill");
}
