/**
 * Team 服务（契约对齐：services/team_service.py）。
 *
 * 一组 Skill + 提示词前缀 + 编排策略（none / sequential / router）。
 */
import { getDb, fromJson, toJson } from "../../db/client.js";
import { newId, utcNow, type TeamRow } from "../../db/schema.js";
import { getLogger } from "../../shared/logger.js";

const logger = getLogger("team");

export interface TeamOut {
  id: string;
  name: string;
  description: string;
  prompt_prefix: string;
  strategy: string;
  enabled: boolean;
  members: Array<{ skill_name: string; position: number }>;
  created_at: string;
  updated_at: string;
}

export class TeamService {
  create(payload: {
    name: string;
    description?: string;
    prompt_prefix?: string;
    strategy?: string;
    members?: string[];
  }): TeamOut {
    const db = getDb();
    const id = newId();
    const now = utcNow();
    const strategy = payload.strategy ?? "none";
    if (!["none", "sequential", "router"].includes(strategy)) {
      throw new Error(`未知的编排策略: ${strategy}`);
    }
    db.prepare(
      `INSERT INTO teams (id, name, description, prompt_prefix, strategy, enabled, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, 1, ?, ?)`,
    ).run(
      id,
      payload.name,
      payload.description ?? "",
      payload.prompt_prefix ?? "",
      strategy,
      now,
      now,
    );
    this.setMembers(id, payload.members ?? []);
    return this.get(id)!;
  }

  list(): TeamOut[] {
    const db = getDb();
    const rows = db.prepare("SELECT * FROM teams ORDER BY updated_at DESC").all() as TeamRow[];
    return rows.map((r) => this.toOut(r));
  }

  get(teamId: string): TeamOut | null {
    const db = getDb();
    const row = db.prepare("SELECT * FROM teams WHERE id = ?").get(teamId) as TeamRow | undefined;
    return row ? this.toOut(row) : null;
  }

  update(
    teamId: string,
    updates: {
      description?: string;
      prompt_prefix?: string;
      strategy?: string;
      members?: string[];
    },
  ): TeamOut | null {
    const db = getDb();
    const row = db.prepare("SELECT * FROM teams WHERE id = ?").get(teamId) as TeamRow | undefined;
    if (!row) return null;
    const strategy = updates.strategy ?? row.strategy;
    if (!["none", "sequential", "router"].includes(strategy)) {
      throw new Error(`未知的编排策略: ${strategy}`);
    }
    db.prepare(
      "UPDATE teams SET description = ?, prompt_prefix = ?, strategy = ?, updated_at = ? WHERE id = ?",
    ).run(
      updates.description ?? row.description,
      updates.prompt_prefix ?? row.prompt_prefix,
      strategy,
      utcNow(),
      teamId,
    );
    if (updates.members) this.setMembers(teamId, updates.members);
    return this.get(teamId);
  }

  delete(teamId: string): boolean {
    const db = getDb();
    const row = db.prepare("SELECT id FROM teams WHERE id = ?").get(teamId);
    if (!row) return false;
    db.prepare("DELETE FROM team_skills WHERE team_id = ?").run(teamId);
    db.prepare("DELETE FROM teams WHERE id = ?").run(teamId);
    return true;
  }

  toggle(teamId: string, enabled?: boolean): TeamOut | null {
    const db = getDb();
    const row = db.prepare("SELECT * FROM teams WHERE id = ?").get(teamId) as TeamRow | undefined;
    if (!row) return null;
    const next = enabled ?? !row.enabled;
    db.prepare("UPDATE teams SET enabled = ?, updated_at = ? WHERE id = ?").run(
      next ? 1 : 0,
      utcNow(),
      teamId,
    );
    return this.get(teamId);
  }

  /**
   * 解析团队应启用的 Skill（router 策略按关键词匹配）。
   */
  resolve(teamId: string, query: string): { skills: string[]; strategy: string } {
    const team = this.get(teamId);
    if (!team) return { skills: [], strategy: "none" };
    const names = team.members.map((m) => m.skill_name);
    if (team.strategy !== "router") {
      return { skills: names, strategy: team.strategy };
    }
    const q = (query ?? "").toLowerCase();
    const scored = names
      .map((n) => ({ n, score: q && n.toLowerCase().includes(q) ? 1 : 0 }))
      .filter((x) => x.score > 0);
    return { skills: scored.length ? scored.map((x) => x.n) : names.slice(0, 1), strategy: team.strategy };
  }

  private setMembers(teamId: string, members: string[]): void {
    const db = getDb();
    db.prepare("DELETE FROM team_skills WHERE team_id = ?").run(teamId);
    const stmt = db.prepare(
      "INSERT INTO team_skills (team_id, skill_name, position) VALUES (?, ?, ?)",
    );
    members.forEach((name, idx) => stmt.run(teamId, name, idx));
  }

  private toOut(row: TeamRow): TeamOut {
    const db = getDb();
    const members = db
      .prepare("SELECT skill_name, position FROM team_skills WHERE team_id = ? ORDER BY position")
      .all(row.id) as Array<{ skill_name: string; position: number }>;
    return {
      id: row.id,
      name: row.name,
      description: row.description,
      prompt_prefix: row.prompt_prefix,
      strategy: row.strategy,
      enabled: Boolean(row.enabled),
      members: members.map((m) => ({ skill_name: m.skill_name, position: m.position })),
      created_at: row.created_at,
      updated_at: row.updated_at,
    };
  }
}

/** 全局单例。 */
export const teamService = new TeamService();
