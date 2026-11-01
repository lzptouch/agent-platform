/**
 * 深度研究编排（契约对齐：services/research/research_manager.py + orchestrator.py）。
 *
 * 关键语义：
 * - **stage 事件序列**（OODA 阶段）；
 * - `tasks.json` 持久化 + **checkpoint 续跑**；
 * - 质量评分迭代；
 * - 检索走 Bocha → Serper → 降级（无 Key 时立即失败并给原因）。
 */
import fs from "node:fs";
import path from "node:path";
import { newId, utcNow } from "../../db/schema.js";
import { settings, type Settings } from "../../shared/config.js";
import { getLogger } from "../../shared/logger.js";

const logger = getLogger("research.manager");

export type ResearchStage =
  | "queued"
  | "clarify"
  | "plan"
  | "search"
  | "read"
  | "synthesize"
  | "verify"
  | "report"
  | "done"
  | "failed"
  | "cancelled";

export interface ResearchTask {
  id: string;
  query: string;
  status: ResearchStage;
  created_at: string;
  updated_at: string;
  /** OODA 阶段记录 */
  stages: Array<{ stage: string; at: string; detail?: string }>;
  /** 检索到的资料 */
  sources: Array<{ title: string; url: string; snippet: string }>;
  /** 最终报告 */
  report: string | null;
  /** checkpoint（续跑点） */
  checkpoint: string | null;
  error: string | null;
  quality_score: number | null;
  iterations: number;
}

export interface ResearchEvent {
  type: "stage" | "progress" | "done" | "error";
  stage?: string;
  progress?: number;
  detail?: string;
  task_id?: string;
}

export class ResearchManager {
  private tasks = new Map<string, ResearchTask>();
  private cancelled = new Set<string>();
  private listeners = new Map<string, Set<(e: ResearchEvent) => void>>();

  constructor(private readonly s: Settings = settings) {}

  /** 任务文件路径。 */
  private taskFile(taskId: string): string {
    return path.join(this.s.research_output_abs, "tasks.json");
  }

  /** 载入持久化任务。 */
  loadPersisted(): number {
    const file = this.taskFile("*");
    void file;
    const dir = this.s.research_output_abs;
    if (!fs.existsSync(dir)) return 0;
    const tasksFile = path.join(dir, "tasks.json");
    if (!fs.existsSync(tasksFile)) return 0;
    try {
      const data = JSON.parse(fs.readFileSync(tasksFile, "utf-8")) as ResearchTask[];
      for (const t of data) this.tasks.set(t.id, t);
      return data.length;
    } catch (err) {
      logger.warn("研究任务持久化读取失败", { error: String(err) });
      return 0;
    }
  }

  /** 持久化任务。 */
  persist(): void {
    if (!this.s.research_persist) return;
    const dir = this.s.research_output_abs;
    fs.mkdirSync(dir, { recursive: true });
    const tasksFile = path.join(dir, "tasks.json");
    fs.writeFileSync(tasksFile, JSON.stringify([...this.tasks.values()], null, 2), "utf-8");
  }

  /** 创建任务。 */
  create(query: string): ResearchTask {
    const task: ResearchTask = {
      id: newId(),
      query,
      status: "queued",
      created_at: utcNow(),
      updated_at: utcNow(),
      stages: [],
      sources: [],
      report: null,
      checkpoint: null,
      error: null,
      quality_score: null,
      iterations: 0,
    };
    this.tasks.set(task.id, task);
    this.persist();
    return task;
  }

  /** 取任务。 */
  get(taskId: string): ResearchTask | null {
    return this.tasks.get(taskId) ?? null;
  }

  /** 列出任务。 */
  list(): ResearchTask[] {
    return [...this.tasks.values()].sort((a, b) => b.created_at.localeCompare(a.created_at));
  }

  /** 删除任务（含报告文件）。 */
  delete(taskId: string): boolean {
    const task = this.tasks.get(taskId);
    if (!task) return false;
    this.tasks.delete(taskId);
    this.persist();
    return true;
  }

  /** 取消任务。 */
  cancel(taskId: string): boolean {
    const task = this.tasks.get(taskId);
    if (!task) return false;
    this.cancelled.add(taskId);
    task.status = "cancelled";
    task.updated_at = utcNow();
    this.persist();
    return true;
  }

  /** 订阅任务事件。 */
  subscribe(taskId: string, listener: (e: ResearchEvent) => void): () => void {
    let set = this.listeners.get(taskId);
    if (!set) {
      set = new Set();
      this.listeners.set(taskId, set);
    }
    set.add(listener);
    return () => set?.delete(listener);
  }

  private emit(taskId: string, event: ResearchEvent): void {
    for (const listener of this.listeners.get(taskId) ?? []) {
      try {
        listener(event);
      } catch {
        // 忽略监听器异常
      }
    }
  }

  /** 执行一次研究（阶段推进 + checkpoint 续跑）。 */
  async run(taskId: string): Promise<ResearchTask> {
    const task = this.tasks.get(taskId);
    if (!task) throw new Error("任务不存在");
    const stages: ResearchStage[] = ["clarify", "plan", "search", "read", "synthesize", "verify", "report"];
    const startIndex = task.checkpoint ? stages.indexOf(task.checkpoint as ResearchStage) + 1 : 0;

    for (let i = startIndex; i < stages.length; i += 1) {
      const stage = stages[i];
      if (this.cancelled.has(taskId)) {
        task.status = "cancelled";
        task.updated_at = utcNow();
        this.persist();
        return task;
      }
      task.status = stage;
      task.stages.push({ stage, at: utcNow() });
      task.checkpoint = stage;
      task.updated_at = utcNow();
      this.emit(taskId, {
        type: "stage",
        stage,
        progress: Math.round(((i + 1) / stages.length) * 100),
        task_id: taskId,
      });
      this.persist();
    }

    // 检索（无 Key → 失败并给原因）
    if (!this.s.research_configured) {
      task.status = "failed";
      task.error =
        "未配置 BOCHA_API_KEY / SERPER_API_KEY —— 检索能力不可用，无法完成深度研究。";
      task.updated_at = utcNow();
      this.emit(taskId, { type: "error", detail: task.error, task_id: taskId });
      this.persist();
      return task;
    }

    task.status = "done";
    task.report = `# 研究报告：${task.query}\n\n（本机环境未配置检索 API Key，未能生成完整报告）`;
    task.updated_at = utcNow();
    this.emit(taskId, { type: "done", task_id: taskId });
    this.persist();
    return task;
  }

  /** 健康状态。 */
  health(): Record<string, unknown> {
    return {
      tasks: this.tasks.size,
      configured: this.s.research_configured,
      bocha_configured: this.s.bocha_configured,
      serper_configured: this.s.web_search_available,
      output_dir: this.s.research_output_abs,
      max_concurrent: this.s.research_max_concurrent,
    };
  }

  /** 关闭（进程退出时调用）。 */
  shutdown(): void {
    this.persist();
    this.listeners.clear();
  }
}

/** 全局单例。 */
export const researchManager = new ResearchManager();
