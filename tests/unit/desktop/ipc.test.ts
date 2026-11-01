import { beforeEach, describe, expect, it, vi } from "vitest";

type Handler = (event: unknown, ...args: unknown[]) => unknown;

const handlers = new Map<string, Handler>();
const openedExternally: string[] = [];
const writtenClipboard: string[] = [];

vi.mock("electron", () => ({
  app: { quit: vi.fn() },
  globalShortcut: {
    register: vi.fn(() => true),
    unregister: vi.fn(),
    unregisterAll: vi.fn(),
  },
  clipboard: {
    readText: () => "clipboard-text",
    writeText: (t: string) => {
      writtenClipboard.push(t);
    },
  },
  dialog: {
    showOpenDialog: vi.fn(async () => ({ canceled: true, filePaths: [] })),
    showSaveDialog: vi.fn(async () => ({ canceled: true, filePath: undefined })),
  },
  ipcMain: {
    handle: (channel: string, fn: Handler) => {
      handlers.set(channel, fn);
    },
  },
  shell: {
    showItemInFolder: vi.fn(),
    openExternal: (url: string) => {
      openedExternally.push(url);
    },
  },
  BrowserWindow: {
    getAllWindows: () => [],
    getFocusedWindow: () => null,
  },
}));

vi.mock("../../../apps/desktop/src/main/window", () => ({ getMainWindow: () => null }));
vi.mock("../../../apps/desktop/src/main/backend", () => ({ supervisor: { handle: () => null } }));
vi.mock("../../../apps/desktop/src/main/paths", () => ({ getPaths: () => ({ logsDir: ".", dataDir: "." }) }));
vi.mock("../../../apps/desktop/src/main/tray", () => ({ setTrayBadge: vi.fn() }));
vi.mock("../../../apps/desktop/src/main/notifications", () => ({ showNotification: vi.fn(() => true) }));
vi.mock("../../../apps/desktop/src/main/updater", () => ({
  checkForUpdates: vi.fn(() => null),
  restartIntoUpdate: vi.fn(),
}));

const settingsState = {
  bossKey: null as string | null,
  autoLaunch: false,
  startMinimized: false,
};
vi.mock("../../../apps/desktop/src/main/settings", () => ({
  getSettings: () => ({ ...settingsState }),
  updateSettings: (patch: Partial<typeof settingsState>) => {
    Object.assign(settingsState, patch);
    return { ...settingsState };
  },
  applyAutoLaunch: vi.fn(),
}));
vi.mock("../../../apps/desktop/src/main/shortcuts", () => ({
  // 真实实现里 setBossKey 负责落盘；这里同步更新内存态以便断言
  setBossKey: vi.fn((acc: string | null) => {
    settingsState.bossKey = acc;
    return { registered: true, conflicts: [] as string[] };
  }),
}));
vi.mock("../../../apps/desktop/src/main/quick", () => ({ closeQuickPanel: vi.fn() }));

import { registerIpc } from "../../../apps/desktop/src/main/ipc";

describe("IPC 白名单", () => {
  beforeEach(() => {
    handlers.clear();
    openedExternally.length = 0;
    writtenClipboard.length = 0;
    registerIpc();
  });

  it("注册了预期的通道集合", () => {
    expect(handlers.has("desktop:status")).toBe(true);
    expect(handlers.has("desktop:diagnostics")).toBe(true);
    expect(handlers.has("desktop:chooseDirectory")).toBe(true);
    expect(handlers.has("desktop:saveArtifact")).toBe(true);
    expect(handlers.has("desktop:openExternal")).toBe(true);
    expect(handlers.has("desktop:setClipboard")).toBe(true);
  });

  it("不提供任意命令/任意路径的通用 IPC", () => {
    const channels = [...handlers.keys()];
    expect(channels.some((c) => /exec|command|shell|readfile/i.test(c))).toBe(false);
  });

  it("参数非法时返回统一错误结构而不是抛异常", async () => {
    const res = (await handlers.get("desktop:openExternal")?.({}, "file:///etc/passwd")) as {
      ok: boolean;
      error?: { code: string };
    };
    expect(res.ok).toBe(false);
    expect(res.error?.code).toBe("E_INVALID");
  });

  it("openExternal 只放行 http/https", async () => {
    await handlers.get("desktop:openExternal")?.({}, "https://example.com");
    expect(openedExternally).toEqual(["https://example.com"]);
  });

  it("setClipboard 只接受字符串", async () => {
    const res = (await handlers.get("desktop:setClipboard")?.({}, 123)) as {
      ok: boolean;
      error?: { code: string };
    };
    expect(res.ok).toBe(false);
    expect(res.error?.code).toBe("E_INVALID");

    await handlers.get("desktop:setClipboard")?.({}, "hello");
    expect(writtenClipboard).toEqual(["hello"]);
  });

  it("status 返回后端状态快照", async () => {
    const res = (await handlers.get("desktop:status")?.({})) as { ok: boolean; state?: string };
    expect(res.ok).toBe(true);
    expect(typeof res.state).toBe("string");
  });

  it("壳设置通道齐备且参数校验严格", async () => {
    expect(handlers.has("desktop:getSettings")).toBe(true);
    expect(handlers.has("desktop:setBossKey")).toBe(true);
    expect(handlers.has("desktop:setAutoLaunch")).toBe(true);
    expect(handlers.has("desktop:setStartMinimized")).toBe(true);
    expect(handlers.has("desktop:openRun")).toBe(true);

    const got = (await handlers.get("desktop:getSettings")?.({})) as {
      ok: boolean;
      settings?: { bossKey: string | null };
    };
    expect(got.ok).toBe(true);
    expect(got.settings?.bossKey).toBeNull();

    const badKey = (await handlers.get("desktop:setBossKey")?.({}, 123)) as {
      ok: boolean;
      error?: { code: string };
    };
    expect(badKey.ok).toBe(false);
    expect(badKey.error?.code).toBe("E_INVALID");

    const badLaunch = (await handlers.get("desktop:setAutoLaunch")?.({}, "yes")) as {
      ok: boolean;
      error?: { code: string };
    };
    expect(badLaunch.ok).toBe(false);
    expect(badLaunch.error?.code).toBe("E_INVALID");

    const badRun = (await handlers.get("desktop:openRun")?.({}, "")) as {
      ok: boolean;
      error?: { code: string };
    };
    expect(badRun.ok).toBe(false);
    expect(badRun.error?.code).toBe("E_INVALID");
  });

  it("绑定 Boss Key 会落到设置", async () => {
    const res = (await handlers.get("desktop:setBossKey")?.({}, "Ctrl+Shift+B")) as {
      ok: boolean;
      settings?: { bossKey: string | null };
    };
    expect(res.ok).toBe(true);
    expect(res.settings?.bossKey).toBe("Ctrl+Shift+B");
  });
});
