import { beforeEach, describe, expect, it, vi } from "vitest";

/** Notification 的假实现：记录点击回调。 */
let clickHandler: (() => void) | null = null;
let shown = 0;
let supported = true;

vi.mock("electron", () => ({
  Notification: class {
    static isSupported() {
      return supported;
    }
    on(event: string, cb: () => void) {
      if (event === "click") clickHandler = cb;
    }
    show() {
      shown += 1;
    }
    constructor(public opts: { title: string; body?: string }) {}
  },
}));

const sent: Array<{ channel: string; payload: unknown }> = [];
const win = {
  show: vi.fn(),
  focus: vi.fn(),
  webContents: { send: (channel: string, payload: unknown) => sent.push({ channel, payload }) },
};
vi.mock("./window", () => ({ getMainWindow: () => win }));

import { showNotification } from "./notifications";

describe("系统通知", () => {
  beforeEach(() => {
    clickHandler = null;
    shown = 0;
    sent.length = 0;
    supported = true;
    win.show.mockClear();
    win.focus.mockClear();
  });

  it("不支持通知时返回 false", () => {
    supported = false;
    expect(showNotification({ title: "x" })).toBe(false);
    expect(shown).toBe(0);
  });

  it("点击通知聚焦主窗口并带 runId 跳转", () => {
    const ok = showNotification({ title: "任务完成", body: "已完成", runId: "run-1" });
    expect(ok).toBe(true);
    expect(shown).toBe(1);

    clickHandler?.();
    expect(win.show).toHaveBeenCalled();
    expect(win.focus).toHaveBeenCalled();
    expect(sent).toEqual([{ channel: "agent:open-run", payload: "run-1" }]);
  });

  it("无 runId 时不发跳转事件", () => {
    showNotification({ title: "提示" });
    clickHandler?.();
    expect(win.show).toHaveBeenCalled();
    expect(sent).toHaveLength(0);
  });
});
