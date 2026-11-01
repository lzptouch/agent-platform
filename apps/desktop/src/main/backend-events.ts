/** 后端事件流订阅（后端 → 壳）。
 *
 * 契约：``GET /api/v1/desktop/events`` 返回 SSE，每条形如
 * ``data: {"id":1,"type":"workspace_changed","ts":"..."}\n\n``；
 * ``id`` 为游标，重连时用 ``after_id`` 补发断连期间的事件。
 *
 * 解析逻辑拆成纯函数（``parseSseBuffer``），便于单测；
 * 网络层（``startEventStream``）只负责连接与重连。
 */
import http from "node:http";

import type { BackendEvent } from "../shared/types";

export interface DesktopEventPayload {
  id: number;
  type: string;
  ts?: string;
  [key: string]: unknown;
}

export interface SseParseResult {
  events: DesktopEventPayload[];
  rest: string;
}

/** 从 SSE 文本缓冲中取出完整事件，剩余部分留在 ``rest``。 */
export function parseSseBuffer(buffer: string): SseParseResult {
  const events: DesktopEventPayload[] = [];
  // 归一 CRLF：SSE 允许 \r\n / \n\r / \n 三种换行；这里先统一成 \n
  let rest = buffer.replace(/\r\n/g, "\n");

  for (;;) {
    const sep = rest.indexOf("\n\n");
    if (sep === -1) break;
    const block = rest.slice(0, sep);
    rest = rest.slice(sep + 2);

    const dataLines: string[] = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
    }
    if (dataLines.length === 0) continue;

    const text = dataLines.join("\n");
    try {
      const parsed = JSON.parse(text) as Partial<DesktopEventPayload>;
      if (typeof parsed?.type !== "string") continue;
      events.push({
        id: typeof parsed.id === "number" ? parsed.id : 0,
        type: parsed.type,
        ...(typeof parsed.ts === "string" ? { ts: parsed.ts } : {}),
        ...parsed,
      });
    } catch {
      // 非法 JSON：跳过该条，不中断整条流
    }
  }

  return { events, rest };
}

/** 归一为渲染进程消费的 ``BackendEvent``。 */
export function toBackendEvent(payload: DesktopEventPayload): BackendEvent {
  return { ...payload, type: payload.type };
}

export interface EventStreamOptions {
  port: number;
  token: string;
  onEvent: (event: BackendEvent) => void;
  onError?: (err: Error) => void;
  /** 重连退避（毫秒），默认 1s / 2s / 4s / 8s 封顶。 */
  reconnectDelaysMs?: number[];
}

/** 单飞重连闸门：同一时刻最多挂**一个**重连定时器。 */
export interface ReconnectGate {
  /** 安排一次重连；已有待触发的重连时返回 false（不重复安排）。 */
  schedule(delayMs: number, task: () => void): boolean;
  /** 取消待触发的重连。 */
  cancel(): void;
  /** 当前是否有待触发的重连。 */
  pending(): boolean;
}

export function createReconnectGate(): ReconnectGate {
  let timer: NodeJS.Timeout | null = null;
  return {
    schedule(delayMs: number, task: () => void): boolean {
      if (timer) return false;
      timer = setTimeout(() => {
        timer = null;
        task();
      }, delayMs);
      return true;
    },
    cancel(): void {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
    },
    pending(): boolean {
      return timer !== null;
    },
  };
}

/** 启动事件流订阅；返回停止函数。 */
export function startEventStream(opts: EventStreamOptions): () => void {
  const delays = opts.reconnectDelaysMs ?? [1_000, 2_000, 4_000, 8_000];
  let stopped = false;
  let attempt = 0;
  let cursor = 0;
  let req: http.ClientRequest | null = null;
  // **D10**：res / req 两处 error 都会触发重连 → 此前会挂**两个**定时器 →
  // 两条并发 SSE → 每条事件被投递两遍。用单飞闸门收敛。
  const gate = createReconnectGate();

  const connect = (): void => {
    if (stopped) return;
    req = http.get(
      {
        host: "127.0.0.1",
        port: opts.port,
        path: `/api/v1/desktop/events?after_id=${cursor}`,
        headers: { "X-Agent-Desktop-Token": opts.token, Accept: "text/event-stream" },
      },
      (res) => {
        res.setEncoding("utf-8");
        let buffer = "";
        res.on("data", (chunk: string) => {
          buffer += chunk;
          const { events, rest } = parseSseBuffer(buffer);
          buffer = rest;
          for (const ev of events) {
            if (typeof ev.id === "number" && ev.id > cursor) cursor = ev.id;
            opts.onEvent(toBackendEvent(ev));
          }
        });
        res.on("end", () => {
          attempt = 0;
          if (!stopped) gate.schedule(delays[0], connect);
        });
        res.on("error", () => {
          if (!stopped) scheduleReconnect();
        });
      },
    );
    req.on("error", (err: Error) => {
      opts.onError?.(err);
      scheduleReconnect();
    });
  };

  const scheduleReconnect = (): void => {
    if (stopped) return;
    const delay = delays[Math.min(attempt, delays.length - 1)];
    attempt += 1;
    gate.schedule(delay, connect);
  };

  connect();

  return () => {
    stopped = true;
    gate.cancel();
    if (req) {
      req.destroy();
      req = null;
    }
  };
}
