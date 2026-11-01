import { beforeEach, describe, expect, it, vi } from "vitest";

/** globalShortcut 的假实现：记录注册与解绑，可模拟「被占用」。 */
const registered = new Map<string, () => void>();
let failNext = false;

vi.mock("electron", () => ({
  globalShortcut: {
    register: (acc: string, cb: () => void) => {
      if (failNext) {
        failNext = false;
        return false;
      }
      registered.set(acc, cb);
      return true;
    },
    unregister: (acc: string) => registered.delete(acc),
    unregisterAll: () => registered.clear(),
    isRegistered: (acc: string) => registered.has(acc),
  },
}));

let quickToggles = 0;
vi.mock("./quick", () => ({
  toggleQuickPanel: () => {
    quickToggles += 1;
  },
}));

const win = { isVisible: () => true, hide: vi.fn(), show: vi.fn(), focus: vi.fn() };
vi.mock("./window", () => ({ getMainWindow: () => win }));

const settings = { bossKey: null as string | null };
vi.mock("./settings", () => ({
  getSettings: () => ({ ...settings }),
  updateSettings: (patch: { bossKey?: string | null }) => {
    if (patch.bossKey !== undefined) settings.bossKey = patch.bossKey;
  },
}));

import { currentBossKey, registerShortcuts, setBossKey, unregisterShortcuts } from "./shortcuts";

describe("全局快捷键（速记面板 + Boss Key）", () => {
  beforeEach(() => {
    registered.clear();
    quickToggles = 0;
    settings.bossKey = null;
    win.isVisible = () => true;
    win.hide.mockClear();
    win.show.mockClear();
    unregisterShortcuts();
  });

  it("注册速记面板快捷键", () => {
    const res = registerShortcuts();
    expect(res.registered).toBe(true);
    expect(registered.size).toBe(1);
  });

  it("Boss Key 默认不绑定", () => {
    registerShortcuts();
    expect(currentBossKey()).toBeNull();
    expect(settings.bossKey).toBeNull();
  });

  it("绑定 Boss Key 后可显隐切换主窗口", () => {
    const res = setBossKey("Ctrl+Shift+B");
    expect(res.registered).toBe(true);
    expect(currentBossKey()).toBe("Ctrl+Shift+B");
    expect(settings.bossKey).toBe("Ctrl+Shift+B");

    // 触发注册的回调 → 窗口可见时隐藏
    registered.get("Ctrl+Shift+B")?.();
    expect(win.hide).toHaveBeenCalled();

    // 窗口不可见时 → 显示并聚焦
    win.isVisible = () => false;
    registered.get("Ctrl+Shift+B")?.();
    expect(win.show).toHaveBeenCalled();
    expect(win.focus).toHaveBeenCalled();
  });

  it("解绑会释放注册并清空配置", () => {
    setBossKey("Ctrl+Shift+B");
    const res = setBossKey(null);
    expect(res.registered).toBe(true);
    expect(currentBossKey()).toBeNull();
    expect(settings.bossKey).toBeNull();
    expect(registered.has("Ctrl+Shift+B")).toBe(false);
  });

  it("快捷键被占用时如实返回冲突且不留下绑定", () => {
    failNext = true;
    const res = setBossKey("Ctrl+Alt+X");
    expect(res.registered).toBe(false);
    expect(res.conflicts).toContain("Ctrl+Alt+X");
    expect(currentBossKey()).toBeNull();
    expect(settings.bossKey).toBeNull();
  });

  it("已配置的 Boss Key 在启动时被注册", () => {
    settings.bossKey = "Ctrl+Shift+Q";
    registerShortcuts();
    expect(currentBossKey()).toBe("Ctrl+Shift+Q");
  });
});
