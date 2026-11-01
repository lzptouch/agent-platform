import { describe, expect, it, vi } from "vitest";

import { createReconnectGate, parseSseBuffer, toBackendEvent } from "../../../apps/desktop/src/main/backend-events";

describe("parseSseBuffer", () => {
  it("解析单条完整事件", () => {
    const raw = 'data: {"id":1,"type":"workspace_changed","ts":"2026-10-26T09:00:00Z"}\n\n';
    const { events, rest } = parseSseBuffer(raw);
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe("workspace_changed");
    expect(events[0].id).toBe(1);
    expect(rest).toBe("");
  });

  it("保留半包到下次解析（TCP 分片场景）", () => {
    const first = parseSseBuffer('data: {"id":2,"ty');
    expect(first.events).toHaveLength(0);
    expect(first.rest).toContain('"ty');

    const second = parseSseBuffer(first.rest + 'pe":"run_started"}\n\n');
    expect(second.events).toHaveLength(1);
    expect(second.events[0].type).toBe("run_started");
  });

  it("一次解析多条事件并保持顺序", () => {
    const raw =
      'data: {"id":1,"type":"a"}\n\n' +
      'data: {"id":2,"type":"b"}\n\n' +
      'data: {"id":3,"type":"c"}\n\n';
    const { events } = parseSseBuffer(raw);
    expect(events.map((e) => e.type)).toEqual(["a", "b", "c"]);
    expect(events.map((e) => e.id)).toEqual([1, 2, 3]);
  });

  it("跳过非法 JSON 而不中断整条流", () => {
    const raw = "data: {not-json}\n\n" + 'data: {"id":9,"type":"ok"}\n\n';
    const { events } = parseSseBuffer(raw);
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe("ok");
  });

  it("忽略缺少 type 的事件", () => {
    const raw = 'data: {"id":5}\n\n';
    const { events } = parseSseBuffer(raw);
    expect(events).toHaveLength(0);
  });

  it("忽略没有 data 行的块（注释/心跳行）", () => {
    const raw = ": keep-alive\n\n" + 'data: {"id":6,"type":"ping"}\n\n';
    const { events } = parseSseBuffer(raw);
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe("ping");
  });

  it("兼容 CRLF 换行", () => {
    const raw = 'data: {"id":7,"type":"x"}\r\n\r\n';
    const { events } = parseSseBuffer(raw);
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe("x");
  });
});

describe("toBackendEvent", () => {
  it("保留 type 与业务字段", () => {
    const ev = toBackendEvent({ id: 3, type: "run_finished", payload: { run_id: "r1" } });
    expect(ev.type).toBe("run_finished");
    expect((ev as Record<string, unknown>).payload).toEqual({ run_id: "r1" });
  });

  it("类型与后端一致：透传未知类型", () => {
    const ev = toBackendEvent({ id: 4, type: "custom_event" });
    expect(ev.type).toBe("custom_event");
  });
});

describe("单飞重连闸门（**D10**）", () => {
  it("同一时刻只挂一个重连定时器", () => {
    vi.useFakeTimers();
    try {
      const gate = createReconnectGate();
      let count = 0;
      expect(gate.schedule(100, () => (count += 1))).toBe(true);
      expect(gate.schedule(100, () => (count += 1))).toBe(false);
      expect(gate.pending()).toBe(true);
      vi.advanceTimersByTime(100);
      expect(count).toBe(1);
      expect(gate.pending()).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it("cancel 能取消待触发的重连", () => {
    vi.useFakeTimers();
    try {
      const gate = createReconnectGate();
      let count = 0;
      gate.schedule(100, () => (count += 1));
      gate.cancel();
      vi.advanceTimersByTime(500);
      expect(count).toBe(0);
      expect(gate.pending()).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });
});
