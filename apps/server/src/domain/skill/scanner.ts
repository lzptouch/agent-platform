/**
 * 插件目录扫描器（契约对齐：Python 侧 `app/services/chains/skills/scanner.py`）。
 *
 * **为什么需要**：`POST /api/v1/plugins/scan` 的**响应键**由前端直接消费
 * （`scanResult.level` / `scanResult.rejected_by_default` / `scanResult.findings[]`）→
 * TS 侧此前返回的是另一套形状（`{ok, path, scanned, issues, valid}`）→ 前端渲染为空。
 *
 * **等级语义**（与 Python 侧一致）：
 * - `low` —— 正常；
 * - `medium` —— 需要**提示确认**；
 * - `high` / `critical` —— **默认拒绝**，需显式确认。
 */
import fs from "node:fs";
import path from "node:path";

export const LEVELS = ["low", "medium", "high", "critical"] as const;
export type ScanLevel = (typeof LEVELS)[number];

const ORDER: Record<ScanLevel, number> = {
  low: 0,
  medium: 1,
  high: 2,
  critical: 3,
};

export interface ScanFinding {
  rule: string;
  level: ScanLevel;
  reason: string;
  path: string;
}

export interface ScanResult {
  level: ScanLevel;
  findings: ScanFinding[];
  scanned_files: number;
  total_bytes: number;
  requires_confirmation: boolean;
  rejected_by_default: boolean;
}

/** 取更严的等级。 */
export function maxLevel(a: ScanLevel, b: ScanLevel): ScanLevel {
  return ORDER[b] > ORDER[a] ? b : a;
}

/** 高危内容模式（与 Python 侧规则口径对齐的**保守子集**）。 */
const DANGEROUS_PATTERNS: Array<{ rule: string; level: ScanLevel; re: RegExp }> = [
  { rule: "curl_pipe_shell", level: "critical", re: /curl[^|]*\|\s*(ba)?sh/i },
  { rule: "rm_rf_root", level: "critical", re: /rm\s+-rf\s+(\/|~\/)/i },
  { rule: "credential_read", level: "high", re: /(\.ssh\/id_rsa|\.aws\/credentials|\.env\b)/i },
  { rule: "sudo_usage", level: "medium", re: /\bsudo\b/i },
  { rule: "base64_exec", level: "medium", re: /base64\s+(-d|--decode)[^|]*\|\s*(ba)?sh/i },
];

function emptyResult(): ScanResult {
  return {
    level: "low",
    findings: [],
    scanned_files: 0,
    total_bytes: 0,
    requires_confirmation: false,
    rejected_by_default: false,
  };
}

/** 扫描一个插件目录（每个子目录视为一个插件）。 */
export function scanDirectory(target: string): ScanResult {
  const result = emptyResult();
  if (!fs.existsSync(target) || !fs.statSync(target).isDirectory()) return result;

  const walk = (dir: string, rel: string): void => {
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const p = path.join(dir, entry.name);
      const relPath = rel ? `${rel}/${entry.name}` : entry.name;
      if (entry.isDirectory()) {
        walk(p, relPath);
        continue;
      }
      if (!entry.isFile()) continue;
      result.scanned_files += 1;
      try {
        result.total_bytes += fs.statSync(p).size;
      } catch {
        // 忽略
      }
      // 只对文本文件做内容规则匹配
      if (!/\.(md|txt|json|ya?ml|sh|py|js|ts)$/i.test(entry.name)) continue;
      let text = "";
      try {
        text = fs.readFileSync(p, "utf-8").slice(0, 200_000);
      } catch {
        continue;
      }
      for (const rule of DANGEROUS_PATTERNS) {
        if (!rule.re.test(text)) continue;
        result.findings.push({
          rule: rule.rule,
          level: rule.level,
          reason: `命中高危模式 ${rule.rule}`,
          path: relPath,
        });
        result.level = maxLevel(result.level, rule.level);
      }
    }
  };

  walk(target, "");

  // 每个插件目录必须有 SKILL.md
  for (const entry of fs.readdirSync(target, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const skillFile = path.join(target, entry.name, "SKILL.md");
    if (!fs.existsSync(skillFile)) {
      result.findings.push({
        rule: "missing_skill_md",
        level: "medium",
        reason: "缺少 SKILL.md",
        path: entry.name,
      });
      result.level = maxLevel(result.level, "medium");
    }
  }

  result.requires_confirmation =
    result.level === "medium" || result.level === "high" || result.level === "critical";
  result.rejected_by_default = result.level === "high" || result.level === "critical";
  return result;
}
