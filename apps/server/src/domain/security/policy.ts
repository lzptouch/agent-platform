/**
 * 安全策略集与请求归一化（契约对齐：services/security/policy.py）。
 *
 * 全部是**纯函数**，不碰 DB、不碰全局可变状态 —— 便于契约测试冻结语义。
 *
 * 归一化三种请求：
 * - 文件路径：`~` 展开 → 绝对化 → 符号链接 resolve → `..` 归一 → 大小写/分隔符归一；
 * - 命令：去引号/重定向 → 拆 `;` / `&&` / `||` 逐段 → 取首 token 与前两 token 作前缀键；
 * - 网络：URL → host:port，判本地地址。
 */
import os from "node:os";
import path from "node:path";
import fs from "node:fs";

/** 把任意形态的路径归一到可直接比对的绝对路径。 */
export function normalizePath(raw: string, cwd?: string | null): string {
  let p = raw.startsWith("~")
    ? path.join(os.homedir(), raw.slice(1).replace(/^[/\\]/, ""))
    : raw;
  if (!path.isAbsolute(p)) {
    p = path.resolve(cwd ?? process.cwd(), p);
  }
  // resolve() 会解析符号链接并归一 `..`；文件不存在时也能工作
  let resolved: string;
  try {
    resolved = fs.realpathSync.native(p);
  } catch {
    resolved = path.resolve(p);
  }
  return process.platform === "win32" ? resolved.toLowerCase() : resolved;
}

/** glob 匹配（**支持 `**` 与 `*`**）。 */
export function pathMatchesPattern(target: string, pattern: string): boolean {
  const pat = pattern.startsWith("~") ? normalizePath(pattern) : pattern;
  const patNorm = pat.replace(/\\/g, "/");
  const pNorm = target.replace(/\\/g, "/");
  // 转义正则元字符（保留 `*`），再把 `**` -> `.*`、`*` -> `[^/]*`
  const escaped = patNorm.replace(/[.+^${}()|[\]\\]/g, "\\$&");
  const DOUBLE = "\u0000DOUBLE\u0000";
  const source = escaped
    .replace(/\*\*/g, DOUBLE)
    .replace(/\*/g, "[^/]*")
    .split(DOUBLE)
    .join(".*");
  return new RegExp(`^${source}$`).test(pNorm);
}

/** 是否本地地址（127.0.0.1 / localhost / ::1 / 空）。 */
export function isLocalAddress(host: string): boolean {
  const h = (host ?? "").trim().toLowerCase();
  return (
    ["127.0.0.1", "localhost", "::1", "0.0.0.0", ""].includes(h) || h.endsWith(".localhost")
  );
}

export interface NetworkTarget {
  host: string;
  port: number | null;
  is_local: boolean;
}

/** URL → `{host, port, is_local}`。 */
export function normalizeNetwork(url: string): NetworkTarget {
  let parsed: URL;
  try {
    parsed = new URL(url.includes("://") ? url : `http://${url}`);
  } catch {
    return { host: "", port: null, is_local: true };
  }
  const host = parsed.hostname ?? "";
  return {
    host,
    port: parsed.port ? Number(parsed.port) : null,
    is_local: isLocalAddress(host),
  };
}

/** 把串联命令拆成逐段（`a && b; c` → `[a, b, c]`）。 */
export function splitCommandSegments(command: string): string[] {
  return command
    .split(/(?:;|&&|\|\|)/)
    .map((p) => p.trim())
    .filter((p) => p.length > 0);
}

export interface NormalizedCommand {
  tokens: string[];
  first: string;
  prefix2: string;
}

/** 单段命令 → `{tokens, first, prefix2}`。 */
export function normalizeCommand(segment: string): NormalizedCommand {
  // 去重定向
  const seg = segment.replace(/[0-9]?>>?\s*\S+|[0-9]?<\s*\S+/g, "").trim();
  const tokens = splitTokens(seg);
  if (!tokens.length) return { tokens: [], first: "", prefix2: "" };
  return {
    tokens,
    first: tokens[0],
    prefix2: tokens.length >= 2 ? tokens.slice(0, 2).join(" ") : tokens[0],
  };
}

/** POSIX 风格的词法切分（处理引号）。 */
export function splitTokens(segment: string): string[] {
  const tokens: string[] = [];
  let current = "";
  let quote: string | null = null;
  let has = false;
  for (let i = 0; i < segment.length; i += 1) {
    const ch = segment[i];
    if (quote) {
      if (ch === quote) {
        quote = null;
      } else {
        current += ch;
      }
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      has = true;
      continue;
    }
    if (/\s/.test(ch)) {
      if (current || has) {
        tokens.push(current);
        current = "";
        has = false;
      }
      continue;
    }
    current += ch;
  }
  if (current || has) tokens.push(current);
  return tokens;
}

/** 递归守卫目录（批量删除这些目录需要审批）。 */
export const RECURSION_GUARD = ["~", "~/Desktop", "~/Downloads", "~/Documents"];

/** Python 代码危险调用标记。 */
export const PYTHON_DANGEROUS_PATTERNS = [
  "os.remove",
  "os.unlink",
  "shutil.rmtree",
  "shutil.rmtree(",
  "subprocess.call",
  "subprocess.run",
  "subprocess.Popen",
  "os.system",
  "eval(",
  "exec(",
];

/** 扫描 Python 代码中的危险调用，返回命中的标记列表。 */
export function pythonHasDangerousCalls(code: string): string[] {
  return PYTHON_DANGEROUS_PATTERNS.filter((p) => code.includes(p));
}

/**
 * 判定命令前缀是否命中危险清单。
 *
 * `forbidden` 元素是 `[pattern, decision]`；按**最长前缀**匹配。
 */
export function commandIsDangerousPrefix(
  prefix: string,
  forbidden: Array<[string, string]>,
): [string, string] | null {
  let best: [string, string] | null = null;
  for (const [pattern, decision] of forbidden) {
    if (prefix.startsWith(pattern) && (!best || pattern.length > best[0].length)) {
      best = [pattern, decision];
    }
  }
  return best;
}
