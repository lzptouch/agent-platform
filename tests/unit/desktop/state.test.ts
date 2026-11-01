import { beforeEach, describe, expect, it } from "vitest";

import { backendState } from "../../../apps/desktop/src/main/state";

describe("BackendStateMachine", () => {
  beforeEach(() => {
    // 复位到初始态，避免用例之间互相影响
    backendState.set("idle");
    // 复位熔断计数（**D7**：markReady 不再清零它，必须显式复位）
    backendState.resetConsecutiveFailures();
  });

  it("初始状态为 idle", () => {
    expect(backendState.current()).toBe("idle");
  });

  it("set 触发 onChange 回调", () => {
    const seen: string[] = [];
    const off = backendState.onChange((s) => seen.push(s));
    backendState.set("starting");
    backendState.set("ready");
    off();
    expect(seen).toEqual(["starting", "ready"]);
  });

  it("相同状态不重复通知", () => {
    let count = 0;
    const off = backendState.onChange(() => (count += 1));
    backendState.set("starting");
    backendState.set("starting");
    off();
    expect(count).toBe(1);
  });

  it("退订后不再收到通知", () => {
    let count = 0;
    const off = backendState.onChange(() => (count += 1));
    off();
    backendState.set("degraded");
    expect(count).toBe(0);
  });

  it("markReady 记录端口与 PID 并回到 ready", () => {
    backendState.markReady(51862, 4242);
    const status = backendState.status();
    expect(status.state).toBe("ready");
    expect(status.port).toBe(51862);
    expect(status.pid).toBe(4242);
    expect(status.lastError).toBeNull();
  });

  it("markCrashed 记录错误原因并累计重启次数", () => {
    backendState.markCrashed("exit code 1");
    const status = backendState.status();
    expect(status.state).toBe("crashed");
    expect(status.lastError).toBe("exit code 1");
    expect(status.restarts).toBeGreaterThan(0);
  });

  it("markReady 会清空错误并复位重启计数", () => {
    backendState.markCrashed("boom");
    backendState.markReady(1, 2);
    const status = backendState.status();
    expect(status.lastError).toBeNull();
    expect(status.restarts).toBe(0);
  });

  it("markReady 不会复位连续失败计数（熔断依据）", () => {
    backendState.markCrashed("boom");
    backendState.markReady(1, 2);
    expect(backendState.status().consecutiveFailures).toBe(1);
  });

  it("连续失败计数逐次累加，只在显式复位时清零", () => {
    backendState.markCrashed("a");
    backendState.markCrashed("b");
    expect(backendState.status().consecutiveFailures).toBe(2);
    backendState.resetConsecutiveFailures();
    expect(backendState.status().consecutiveFailures).toBe(0);
  });
});
