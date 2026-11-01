/**
 * 权限判定引擎（契约对齐：services/security/permissions.py）。
 *
 * 分两层：
 * - **纯函数层** `decide(request, rules)` —— 输入请求 + 规则集，输出裁决，
 *   不碰 DB / 不碰全局状态，便于契约测试冻结语义；
 * - **服务层** `PermissionService` —— 单例 + 规则缓存 + 阻塞式审批。
 *
 * 判定语义：
 *  1. 归一化（policy.ts）；
 *  2. scope 分流（只在同 scope 内匹配）；
 *  3. priority 升序匹配，最长前缀/后缀命中；
 *  4. 同优先级冲突裁决 `deny > ask > allow`；
 *  5. 未命中 → 信任分层回落（L0 只读 / L1 工作区内常规读写 / L2 越界写 / L3 破坏性 / L4 禁止路径）。
 */
import path from "node:path";
import { getDb, fromJson, toJson } from "../../db/client.js";
import { utcNow, type PermissionRuleRow } from "../../db/schema.js";
import { settings } from "../../shared/config.js";
import { getLogger } from "../../shared/logger.js";
import { bus } from "../../http/events.js";
import * as policy from "./policy.js";
import { getWorkspaceDir } from "../workspace/service.js";

const logger = getLogger("security.permissions");

export const DENY = "deny";
export const ASK = "ask";
export const ALLOW = "allow";

/** 合法决定集合。 */
export const DECISIONS = [DENY, ASK, ALLOW] as const;
/** 规则作用域。 */
export const SCOPES = ["tool", "file", "command", "network", "action"] as const;

export const HIGH_RISK_ACTIONS = new Set([
  "batch_delete",
  "system_config_write",
  "external_script_exec",
]);

/** 只读工具（L0 信任分层，直接放行）。 */
export const READONLY_TOOLS = new Set(["read_file", "list_directory", "search_files"]);

/** 危险工具（定时任务需二次开关 `allow_dangerous_tools` 才放行）。 */
export const DANGEROUS_TOOLS = new Set(["write_file", "execute_python", "execute_bash"]);

/** 旧 API 的 scope 别名（旧名 → 现行名）。 */
export const SCOPE_ALIASES: Record<string, string> = { path: "file" };

/** 权限档位。 */
export const LEVELS = ["readonly", "ask", "allow"] as const;
export const LEVEL_TO_DECISION: Record<string, string> = {
  readonly: DENY,
  ask: ASK,
  allow: ALLOW,
};

/**
 * 内置权限规则清单（**唯一真相源**）—— `[scope, pattern, decision, risk, priority]`。
 *
 * 由 `ensure_builtin_rules` 在**启动时**统一收敛（去重 + 补齐，幂等）。
 */
export const BUILTIN_RULES: Array<[string, string, string, string, number]> = [
  // 禁止路径（直接 deny，不询问）
  ["file", "~/.ssh/**", "deny", "critical", 1],
  ["file", "~/.gnupg/**", "deny", "critical", 1],
  ["file", "~/.aws/**", "deny", "critical", 1],
  ["file", "~/.kube/**", "deny", "critical", 1],
  // 危险命令前缀（deny）
  ["command", "rm -rf /", "deny", "critical", 1],
  ["command", "mkfs", "deny", "critical", 1],
  ["command", "shutdown", "deny", "critical", 1],
  ["command", "reboot", "deny", "critical", 1],
  ["command", "format", "deny", "critical", 1],
  ["command", "reg delete", "deny", "elevated", 2],
  ["command", "taskkill /f", "deny", "elevated", 2],
  // 只读工具（allow）
  ["tool", "read_file", "allow", "normal", 100],
  ["tool", "list_directory", "allow", "normal", 100],
  ["tool", "search_files", "allow", "normal", 100],
  // 产物登记（只登记元数据，不写文件）→ 放行
  ["tool", "emit_artifact", "allow", "normal", 100],
  // 写类 / 执行类工具（ask）
  ["tool", "write_file", "ask", "normal", 100],
  ["tool", "execute_python", "ask", "elevated", 100],
  ["tool", "execute_bash", "ask", "elevated", 100],
  // 高危动作
  ["action", "batch_delete", "deny", "critical", 1],
  ["action", "system_config_write", "deny", "critical", 1],
  ["action", "external_script_exec", "ask", "elevated", 5],
];

export interface Rule {
  id: number | null;
  scope: string;
  pattern: string;
  decision: string;
  risk: string;
  workspace_id: string | null;
  priority: number;
}

/** 规则行 → 旧 API 形态的 dict。 */
export function ruleToDict(row: PermissionRuleRow): Record<string, unknown> {
  return {
    id: row.id,
    scope: row.scope,
    pattern: row.pattern,
    target: row.pattern,
    decision: row.decision,
    risk: row.risk,
    workspace_id: row.workspace_id,
    priority: row.priority,
    origin: row.origin,
    expires_at: row.expires_at,
    hit_count: row.hit_count ?? 0,
    last_hit_at: row.last_hit_at,
    updated_at: row.updated_at,
  };
}

export interface PermissionRequest {
  tool: string;
  action?: string | null;
  path?: string | null;
  command?: string | null;
  network?: { host: string; port?: number | null; is_local?: boolean } | null;
  workspace_id?: string | null;
  workspace_root?: string | null;
}

export interface Decision {
  decision: string;
  reason: string;
  scope: string;
  target: string;
  risk: string;
  matched_rule: Rule | null;
}

function severity(decision: string): number {
  return decision === "deny" ? 2 : decision === "ask" ? 1 : 0;
}

/** 在同 scope 内按 priority 升序 + 最长命中匹配。 */
function matchRules(
  scope: string,
  candidate: string,
  rules: Rule[],
  workspaceId: string | null,
): Rule | null {
  const matched: Rule[] = [];
  for (const rule of rules) {
    if (rule.scope !== scope) continue;
    if (rule.workspace_id !== null && rule.workspace_id !== workspaceId) continue;
    if (patternHit(rule, scope, candidate)) matched.push(rule);
  }
  if (!matched.length) return null;
  matched.sort((a, b) => a.priority - b.priority || b.pattern.length - a.pattern.length);
  const bestPriority = matched[0].priority;
  const top = matched.filter((r) => r.priority === bestPriority);
  for (const d of [DENY, ASK, ALLOW]) {
    const hit = top.find((r) => r.decision === d);
    if (hit) return hit;
  }
  return top[0];
}

function patternHit(rule: Rule, scope: string, candidate: string): boolean {
  if (scope === "file") {
    if (rule.pattern.includes("*")) {
      return policy.pathMatchesPattern(candidate, rule.pattern);
    }
    // 无通配符 → 目录/文件前缀（归一化 + 分隔符边界）
    const pat = rule.pattern.startsWith("~")
      ? policy.normalizePath(rule.pattern)
      : rule.pattern;
    const normalized = process.platform === "win32" ? pat.toLowerCase() : pat;
    const boundary = normalized.replace(/[/\\]+$/, "");
    return (
      candidate === normalized ||
      candidate.startsWith(boundary + path.sep) ||
      candidate.startsWith(boundary + "/")
    );
  }
  if (scope === "command") return candidate.startsWith(rule.pattern);
  if (scope === "network") {
    return candidate === rule.pattern || candidate.endsWith(rule.pattern.replace(/^\*/, ""));
  }
  // tool / action：前缀匹配
  return candidate === rule.pattern || candidate.startsWith(rule.pattern);
}

/** 读类动作的工具名（用于「只读可信根」的判定）。 */
const READ_TOOLS = ["read_file", "list_directory", "list_files", "read", "grep", "glob"];

function isReadAction(request: PermissionRequest): boolean {
  const tool = (request.tool ?? "").trim().toLowerCase();
  const action = (request.action ?? "").trim().toLowerCase();
  if (action.startsWith("read") || action.startsWith("list")) return true;
  return READ_TOOLS.some((t) => tool === t || tool.startsWith(`${t}_`));
}

/** 路径是否位于**技能目录**（只读可信根）之下。 */
function underTrustedReadRoot(target: string): boolean {
  const roots = [settings.builtin_skills_dir, settings.custom_skills_dir].filter(Boolean);
  if (!roots.length) return false;
  return roots.some((root) => isUnder(target, root));
}

/** 判断 path 是否位于 root 之下（两侧都做 Windows 大小写与分隔符归一）。 */
export function isUnder(target: string, root: string): boolean {
  const p = path.normalize(target).replace(/\\/g, "/").toLowerCase();
  const r = path.normalize(root).replace(/\\/g, "/").toLowerCase();
  return p === r || p.startsWith(r.replace(/\/+$/, "") + "/");
}

/** 纯函数裁决：命中规则则按规则，未命中则按信任分层回落。 */
export function decide(request: PermissionRequest, rules: Rule[]): Decision {
  const wsRoot = request.workspace_root ?? getWorkspaceDir();
  let req = request;

  // 防御纵深：路径在此归一化（即便调用方未归一）
  if (request.path !== null && request.path !== undefined) {
    // 归一化的基准必须与**执行器**完全一致（以 run 绑定的工作区根解析）
    const cwd = request.workspace_root ?? null;
    req = {
      ...request,
      path: policy.normalizePath(request.path, cwd),
    };
  }

  // 0) 工具维度：deny 立即生效；ask 只作兜底
  const toolRule = req.tool
    ? matchRules("tool", req.tool, rules, req.workspace_id ?? null)
    : null;

  const toolDeny = (): Decision | null => {
    if (toolRule && toolRule.decision === DENY) {
      return {
        decision: DENY,
        reason: `工具 ${req.tool} 命中禁止规则 ${toolRule.pattern}`,
        scope: "tool",
        target: req.tool,
        risk: toolRule.risk,
        matched_rule: toolRule,
      };
    }
    return null;
  };

  // 1) 高危动作最先判定（不能被「工作区内 allow」放行）
  if (req.action && HIGH_RISK_ACTIONS.has(req.action)) {
    const rule = matchRules("action", req.action, rules, req.workspace_id ?? null);
    if (rule) {
      return {
        decision: rule.decision,
        reason: `高危动作 ${req.action}（命中规则）`,
        scope: "action",
        target: req.action,
        risk: rule.risk,
        matched_rule: rule,
      };
    }
    return {
      decision: req.action !== "external_script_exec" ? DENY : ASK,
      reason: `高危动作 ${req.action}（默认）`,
      scope: "action",
      target: req.action,
      risk: "critical",
      matched_rule: null,
    };
  }

  // 2) 文件维度
  if (req.path !== null && req.path !== undefined) {
    const rule = matchRules("file", req.path, rules, req.workspace_id ?? null);
    if (rule) {
      return {
        decision: rule.decision,
        reason:
          rule.decision === DENY
            ? `路径命中禁止规则 ${rule.pattern}`
            : `路径命中规则 ${rule.pattern}`,
        scope: "file",
        target: req.path,
        risk: rule.risk,
        matched_rule: rule,
      };
    }
    const deny = toolDeny();
    if (deny) return deny;
    // 信任分层：工作区内放行，工作区外写询问
    if (isUnder(req.path, wsRoot)) {
      return {
        decision: ALLOW,
        reason: "工作区内路径",
        scope: "file",
        target: req.path,
        risk: "normal",
        matched_rule: null,
      };
    }
    // 技能目录是只读可信根 → 读类动作放行
    if (isReadAction(req) && underTrustedReadRoot(req.path)) {
      return {
        decision: ALLOW,
        reason: "技能目录（只读可信根）",
        scope: "file",
        target: req.path,
        risk: "normal",
        matched_rule: null,
      };
    }
    return {
      decision: ASK,
      reason: "工作区外路径",
      scope: "file",
      target: req.path,
      risk: "elevated",
      matched_rule: null,
    };
  }

  // 3) 命令维度（串联逐段判定；取各段中最严的裁决）
  if (req.command !== null && req.command !== undefined) {
    let worst: Decision | null = null;
    for (const segment of policy.splitCommandSegments(req.command)) {
      const normText = policy.normalizeCommand(segment).tokens.join(" ");
      const rule = matchRules("command", normText, rules, req.workspace_id ?? null);
      if (rule) {
        const d: Decision = {
          decision: rule.decision,
          reason: `命令前缀命中规则 ${rule.pattern}`,
          scope: "command",
          target: normText,
          risk: rule.risk,
          matched_rule: rule,
        };
        if (!worst || severity(d.decision) > severity(worst.decision)) worst = d;
      }
    }
    if (worst) return worst;
    const deny = toolDeny();
    if (deny) return deny;
    if (toolRule && toolRule.decision === ASK) {
      return {
        decision: ASK,
        reason: `工具 ${req.tool} 命中规则 ${toolRule.pattern}`,
        scope: "tool",
        target: req.tool,
        risk: toolRule.risk,
        matched_rule: toolRule,
      };
    }
    return {
      decision: ASK,
      reason: "命令无显式规则",
      scope: "command",
      target: req.command,
      risk: "elevated",
      matched_rule: null,
    };
  }

  // 4) 网络维度
  if (req.network !== null && req.network !== undefined) {
    const host = req.network.host ?? "";
    if (req.network.is_local) {
      return {
        decision: ALLOW,
        reason: "本地地址",
        scope: "network",
        target: host,
        risk: "normal",
        matched_rule: null,
      };
    }
    const rule = matchRules("network", host, rules, req.workspace_id ?? null);
    if (rule) {
      return {
        decision: rule.decision,
        reason: `网络命中规则 ${rule.pattern}`,
        scope: "network",
        target: host,
        risk: rule.risk,
        matched_rule: rule,
      };
    }
    return {
      decision: ASK,
      reason: "未配置的外部网络地址",
      scope: "network",
      target: host,
      risk: "elevated",
      matched_rule: null,
    };
  }

  // 5) 工具维度（兜底）
  if (READONLY_TOOLS.has(req.tool)) {
    return {
      decision: ALLOW,
      reason: `只读工具 ${req.tool}`,
      scope: "tool",
      target: req.tool,
      risk: "normal",
      matched_rule: null,
    };
  }
  const rule = matchRules("tool", req.tool, rules, req.workspace_id ?? null);
  if (rule) {
    return {
      decision: rule.decision,
      reason: `工具命中规则 ${rule.pattern}`,
      scope: "tool",
      target: req.tool,
      risk: rule.risk,
      matched_rule: rule,
    };
  }
  return {
    decision: ASK,
    reason: `工具 ${req.tool}（默认）`,
    scope: "tool",
    target: req.tool,
    risk: "normal",
    matched_rule: null,
  };
}
