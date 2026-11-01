/**
 * 工作空间目录布局与 manifest 读写（契约对齐：services/workspace/manifest.py）。
 *
 * 布局：
 *   {container}/{workspace_id}/
 *   ├── .agent/               # 内部目录
 *   │   ├── manifest.json
 *   │   ├── memory/  snapshots/{seq}/  audit/  runtime/  locks/
 *   └── artifacts/            # 交付物（用户可见）
 */
import fs from "node:fs";
import path from "node:path";
import { getLogger } from "../../shared/logger.js";

const logger = getLogger("workspace.manifest");

export const INTERNAL_DIR = ".agent";
export const MANIFEST_NAME = "manifest.json";

export interface WorkspaceManifest {
  writable_roots: string[];
  default_policy: string;
  model: string | null;
  skills: string[];
  extensions: string[];
  snapshot_budget_mb: number;
  [key: string]: unknown;
}

export const DEFAULT_MANIFEST: WorkspaceManifest = {
  writable_roots: [],
  default_policy: "ask",
  model: null,
  skills: [],
  extensions: [],
  snapshot_budget_mb: 3000,
};

export function workspaceDir(root: string, workspaceId: string): string {
  return path.join(root, workspaceId);
}

/** 按约定创建工作空间目录布局，返回工作空间根。 */
export function ensureLayout(root: string, workspaceId: string): string {
  const base = workspaceDir(root, workspaceId);
  for (const sub of ["snapshots", "audit", "runtime", "locks", "memory"]) {
    fs.mkdirSync(path.join(base, INTERNAL_DIR, sub), { recursive: true });
  }
  fs.mkdirSync(path.join(base, "artifacts"), { recursive: true });
  return base;
}

export function manifestPath(root: string, workspaceId: string): string {
  return path.join(workspaceDir(root, workspaceId), INTERNAL_DIR, MANIFEST_NAME);
}

/** 读 manifest；不存在或损坏则返回默认。 */
export function readManifest(root: string, workspaceId: string): WorkspaceManifest {
  const p = manifestPath(root, workspaceId);
  if (!fs.existsSync(p)) return { ...DEFAULT_MANIFEST };
  try {
    const data = JSON.parse(fs.readFileSync(p, "utf-8")) as Partial<WorkspaceManifest>;
    return { ...DEFAULT_MANIFEST, ...data };
  } catch (err) {
    logger.warn("manifest 损坏，使用默认", { error: String(err) });
    return { ...DEFAULT_MANIFEST };
  }
}

/** 校验 manifest 更新（非法值 → 抛错，由路由转 422）。 */
export function validateManifest(updates: unknown): Partial<WorkspaceManifest> {
  if (typeof updates !== "object" || updates === null || Array.isArray(updates)) {
    throw new Error("manifest 必须是对象");
  }
  const out = { ...(updates as Partial<WorkspaceManifest>) };
  const roots = out.writable_roots;
  if (roots !== undefined && roots !== null) {
    if (!Array.isArray(roots) || roots.some((r) => typeof r !== "string")) {
      throw new Error("writable_roots 必须是字符串数组");
    }
  }
  const policy = out.default_policy;
  if (policy !== undefined && policy !== null) {
    if (!["allow", "ask", "deny"].includes(policy)) {
      throw new Error(`default_policy 必须是 allow / ask / deny 之一: ${policy}`);
    }
  }
  const model = out.model;
  if (model !== undefined && model !== null && typeof model !== "string") {
    throw new Error("model 必须是字符串或 null");
  }
  for (const key of ["skills", "extensions"] as const) {
    const val = out[key];
    if (val !== undefined && val !== null) {
      if (!Array.isArray(val) || val.some((v) => typeof v !== "string")) {
        throw new Error(`${key} 必须是字符串数组`);
      }
    }
  }
  return out;
}

/** 更新 manifest（合并写）。返回更新后的完整 manifest。 */
export function writeManifest(
  root: string,
  workspaceId: string,
  updates: unknown,
): WorkspaceManifest {
  const validated = validateManifest(updates);
  const manifest = readManifest(root, workspaceId);
  Object.assign(manifest, validated);
  if (!manifest.writable_roots?.length) {
    manifest.writable_roots = [workspaceDir(root, workspaceId)];
  }
  const p = manifestPath(root, workspaceId);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(manifest, null, 2), "utf-8");
  return manifest;
}

export function snapshotsDir(root: string, workspaceId: string): string {
  return path.join(workspaceDir(root, workspaceId), INTERNAL_DIR, "snapshots");
}

export function artifactsDir(root: string, workspaceId: string): string {
  return path.join(workspaceDir(root, workspaceId), "artifacts");
}
