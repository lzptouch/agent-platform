/**
 * 工作空间注册表与当前选择（契约对齐：services/workspace/service.py）。
 *
 * 把「工作目录」升格为一等资源：创建 / 列表 / 切换 / 归档；run 绑定独立
 * `workspace_id`（运行期不随全局切换变化）。
 */
import crypto from "node:crypto";
import path from "node:path";
import { getDb } from "../../db/client.js";
import { utcNow, type WorkspaceRow } from "../../db/schema.js";
import { settings } from "../../shared/config.js";
import { getLogger } from "../../shared/logger.js";
import * as mf from "./manifest.js";

const logger = getLogger("workspace");

/** 全局工作区目录（可被用户切换）。 */
let currentWorkspaceDir: string = settings.default_workspace_dir;

export function getWorkspaceDir(): string {
  return currentWorkspaceDir;
}

export function setWorkspaceDir(dir: string): void {
  currentWorkspaceDir = dir;
}

/** 生成新的工作空间 ID（`wb-{日期}-{短ID}`）。 */
export function newWorkspaceId(): string {
  const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  return `wb-${stamp}-${crypto.randomUUID().replace(/-/g, "").slice(0, 6)}`;
}

export interface Workspace {
  id: string;
  name: string;
  root_path: string;
  status: string;
  created_at: string;
}

export class WorkspaceService {
  private currentId: string | null = null;

  /**
   * 创建工作空间。
   *
   * - 指定 `rootPath`：以该目录为工作空间根（复用用户目录）；
   * - 未指定：在 `settings.data_dir` 下自动创建 `wb-{日期}-{短ID}/` 独立目录。
   */
  create(name: string, rootPath: string | null = null): Workspace {
    const wsId = newWorkspaceId();
    let container: string;
    let wsRoot: string;
    let dirName: string;
    if (rootPath) {
      wsRoot = path.resolve(rootPath.replace(/^~(?=$|\/)/, process.env.HOME ?? "~"));
      container = path.dirname(wsRoot);
      dirName = path.basename(wsRoot);
    } else {
      container = settings.data_dir_abs;
      wsRoot = path.join(container, wsId);
      dirName = wsId;
    }
    mf.ensureLayout(container, dirName);
    mf.writeManifest(container, dirName, {});

    const db = getDb();
    db.prepare(
      `INSERT INTO workspaces (id, name, root_path, status, manifest_json, created_at, updated_at)
       VALUES (?, ?, ?, 'active', '{}', ?, ?)`,
    ).run(wsId, name || wsId, wsRoot, utcNow(), utcNow());
    logger.info("创建工作空间", { wsId, wsRoot });
    return { id: wsId, name: name || wsId, root_path: wsRoot, status: "active", created_at: utcNow() };
  }

  list(includeArchived = false): Workspace[] {
    const db = getDb();
    const sql = includeArchived
      ? "SELECT * FROM workspaces ORDER BY updated_at DESC"
      : "SELECT * FROM workspaces WHERE status = 'active' ORDER BY updated_at DESC";
    const rows = db.prepare(sql).all() as WorkspaceRow[];
    return rows.map((r) => ({
      id: r.id,
      name: r.name,
      root_path: r.root_path,
      status: r.status,
      created_at: r.created_at,
    }));
  }

  get(workspaceId: string): Workspace | null {
    const db = getDb();
    const row = db.prepare("SELECT * FROM workspaces WHERE id = ?").get(workspaceId) as
      | WorkspaceRow
      | undefined;
    if (!row) return null;
    return {
      id: row.id,
      name: row.name,
      root_path: row.root_path,
      status: row.status,
      created_at: row.created_at,
    };
  }

  /** 切换当前工作空间（立即生效；**不影响**已绑定 run 的工作空间）。 */
  switch(workspaceId: string): Workspace {
    const ws = this.get(workspaceId);
    if (!ws) throw new Error(`工作空间不存在: ${workspaceId}`);
    if (ws.status !== "active") throw new Error(`工作空间已归档: ${workspaceId}`);
    this.currentId = workspaceId;
    setWorkspaceDir(ws.root_path);
    return ws;
  }

  /** 归档（**不删磁盘文件**）。 */
  archive(workspaceId: string): boolean {
    const db = getDb();
    const row = db.prepare("SELECT id FROM workspaces WHERE id = ?").get(workspaceId);
    if (!row) return false;
    db.prepare("UPDATE workspaces SET status = 'archived', updated_at = ? WHERE id = ?").run(
      utcNow(),
      workspaceId,
    );
    return true;
  }

  current(): Workspace | null {
    if (this.currentId === null) return null;
    return this.get(this.currentId);
  }

  /**
   * 为一次 run 解析工作空间：未指定则自动创建独立空间。
   *
   * 返回 `[workspace_id, workspace_root]`。结果写入 run 的 meta_json，
   * 运行期锁死（不随全局切换变化）。
   */
  bindForRun(workspaceId: string | null = null, name = ""): { id: string; root_path: string } {
    if (workspaceId) {
      const ws = this.get(workspaceId);
      if (!ws) throw new Error(`工作空间不存在: ${workspaceId}`);
      return { id: ws.id, root_path: ws.root_path };
    }
    const ws = this.create(name || "auto");
    return { id: ws.id, root_path: ws.root_path };
  }

  /** 复位（测试用）。 */
  resetForTest(): void {
    this.currentId = null;
    currentWorkspaceDir = settings.default_workspace_dir;
  }
}

/** 全局服务单例。 */
export const workspaceService = new WorkspaceService();
