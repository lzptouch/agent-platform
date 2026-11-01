import http from "node:http";
import type { AddressInfo } from "node:net";

import { describe, expect, it } from "vitest";

import { startEventStream } from "./backend-events";

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

describe("SSE 事件流：单次故障只重连一次（**D10**）", () => {
  it("不会并发两条 SSE 连接（事件不会双发）", async () => {
    let active = 0;
    let maxActive = 0;
    const server = http.createServer((_req, res) => {
      active += 1;
      maxActive = Math.max(maxActive, active);
      res.writeHead(200, { "Content-Type": "text/event-stream" });
      res.write('data: {"id":1,"type":"x"}\n\n');
      res.on("close", () => {
        active -= 1;
      });
      // 立刻断开 → 触发客户端 error → 重连
      setTimeout(() => res.destroy(), 30);
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const port = (server.address() as AddressInfo).port;

    const stop = startEventStream({
      port,
      token: "t",
      onEvent: () => undefined,
      reconnectDelaysMs: [20],
    });
    await sleep(400);
    stop();
    await new Promise<void>((resolve) => server.close(() => resolve()));

    // 修复前：res/req 双 error → 两个定时器 → 两条并发 SSE → maxActive >= 2
    expect(maxActive).toBe(1);
  });
});
