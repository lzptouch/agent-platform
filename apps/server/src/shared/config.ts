/**
 * 统一应用配置（契约冻结项，来源：backend/app/core/config.py）。
 *
 * - 单一来源：Zod schema 校验 `.env` + 环境变量；桌面态由壳注入 `AGENT_*`。
 * - 派生路径逐条对齐 Python 侧 `Settings` 的 `@property`（见 contract/env.json）。
 * - **阈值常量集中**（design §6.1-6）：所有限额放在 `LIMITS`，禁止散落。
 */
import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { z } from "zod";

// apps/server/src/shared/config.ts -> src/shared -> src -> apps/server
const THIS_DIR = path.dirname(fileURLToPath(import.meta.url));
export const APP_DIR = path.resolve(THIS_DIR, "..");
export const SERVER_DIR = path.resolve(APP_DIR, "..");

/**
 * 服务根（**含 `package.json` 的那一层**）。
 *
 * **P8-01 实测踩坑**：打包态的目录层级与开发态**不同**——
 * - 开发态：`apps/server/src/shared/config.js` → 服务根 = `apps/server`
 * - 打包态：`resources/server/shared/config.js`  → 服务根 = `resources/server`
 *
 * 若按固定层级上溯（`../../..`），打包态会多退一级 → `data_dir_abs` 等派生路径
 * 指到 `resources/` 下（应落在**用户数据目录**里）。故改为「向上找 package.json」。
 */
/** 服务包名（`package.json` 的 `name`）—— 允许带 scope 前缀。 */
const SERVER_PACKAGE_NAMES = new Set(["agent-server", "@agent/server"]);

function findServiceRoot(from: string): string {
  let dir = from;
  for (let i = 0; i < 6; i += 1) {
    const pkg = path.join(dir, "package.json");
    if (fs.existsSync(pkg)) {
      try {
        const meta = JSON.parse(fs.readFileSync(pkg, "utf-8")) as { name?: string };
        if (meta.name && SERVER_PACKAGE_NAMES.has(meta.name)) return dir;
      } catch {
        // 解析失败则继续上溯
      }
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  // 兜底：编译产物在 <root>/shared/config.js → 服务根 = 上一级
  return path.resolve(from, "..");
}

/** 服务根（打包态与开发态一致）。 */
export const SERVICE_ROOT = findServiceRoot(THIS_DIR);

/**
 * 应用根：**与 Python 侧 `PROJECT_ROOT` 同语义**（其下有 `skills/` 与 `data/`）。
 *
 * - 开发态：仓库根（`apps/server` → `apps` → 仓库根）
 * - 打包态：`resources/`（`resources/server` → `resources`，其下有 `skills/`）
 *
 * 判定方式：看 `skills/` 在哪一层（与 Python 侧 `PROJECT_ROOT.parent / "skills"`
 * 的落点对齐）——**不写死层级**，避免打包态多退/少退一级。
 */
function findAppRoot(serviceRoot: string): string {
  // 取**最外层**含非空 `skills/` 的祖先：
  // - 开发态：`apps/server` → `apps` → 仓库根（仓库根有 `skills/`，`apps/` 没有）
  // - 打包态：`resources/server` → `resources`（`resources/skills` ✓）
  // 用「最外层」而非「最内层」，避免被空目录（如历史遗留的 `apps/skills`）误导。
  let found = "";
  for (const up of [1, 2, 3]) {
    const candidate = path.resolve(serviceRoot, ...Array(up).fill(".."));
    const skills = path.join(candidate, "skills");
    try {
      if (fs.existsSync(skills) && fs.readdirSync(skills).length > 0) {
        found = candidate;
      }
    } catch {
      // 读不到就跳过
    }
  }
  return found || path.resolve(serviceRoot, "..");
}

/** 应用根（仓库根 / `resources/`）。 */
export const PROJECT_ROOT = findAppRoot(SERVICE_ROOT);

/** 读取布尔环境变量（1/true/yes/on 视为真）。 */
function envFlag(name: string, fallback = false): boolean {
  const raw = (process.env[name] ?? "").trim().toLowerCase();
  if (!raw) return fallback;
  return raw === "1" || raw === "true" || raw === "yes" || raw === "on";
}

function envInt(name: string, fallback: number): number {
  const raw = (process.env[name] ?? "").trim();
  if (!raw) return fallback;
  const n = Number.parseInt(raw, 10);
  return Number.isNaN(n) ? fallback : n;
}

function envStr(name: string, fallback = ""): string {
  return (process.env[name] ?? fallback).trim();
}

// --------------------------------------------------------------------------- //
// Zod schema（.env 文件 + 环境变量）
// --------------------------------------------------------------------------- //
const boolish = z
  .union([z.boolean(), z.string()])
  .transform((v) =>
    typeof v === "boolean"
      ? v
      : ["1", "true", "yes", "on"].includes(v.trim().toLowerCase()),
  );

const SettingsSchema = z.object({
  // ---------- 应用 ----------
  app_name: z.string().default("agent"),
  app_version: z.string().default("1.1.0"),
  debug: boolish.default(false),
  host: z.string().default("127.0.0.1"),
  port: z.coerce.number().int().default(8000),

  // ---------- 敏感信息处置 ----------
  sensitive_policy: z.enum(["allow", "encrypt", "deny"]).default("encrypt"),
  research_fact_check: boolish.default(true),

  // ---------- 主 LLM ----------
  dashscope_api_key: z.string().default(""),
  dashscope_base_url: z
    .string()
    .default("https://dashscope.aliyuncs.com/compatible-mode/v1"),
  default_model: z.string().default("qwen-plus"),
  max_tokens: z.coerce.number().int().default(8192),
  max_iterations: z.coerce.number().int().default(20),
  skill_match_top_k: z.coerce.number().int().default(3),
  reflection_max_rounds: z.coerce.number().int().default(2),
  exec_timeout: z.coerce.number().int().default(180),

  // ---------- 备选 LLM ----------
  llm_api_key: z.string().default(""),
  llm_base_url: z.string().default("https://api.deepseek.com/v1"),
  plan_model: z.string().default("deepseek-chat"),
  rag_model: z.string().default("deepseek-chat"),
  answer_model: z.string().default("deepseek-reasoner"),

  // ---------- OpenAI（Web Research 专用，可选） ----------
  openai_api_key: z.string().default(""),
  openai_base_url: z.string().default("https://api.openai.com/v1"),
  openai_model: z.string().default("gpt-4o"),

  // ---------- Web 形态最小鉴权（P6 起随 Web 端退场删除） ----------
  agent_api_key: z.string().default(""),

  // ---------- MCP 链路 ----------
  serper_api_key: z.string().default(""),
  gaode_api_key: z.string().default(""),
  mcp_max_servers: z.coerce.number().int().default(5),
  mcp_call_timeout: z.coerce.number().int().default(60),

  // ---------- RAG 链路 ----------
  milvus_db_path: z.string().default("data/milvus.db"),
  milvus_collection: z.string().default("hybrid_demo"),

  // ---------- Research 链路 ----------
  bocha_api_key: z.string().default(""),
  bocha_base_url: z.string().default("https://api.bocha.cn/v1/web-search"),
  bocha_default_count: z.coerce.number().int().default(10),
  bocha_summary: boolish.default(true),
  research_output_dir: z.string().default("data/research"),
  research_max_concurrent: z.coerce.number().int().default(3),
  research_persist: boolish.default(true),

  // ---------- 数据库 ----------
  database_url: z.string().default(""),
  db_echo: boolish.default(false),

  // ---------- 会话 / 双模式 ----------
  session_history_limit: z.coerce.number().int().default(10),
  session_history_max_chars: z.coerce.number().int().default(8000),
  chat_max_iterations: z.coerce.number().int().default(5),

  // ---------- 定时任务 ----------
  scheduler_enabled: boolish.default(true),
  tz: z.string().default("Asia/Shanghai"),
  schedule_run_timeout: z.coerce.number().int().default(600),
  schedule_max_concurrent: z.coerce.number().int().default(2),
  interactive_max_concurrent: z.coerce.number().int().default(4),
  interactive_queue_timeout: z.coerce.number().default(30.0),
  schedule_lease_ttl: z.coerce.number().int().default(60),
  schedule_lease_renew: z.coerce.number().int().default(20),
  schedule_daily_run_limit: z.coerce.number().int().default(100),
  schedule_task_soft_limit: z.coerce.number().int().default(200),
  schedule_stale_sweep_minutes: z.coerce.number().int().default(5),
  schedule_stale_sweep_grace: z.coerce.number().int().default(900),

  // ---------- 上下文经济性 ----------
  context_lazy_tool_loading: boolish.default(true),
  context_budget_ratio: z.coerce.number().default(0.85),
  context_compact_threshold: z.coerce.number().default(0.7),
  context_summary_threshold: z.coerce.number().default(0.85),
  context_keep_recent_turns: z.coerce.number().int().default(3),
  context_memory_enabled: boolish.default(true),
  context_memory_max: z.coerce.number().int().default(5),
  pricing_json: z.string().default(""),

  // ---------- 权限引擎 ----------
  permission_approval_timeout: z.coerce.number().int().default(120),
  permission_audit_enabled: boolish.default(true),

  // ---------- 日志 ----------
  log_to_file: boolish.default(true),
  log_file_name: z.string().default("app.log"),
  log_file_max_bytes: z.coerce.number().int().default(10 * 1024 * 1024),
  log_file_backup_count: z.coerce.number().int().default(5),
  log_file_level: z.string().default("DEBUG"),
  log_debug_sample_rate: z.coerce.number().default(0.2),

  // ---------- 执行边界 ----------
  exec_resource_limits: boolish.default(true),
  exec_cpu_seconds: z.coerce.number().int().default(60),
  exec_memory_bytes: z.coerce.number().int().default(1024 * 1024 * 1024),
  exec_open_files: z.coerce.number().int().default(256),
  exec_file_size_bytes: z.coerce.number().int().default(64 * 1024 * 1024),
  exec_max_output_bytes: z.coerce.number().int().default(64 * 1024),
  exec_workspace_escape_check: boolish.default(true),
  exec_network_enabled: boolish.default(false),

  // ---------- 上传限制 ----------
  upload_max_file_bytes: z.coerce.number().int().default(50 * 1024 * 1024),
  upload_max_request_bytes: z.coerce.number().int().default(100 * 1024 * 1024),
  upload_allowed_extensions: z.string().default(""),

  // ---------- CORS（P6 起删除） ----------
  cors_origins: z.string().default(""),
});

export type RawSettings = z.infer<typeof SettingsSchema>;

/** 解析 `.env`（仅开发态；桌面态由壳写 `userData/config.json`）。 */
function loadDotEnv(): Record<string, string> {
  const envPath = path.join(PROJECT_ROOT, ".env");
  const out: Record<string, string> = {};
  if (!fs.existsSync(envPath)) return out;
  for (const line of fs.readFileSync(envPath, "utf-8").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq <= 0) continue;
    const key = trimmed.slice(0, eq).trim();
    let value = trimmed.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    out[key.toLowerCase()] = value;
  }
  return out;
}

/**
 * 读取设置。
 *
 * 优先级：环境变量 > `.env` 文件 > 默认值（与 pydantic-settings 的
 * `env_file` + `case_sensitive=False` 语义一致）。
 */
function readSettings(): RawSettings {
  const fromFile = loadDotEnv();
  const raw: Record<string, unknown> = { ...fromFile };

  // **环境变量独立生效**（不依赖 `.env` 文件存在）。
  //
  // ⚠️ **P8-02 实测踩坑**：此前只遍历 `.env` 文件里的键 → **没有 `.env` 时，
  //    所有环境变量都被忽略**。安装包里 `PROJECT_ROOT` = `resources/`（**只读**，
  //    放不了 `.env`）→ 壳注入的 `DASHSCOPE_API_KEY` 永远不生效 → 界面报
  //    「未配置 LLM 密钥」。
  //
  // 正确语义应与 Python 侧 pydantic-settings 一致：**环境变量与 `.env` 各自独立**，
  // 环境变量优先级更高。
  for (const key of Object.keys(SettingsSchema.shape)) {
    const envKey = key.toUpperCase();
    const v = process.env[envKey];
    if (v !== undefined && v !== "") raw[key] = v;
  }

  const parsed = SettingsSchema.safeParse(raw);
  if (!parsed.success) {
    // 配置错误不阻断启动：打印问题并用默认值兜底（桌面态首启向导可修正）
    const issues = parsed.error.issues
      .map((i) => `${i.path.join(".")}: ${i.message}`)
      .join("; ");
    // eslint-disable-next-line no-console
    console.error(`[config] 校验失败，使用默认值兜底: ${issues}`);
    return SettingsSchema.parse({});
  }
  return parsed.data;
}

/**
 * 应用配置（**显式声明**）。
 *
 * 之所以不直接用 `z.infer<typeof SettingsSchema>`：Zod 的 `z.coerce.*` 输入类型是
 * `unknown`，在 `interface extends` 时会污染全部字段。运行时仍由 Zod schema 校验，
 * 这里只负责**类型契约**。
 */
export interface Settings {
  app_name: string;
  app_version: string;
  debug: boolean;
  host: string;
  port: number;
  sensitive_policy: "allow" | "encrypt" | "deny";
  research_fact_check: boolean;
  dashscope_api_key: string;
  dashscope_base_url: string;
  default_model: string;
  max_tokens: number;
  max_iterations: number;
  skill_match_top_k: number;
  reflection_max_rounds: number;
  exec_timeout: number;
  llm_api_key: string;
  llm_base_url: string;
  plan_model: string;
  rag_model: string;
  answer_model: string;
  openai_api_key: string;
  openai_base_url: string;
  openai_model: string;
  agent_api_key: string;
  serper_api_key: string;
  gaode_api_key: string;
  mcp_max_servers: number;
  mcp_call_timeout: number;
  milvus_db_path: string;
  milvus_collection: string;
  bocha_api_key: string;
  bocha_base_url: string;
  bocha_default_count: number;
  bocha_summary: boolean;
  research_output_dir: string;
  research_max_concurrent: number;
  research_persist: boolean;
  database_url: string;
  db_echo: boolean;
  session_history_limit: number;
  session_history_max_chars: number;
  chat_max_iterations: number;
  scheduler_enabled: boolean;
  tz: string;
  schedule_run_timeout: number;
  schedule_max_concurrent: number;
  interactive_max_concurrent: number;
  interactive_queue_timeout: number;
  schedule_lease_ttl: number;
  schedule_lease_renew: number;
  schedule_daily_run_limit: number;
  schedule_task_soft_limit: number;
  schedule_stale_sweep_minutes: number;
  schedule_stale_sweep_grace: number;
  context_lazy_tool_loading: boolean;
  context_budget_ratio: number;
  context_compact_threshold: number;
  context_summary_threshold: number;
  context_keep_recent_turns: number;
  context_memory_enabled: boolean;
  context_memory_max: number;
  pricing_json: string;
  permission_approval_timeout: number;
  permission_audit_enabled: boolean;
  log_to_file: boolean;
  log_file_name: string;
  log_file_max_bytes: number;
  log_file_backup_count: number;
  log_file_level: string;
  log_debug_sample_rate: number;
  exec_resource_limits: boolean;
  exec_cpu_seconds: number;
  exec_memory_bytes: number;
  exec_open_files: number;
  exec_file_size_bytes: number;
  exec_max_output_bytes: number;
  exec_workspace_escape_check: boolean;
  exec_network_enabled: boolean;
  upload_max_file_bytes: number;
  upload_max_request_bytes: number;
  upload_allowed_extensions: string;
  cors_origins: string;

  // ---------- 路径（派生） ----------
  readonly milvus_db_abs: string;
  readonly data_dir_abs: string;
  readonly database_url_abs: string;
  readonly custom_skills_dir: string;
  readonly output_dir: string;
  readonly upload_dir: string;
  readonly browser_data_dir: string;
  readonly pdf_dir: string;
  readonly logs_dir: string;
  readonly research_output_abs: string;
  readonly user_data_dir: string;
  readonly runtime_root: string;
  readonly builtin_skills_dir: string;
  readonly frontend_dist_dir: string;
  readonly default_workspace_dir: string;
  readonly vectors_dir: string;
  // ---------- 能力 ----------
  readonly has_api_key: boolean;
  readonly web_search_available: boolean;
  readonly llm_available: boolean;
  readonly bocha_configured: boolean;
  readonly research_configured: boolean;
  readonly desktop_mode: boolean;
  readonly desktop_token: string;
  readonly desktop_bootstrap_nonce: string;
  readonly desktop_protocol: number;
  readonly desktop_missed_window_hours: number;
  readonly cors_origin_list: string[];
  readonly upload_extension_list: string[];
}

function buildSettings(raw: RawSettings): Settings {
  const resolve = (p: string): string =>
    path.isAbsolute(p) ? p : path.join(PROJECT_ROOT, p);

  const userDataDir = envStr("AGENT_DATA_DIR") || path.join(PROJECT_ROOT, "data");
  const runtimeRoot = envStr("AGENT_RUNTIME_ROOT") || PROJECT_ROOT;
  const builtinSkillsDir = envStr("AGENT_SKILLS_DIR") || path.join(PROJECT_ROOT, "skills");
  // 前端产物：开发态 `apps/ui/dist`；打包态 `resources/frontend`（壳会注入，此处为兜底）
  const frontendDistDir =
    envStr("AGENT_FRONTEND_DIST") ||
    (fs.existsSync(path.join(PROJECT_ROOT, "apps", "ui", "dist"))
      ? path.join(PROJECT_ROOT, "apps", "ui", "dist")
      : path.join(PROJECT_ROOT, "frontend"));
  const defaultWorkspaceDir =
    envStr("AGENT_WORKSPACE_DIR") || path.join(userDataDir, "workspace");

  const databaseUrlAbs = raw.database_url.trim()
    ? raw.database_url
    : `sqlite:///${path.join(userDataDir, "app.db")}`;

  const desktopMode = envFlag("AGENT_DESKTOP");

  const settings: Settings = {
    ...raw,

    // ⚠️ 向量库文件**必须可写**：安装包内 `resources/` 是只读的 →
    // 相对路径一律挂到**用户数据目录**下（开发态 userDataDir = PROJECT_ROOT/data，
    // 与 Python 侧 `PROJECT_ROOT/data/milvus.db` 完全一致）。
    milvus_db_abs: path.isAbsolute(raw.milvus_db_path)
      ? raw.milvus_db_path
      : path.join(userDataDir, raw.milvus_db_path.replace(/^data[\\/]/, "")),
    // ⚠️ **必须可写**：安装包内的 `resources/` 是**只读**的 → 打包态必须落到用户数据目录
    // （与 Python 侧 `user_data_dir` 在注入了 `AGENT_DATA_DIR` 时等于 data_dir 的语义一致）。
    data_dir_abs: userDataDir,
    database_url_abs: databaseUrlAbs,
    custom_skills_dir: path.join(userDataDir, "skills_custom"),
    output_dir: path.join(userDataDir, "outputs"),
    upload_dir: path.join(userDataDir, "uploads"),
    browser_data_dir: path.join(userDataDir, "browser_data"),
    pdf_dir: path.join(userDataDir, "pdf"),
    logs_dir: path.join(userDataDir, "logs"),
    research_output_abs: resolve(raw.research_output_dir),
    user_data_dir: userDataDir,
    runtime_root: runtimeRoot,
    builtin_skills_dir: builtinSkillsDir,
    frontend_dist_dir: frontendDistDir,
    default_workspace_dir: defaultWorkspaceDir,
    vectors_dir: path.join(userDataDir, "vectors"),

    has_api_key: raw.dashscope_api_key.trim().length > 0,
    web_search_available: raw.serper_api_key.trim().length > 0,
    llm_available: raw.llm_api_key.trim().length > 0,
    bocha_configured: raw.bocha_api_key.trim().length > 0,
    research_configured:
      raw.bocha_api_key.trim().length > 0 || raw.serper_api_key.trim().length > 0,

    desktop_mode: desktopMode,
    desktop_token: envStr("AGENT_DESKTOP_TOKEN"),
    desktop_bootstrap_nonce: envStr("AGENT_DESKTOP_BOOTSTRAP_NONCE"),
    desktop_protocol: envInt("AGENT_DESKTOP_PROTOCOL", 1),
    desktop_missed_window_hours: envInt("AGENT_DESKTOP_MISSED_WINDOW_HOURS", 6),

    cors_origin_list: desktopMode
      ? []
      : raw.cors_origins
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
    upload_extension_list: raw.upload_allowed_extensions
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean),
  };
  return settings;
}

let cached: Settings | null = null;

/** 获取设置单例（测试可调用 `resetSettings()` 复位）。 */
export function getSettings(): Settings {
  if (!cached) cached = buildSettings(readSettings());
  return cached;
}

/** 复位设置单例（测试用）。 */
export function resetSettings(): void {
  cached = null;
}

export const settings: Settings = getSettings();

/** 创建所需目录（幂等）。 */
export function ensureDirs(s: Settings = settings): void {
  const dirs = [
    s.builtin_skills_dir,
    s.user_data_dir,
    s.custom_skills_dir,
    s.output_dir,
    s.upload_dir,
    s.browser_data_dir,
    s.pdf_dir,
    s.logs_dir,
    s.default_workspace_dir,
    s.research_output_abs,
    s.vectors_dir,
  ];
  for (const dir of dirs) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

/** 可供前端切换的模型列表（DashScope OpenAI 兼容模式）。 */
export const AVAILABLE_MODELS: Array<{ id: string; name: string; provider: string }> = [
  { id: "qwen-plus", name: "Qwen-Plus", provider: "阿里" },
  { id: "qwen-turbo", name: "Qwen-Turbo", provider: "阿里" },
  { id: "qwen-max", name: "Qwen-Max", provider: "阿里" },
  { id: "qwen-long", name: "Qwen-Long", provider: "阿里" },
];

// --------------------------------------------------------------------------- //
// 阈值常量集中（design §6.1-6）
// --------------------------------------------------------------------------- //
export const LIMITS = {
  /** Agent 循环上限 */
  maxIterations: 20,
  /** 代码执行墙钟超时（秒） */
  execTimeoutSeconds: 180,
  /** setrlimit CPU（秒） */
  execCpuSeconds: 60,
  /** setrlimit 内存（MB） */
  execMemoryMb: 1024,
  /** 句柄数 */
  execOpenFiles: 256,
  /** 单文件写上限（MB） */
  execFileSizeMb: 64,
  /** 输出截断阈值（字节），超出即杀 */
  execMaxOutputBytes: 65536,
  /** 调度槽位 */
  scheduleMaxConcurrent: 2,
  /** 交互槽位（与调度分离） */
  interactiveMaxConcurrent: 4,
  /** ask 审批超时（秒），超时按 deny */
  permissionApprovalTimeout: 120,
  /** 上下文预算 / 压缩触发 / 摘要触发 */
  contextBudgetRatio: 0.85,
  contextCompactThreshold: 0.7,
  contextSummaryThreshold: 0.85,
  /** RAG 混合检索权重与条数 */
  ragSparseWeight: 0.7,
  ragDenseWeight: 1.0,
  ragLimit: 10,
  /** BM25 参数（对齐 Milvus 默认） */
  bm25K1: 1.5,
  bm25B: 0.75,
  /** Embedding 维度与批大小 */
  embeddingDim: 1024,
  embeddingBatch: 10,
  /** 上传限额 */
  uploadMaxFileBytes: 50 * 1024 * 1024,
  uploadMaxRequestBytes: 100 * 1024 * 1024,
} as const;

/** 命令黑名单（来源：services/code_executor.py `BLOCKED_COMMANDS`）。 */
export const BLOCKED_COMMANDS: string[] = [
  "rm -rf /",
  "mkfs",
  "dd if=",
  ":(){",
  "shutdown",
];
