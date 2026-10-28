/** 全局快捷键：速记面板 + Boss Key。
 *
 * 口径：
 * - **速记面板**固定 ``Ctrl/Cmd+Shift+Space``（可被系统占用 → 记入 conflicts）；
 * - **Boss Key 默认不绑定**（避免与系统/其他软件冲突），仅在用户显式绑定后注册；
 *   绑定失败（被占用）会释放本次注册并如实返回冲突项。
 */
import { globalShortcut } from "electron";

import { toggleQuickPanel } from "./quick";
import { getMainWindow } from "./window";
import { getSettings, updateSettings } from "./settings";

export interface ShortcutResult {
  registered: boolean;
  conflicts: string[];
}

/** 已注册的 Boss Key（用于解绑时释放）。 */
let bossKey: string | null = null;

export function registerShortcuts(): ShortcutResult {
  const conflicts: string[] = [];

  const quick = process.platform === "darwin" ? "Cmd+Shift+Space" : "Ctrl+Shift+Space";
  if (!globalShortcut.register(quick, () => toggleQuickPanel())) {
    conflicts.push(quick);
  }

  // Boss Key：默认不绑定；已配置才注册
  const configured = getSettings().bossKey;
  if (configured) {
    const res = setBossKey(configured);
    conflicts.push(...res.conflicts);
  }

  return { registered: conflicts.length === 0, conflicts };
}

/**
 * 绑定 / 解绑 Boss Key。
 *
 * @param accelerator Electron 快捷键字符串；传 `null` 或空串即解绑。
 */
export function setBossKey(accelerator: string | null): ShortcutResult {
  const conflicts: string[] = [];

  // 先释放旧注册（解绑必须真的释放，否则系统里仍占着）
  if (bossKey) {
    try {
      globalShortcut.unregister(bossKey);
    } catch {
      // 忽略
    }
    bossKey = null;
  }

  const next = accelerator && accelerator.trim() ? accelerator.trim() : null;
  updateSettings({ bossKey: next });

  if (!next) {
    return { registered: true, conflicts };
  }

  const ok = globalShortcut.register(next, () => {
    // Boss Key 语义：显隐切换主窗口（隐藏时再按唤起）
    const win = getMainWindow();
    if (!win) return;
    if (win.isVisible()) {
      win.hide();
    } else {
      win.show();
      win.focus();
    }
  });

  if (!ok) {
    conflicts.push(next);
    // 注册失败 → 不留下「已绑定」的假象，回滚为未绑定
    updateSettings({ bossKey: null });
    return { registered: false, conflicts };
  }

  bossKey = next;
  return { registered: true, conflicts };
}

/** 当前已注册的 Boss Key（未绑定为 null）。 */
export function currentBossKey(): string | null {
  return bossKey;
}

export function unregisterShortcuts(): void {
  globalShortcut.unregisterAll();
  bossKey = null;
}
