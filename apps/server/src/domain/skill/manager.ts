/**
 * Skill 管理器（契约对齐：services/skill_manager.py）。
 *
 * 关键约束：
 * - **三级渐进披露**：目录 → 摘要 → 全文；
 * - top-k 匹配（`skill_match_top_k`）；
 * - 内置 Skill **只读保护**（可禁用，不可删除）；
 * - 内置目录与用户目录**合并**（同名以用户目录优先）；
 * - 路径穿越拦截。
 */
import fs from "node:fs";
import path from "node:path";
import yaml from "js-yaml";
import { getDb, fromJson, toJson } from "../../db/client.js";
import { utcNow, type SkillRecordRow } from "../../db/schema.js";
import { settings, type Settings } from "../../shared/config.js";
import { getLogger } from "../../shared/logger.js";

const logger = getLogger("skill.manager");

export interface SkillFrontmatter {
  name?: string;
  description?: string;
  version?: string;
  [key: string]: unknown;
}

export interface SkillInfo {
  name: string;
  description: string;
  source: "builtin" | "custom";
  path: string;
  enabled: boolean;
  stale: boolean;
  frontmatter: SkillFrontmatter;
  updated_at: string;
}

export interface SkillSummary {
  name: string;
  description: string;
  path: string;
  skill_md_path: string;
  skill_md_rel: string;
  resources: string[];
  source: string;
  enabled: boolean;
}

export interface SkillDetail extends SkillInfo {
  content: string;
  resources: string[];
}

/** 解析 SKILL.md 的 frontmatter。 */
export function parseFrontmatter(content: string): SkillFrontmatter {
  const match = /^---\r?\n([\s\S]*?)\r?\n---/.exec(content);
  if (!match) return {};
  try {
    const parsed = yaml.load(match[1]);
    return parsed && typeof parsed === "object"
      ? (parsed as SkillFrontmatter)
      : {};
  } catch (err) {
    logger.warn("Skill frontmatter 解析失败", { error: String(err) });
    return {};
  }
}

/** 校验路径不逃逸出 base 目录。 */
export function isInside(base: string, target: string): boolean {
  const resolvedBase = path.resolve(base);
  const resolved = path.resolve(target);
  return resolved === resolvedBase || resolved.startsWith(resolvedBase + path.sep);
}

export class SkillManager {
  private cache: Map<string, SkillInfo> | null = null;

  constructor(private readonly s: Settings = settings) {}

  /** 内置 + 用户目录合并（同名以用户目录优先）。 */
  private scan(): Map<string, SkillInfo> {
    const map = new Map<string, SkillInfo>();
    const roots: Array<[string, "builtin" | "custom"]> = [
      [this.s.builtin_skills_dir, "builtin"],
      [this.s.custom_skills_dir, "custom"],
    ];
    for (const [root, source] of roots) {
      if (!root || !fs.existsSync(root)) continue;
      let entries: string[] = [];
      try {
        entries = fs.readdirSync(root);
      } catch {
        continue;
      }
      for (const entry of entries) {
        const dir = path.join(root, entry);
        const skillFile = path.join(dir, "SKILL.md");
        if (!fs.existsSync(skillFile)) continue;
        let content = "";
        try {
          content = fs.readFileSync(skillFile, "utf-8");
        } catch {
          continue;
        }
        const fm = parseFrontmatter(content);
        const name = String(fm.name ?? entry);
        const info: SkillInfo = {
          name,
          description: String(fm.description ?? ""),
          source,
          path: dir,
          enabled: true,
          stale: false,
          frontmatter: fm,
          updated_at: utcNow(),
        };
        // 用户目录覆盖内置（同名）
        if (source === "custom" || !map.has(name)) {
          map.set(name, info);
        }
      }
    }
    return map;
  }

  /** 列出全部 Skill（目录级信息）。 */
  listSkills(): SkillInfo[] {
    if (!this.cache) this.cache = this.scan();
    const db = getDb();
    const rows = db.prepare("SELECT * FROM skills").all() as SkillRecordRow[];
    const states = new Map(rows.map((r) => [r.name, r]));
    return [...this.cache.values()].map((info) => {
      const state = states.get(info.name);
      return {
        ...info,
        enabled: state ? Boolean(state.enabled) : true,
        stale: state ? Boolean(state.stale) : false,
        updated_at: state?.updated_at ?? info.updated_at,
      };
    });
  }

  /** 摘要列表（渐进披露第 1 层）——形态对齐 Python 侧 `SkillMeta`。 */
  listSummaries(): SkillSummary[] {
    return this.listSkills().map((s) => {
      let resources: string[] = [];
      try {
        resources = fs
          .readdirSync(s.path)
          .filter((f) => f !== "SKILL.md")
          .map((f) => f);
      } catch {
        resources = [];
      }
      return {
        name: s.name,
        description: s.description,
        path: s.path,
        skill_md_path: path.join(s.path, "SKILL.md"),
        skill_md_rel: path.relative(this.s.builtin_skills_dir, s.path),
        resources,
        source: s.source,
        enabled: s.enabled,
      };
    });
  }

  /** 取单个 Skill（详情层，含全文）。 */
  getSkill(name: string): SkillDetail | null {
    const info = this.listSkills().find((s) => s.name === name);
    if (!info) return null;
    const skillFile = path.join(info.path, "SKILL.md");
    let content = "";
    try {
      content = fs.readFileSync(skillFile, "utf-8");
    } catch {
      content = "";
    }
    let resources: string[] = [];
    try {
      resources = fs
        .readdirSync(info.path)
        .filter((f) => f !== "SKILL.md")
        .map((f) => f);
    } catch {
      resources = [];
    }
    return { ...info, content, resources };
  }

  /** top-k 匹配（按关键词打分）。 */
  matchSkills(query: string, topK = settings.skill_match_top_k as number): SkillInfo[] {
    const q = (query ?? "").trim().toLowerCase();
    const pool = this.listSkills();
    if (!q) return pool.slice(0, topK);
    const scored = pool
      .map((s) => {
        const hay = `${s.name} ${s.description}`.toLowerCase();
        let score = 0;
        if (hay.includes(q)) score += 2;
        for (const token of q.split(/\s+/).filter(Boolean)) {
          if (hay.includes(token)) score += 1;
        }
        return { s, score };
      })
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score);
    return scored.slice(0, topK).map((x) => x.s);
  }

  /** 读取 Skill 目录下的资源文件（路径穿越拦截）。 */
  readResource(name: string, resourcePath: string): { content: string; path: string } | null {
    const info = this.listSkills().find((s) => s.name === name);
    if (!info) return null;
    if (!isInside(info.path, path.join(info.path, resourcePath))) return null;
    const target = path.join(info.path, resourcePath);
    if (!fs.existsSync(target) || !fs.statSync(target).isFile()) return null;
    return { content: fs.readFileSync(target, "utf-8"), path: target };
  }

  /** 写入 Skill 目录下的资源文件。 */
  writeResource(name: string, resourcePath: string, content: string): boolean {
    const info = this.listSkills().find((s) => s.name === name);
    if (!info) return false;
    const target = path.join(info.path, resourcePath);
    if (!isInside(info.path, target)) return false;
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, content, "utf-8");
    return true;
  }

  /** 新建自定义 Skill。 */
  createSkill(name: string, description: string, content?: string): SkillInfo {
    if (!/^[A-Za-z0-9_-]+$/.test(name)) {
      throw new Error(`非法 Skill 名称: ${name}`);
    }
    const dir = path.join(this.s.custom_skills_dir, name);
    if (fs.existsSync(dir)) throw new Error(`Skill 已存在: ${name}`);
    fs.mkdirSync(dir, { recursive: true });
    const body =
      content ??
      `---\nname: ${name}\ndescription: ${description}\n---\n\n# ${name}\n\n${description}\n`;
    fs.writeFileSync(path.join(dir, "SKILL.md"), body, "utf-8");
    this.cache = null;
    return {
      name,
      description,
      source: "custom",
      path: dir,
      enabled: true,
      stale: false,
      frontmatter: { name, description },
      updated_at: utcNow(),
    };
  }

  /** 删除 Skill（内置只读保护）。 */
  deleteSkill(name: string): boolean {
    const info = this.listSkills().find((s) => s.name === name);
    if (!info) return false;
    if (info.source === "builtin") {
      throw new Error("内置 Skill 不可删除（可禁用）");
    }
    fs.rmSync(info.path, { recursive: true, force: true });
    this.cache = null;
    this.getDbDelete(name);
    return true;
  }

  private getDbDelete(name: string): void {
    getDb().prepare("DELETE FROM skills WHERE name = ?").run(name);
  }

  /** 更新 Skill 元信息 / 内容。 */
  updateSkill(
    name: string,
    updates: { description?: string; content?: string },
  ): SkillInfo | null {
    const info = this.listSkills().find((s) => s.name === name);
    if (!info) return null;
    if (info.source === "builtin" && updates.content !== undefined) {
      throw new Error("内置 Skill 内容只读（可新建自定义 Skill 覆盖）");
    }
    const skillFile = path.join(info.path, "SKILL.md");
    let content = updates.content;
    if (content === undefined) {
      content = fs.existsSync(skillFile) ? fs.readFileSync(skillFile, "utf-8") : "";
    }
    if (updates.description !== undefined) {
      const fm = parseFrontmatter(content);
      const merged = { ...fm, name, description: updates.description };
      const body = /^---\r?\n([\s\S]*?)\r?\n---/.exec(content);
      const rest = body ? content.slice(body[0].length) : content;
      content = `---\n${yaml.dump(merged, { lineWidth: -1 })}---${rest}`;
    }
    fs.writeFileSync(skillFile, content, "utf-8");
    this.cache = null;
    return this.listSkills().find((s) => s.name === name) ?? null;
  }

  /** 启用 / 禁用。 */
  toggleSkill(name: string, enabled?: boolean): SkillInfo | null {
    const info = this.listSkills().find((s) => s.name === name);
    if (!info) return null;
    const db = getDb();
    const now = utcNow();
    const current = db.prepare("SELECT * FROM skills WHERE name = ?").get(name) as
      | SkillRecordRow
      | undefined;
    const next = enabled ?? !(current ? Boolean(current.enabled) : true);
    if (current) {
      db.prepare("UPDATE skills SET enabled = ?, updated_at = ? WHERE name = ?").run(
        next ? 1 : 0,
        now,
        name,
      );
    } else {
      db.prepare(
        `INSERT INTO skills (name, description, source, path, frontmatter_json, enabled, stale, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, 0, ?)`,
      ).run(
        name,
        info.description,
        info.source,
        info.path,
        toJson(info.frontmatter),
        next ? 1 : 0,
        now,
      );
    }
    this.cache = null;
    return this.listSkills().find((s) => s.name === name) ?? null;
  }

  /** 把 Skill 元信息同步到 DB（启动时调用）。 */
  syncToDb(): { synced: number; warnings: string[] } {
    const db = getDb();
    const warnings: string[] = [];
    let synced = 0;
    const now = utcNow();
    for (const info of this.listSkills()) {
      const existing = db.prepare("SELECT * FROM skills WHERE name = ?").get(info.name) as
        | SkillRecordRow
        | undefined;
      if (existing) {
        db.prepare(
          "UPDATE skills SET description = ?, source = ?, path = ?, frontmatter_json = ?, stale = 0, updated_at = ? WHERE name = ?",
        ).run(
          info.description,
          info.source,
          info.path,
          toJson(info.frontmatter),
          now,
          info.name,
        );
      } else {
        db.prepare(
          `INSERT INTO skills (name, description, source, path, frontmatter_json, enabled, stale, updated_at)
           VALUES (?, ?, ?, ?, ?, 1, 0, ?)`,
        ).run(
          info.name,
          info.description,
          info.source,
          info.path,
          toJson(info.frontmatter),
          now,
        );
      }
      synced += 1;
    }
    // 标记磁盘已删除的 Skill
    const present = new Set(this.listSkills().map((s) => s.name));
    const rows = db.prepare("SELECT name FROM skills").all() as Array<{ name: string }>;
    for (const row of rows) {
      if (!present.has(row.name)) {
        db.prepare("UPDATE skills SET stale = 1, updated_at = ? WHERE name = ?").run(
          now,
          row.name,
        );
        warnings.push(`Skill 已从磁盘移除: ${row.name}`);
      }
    }
    return { synced, warnings };
  }

  /** 导出 Skill 为 zip 内容（简化：返回目录内文件清单）。 */
  exportSkill(name: string): { name: string; files: Array<{ path: string; content: string }> } | null {
    const info = this.listSkills().find((s) => s.name === name);
    if (!info) return null;
    const files: Array<{ path: string; content: string }> = [];
    const walk = (dir: string, rel: string): void => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (entry.name.startsWith(".")) continue;
        const full = path.join(dir, entry.name);
        const relPath = rel ? `${rel}/${entry.name}` : entry.name;
        if (entry.isDirectory()) walk(full, relPath);
        else if (entry.isFile()) {
          files.push({ path: relPath, content: fs.readFileSync(full, "utf-8") });
        }
      }
    };
    walk(info.path, "");
    return { name: info.name, files };
  }

  /** 构造 system prompt 中的 Skill 片段。 */
  buildSystemPrompt(selected: string[] | null, mode: "chat" | "work"): string {
    const skills = this.listSkills();
    if (mode === "chat" && (!selected || !selected.length)) return "";
    const picked = selected?.length
      ? skills.filter((s) => selected.includes(s.name))
      : mode === "work"
        ? skills
        : [];
    if (!picked.length) return "";
    const lines = picked.map((s) => `- ${s.name}: ${s.description}`);
    return `## 可用 Skill\n${lines.join("\n")}`;
  }
}

/** 全局单例。 */
export const skillManager = new SkillManager();
