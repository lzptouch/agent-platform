/**
 * 桌面事件总线（后端 → 壳）。
 *
 * 事件是**单向**的：后端发布，壳通过 `GET /api/v1/desktop/events`（SSE）订阅。
 * 历史只保留最近 200 条，重连时带 `after_id` 补发。
 */
import { utcNow } from "../db/schema.js";

export const MAX_EVENTS = 200;

export interface DesktopEvent {
  id: number;
  type: string;
  ts: string;
  [key: string]: unknown;
}

export class DesktopEventBus {
  private events: DesktopEvent[] = [];
  private seq = 0;

  constructor(private readonly maxlen: number = MAX_EVENTS) {}

  /** 发布一条事件，返回事件体。 */
  publish(eventType: string, payload: Record<string, unknown> = {}): DesktopEvent {
    this.seq += 1;
    const event: DesktopEvent = {
      id: this.seq,
      type: eventType,
      ts: utcNow(),
      ...payload,
    };
    this.events.push(event);
    if (this.events.length > this.maxlen) {
      this.events.splice(0, this.events.length - this.maxlen);
    }
    return event;
  }

  /** 取出 `id > after_id` 的事件（按发布顺序）。 */
  since(afterId = 0): DesktopEvent[] {
    return this.events.filter((e) => e.id > afterId);
  }

  /** 最新事件 id。 */
  latestId(): number {
    return this.seq;
  }

  /** 清空（测试用）。 */
  clear(): void {
    this.events = [];
    this.seq = 0;
  }
}

/** 全局单例（与应用同生命周期）。 */
export const bus = new DesktopEventBus();
