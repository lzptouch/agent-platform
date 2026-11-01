import { beforeEach, describe, expect, it, vi } from "vitest";

/** Tray 的假实现：记录菜单与点击回调。 */
let trayClickHandler: (() => void) | null = null;
let menuLabels: string[] = [];
let badgeText: string | null = null;

vi.mock("electron", () => ({
  app: { isPackaged: false, quit: vi.fn() },
  nativeImage: {
    createFromPath: () => ({ isEmpty: () => true }),
    createEmpty: () => ({}),
  },
  Menu: {
    buildFromTemplate: (template: Array<{ label?: string; click?: () => void }>) => {
      menuLabels = template.map((t) => t.label ?? t.type ?? "");
      return { template };
    },
  },
  Tray: class {
    setToolTip() {}
    setContextMenu() {}
    on(event: string, cb: () => void) {
      if (event === "click") trayClickHandler = cb;
    }
  },
}));

let quickToggles = 0;
vi.mock("./quick", () => ({
  toggleQuickPanel: () => {
    quickToggles += 1;
  },
}));

const win = { show: vi.fn(), focus: vi.fn() };
vi.mock("./window", () => ({ getMainWindow: () => win }));
vi.mock("./paths", () => ({ getPaths: () => ({ installDir: "." }) }));

import { createTray, setTrayBadge } from "./tray";

describe("系统托盘", () => {
  beforeEach(() => {
    quickToggles = 0;
    trayClickHandler = null;
    menuLabels = [];
    badgeText = null;
    win.show.mockClear();
    win.focus.mockClear();
    createTray();
  });

  it("左键点击唤起速记输入窗", () => {
    expect(trayClickHandler).toBeTypeOf("function");
    trayClickHandler?.();
    expect(quickToggles).toBe(1);
  });

  it("菜单含速记输入与退出", () => {
    expect(menuLabels.some((l) => l.includes("速记输入"))).toBe(true);
    expect(menuLabels.some((l) => l.includes("退出"))).toBe(true);
  });

  it("角标文本显示在菜单首项", () => {
    setTrayBadge("2");
    expect(menuLabels[0]).toContain("2");
    setTrayBadge(null);
    expect(menuLabels[0]).toContain("就绪");
  });
});
