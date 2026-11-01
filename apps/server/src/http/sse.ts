/**
 * SSE 工具（契约冻结：4 条 SSE 端点，统一响应头）。
 *
 * 统一响应头：`Cache-Control: no-cache`、`X-Accel-Buffering: no`、`Connection: keep-alive`。
 *
 * ⚠️ **不要启用 `@fastify/compress`** —— 会缓冲 SSE 流。
 */
import type { FastifyReply } from "fastify";

export const SSE_HEADERS: Record<string, string> = {
  "Content-Type": "text/event-stream; charset=utf-8",
  "Cache-Control": "no-cache",
  "X-Accel-Buffering": "no",
  Connection: "keep-alive",
};

export interface SseChannel {
  /** 发送一个事件。 */
  send(event: string, data: unknown, id?: number): void;
  /** 发送一条注释（心跳）。 */
  ping(): void;
  /** 结束响应。 */
  end(): void;
  /** 底层响应是否已断开。 */
  readonly closed: boolean;
}

/** 建立一条 SSE 通道。 */
export function sse(reply: FastifyReply): SseChannel {
  reply.raw.writeHead(200, SSE_HEADERS);
  // Node 的 keep-alive 由 socket 层处理；显式关闭 Nagle 以降低首字节延迟
  reply.raw.socket?.setNoDelay?.(true);

  let closed = false;

  const write = (chunk: string): void => {
    if (closed) return;
    try {
      reply.raw.write(chunk);
    } catch {
      closed = true;
    }
  };

  return {
    get closed() {
      return closed || reply.raw.writableEnded;
    },
    send(event: string, data: unknown, id?: number): void {
      let payload: string;
      try {
        payload = JSON.stringify(data ?? null);
      } catch {
        payload = "null";
      }
      const idPart = id !== undefined ? `id: ${id}\n` : "";
      write(`${idPart}event: ${event}\ndata: ${payload}\n\n`);
    },
    ping(): void {
      write(": ping\n\n");
    },
    end(): void {
      if (closed) return;
      closed = true;
      try {
        reply.raw.end();
      } catch {
        // 忽略
      }
    },
  };
}

/** 仅发送 `data:` 行（Python 侧 `POST /agent/run` 的形态：事件名放在 payload 的 `type` 字段）。 */
export function sseData(channel: SseChannel, data: unknown): void {
  let payload: string;
  try {
    payload = JSON.stringify(data ?? null);
  } catch {
    payload = "null";
  }
  channel.send("message", data);
  void payload;
}
