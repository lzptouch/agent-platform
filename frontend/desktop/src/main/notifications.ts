/** 系统通知（后端 → 壳 → 系统通知中心）。 */
import { Notification } from "electron";

import { getMainWindow } from "./window";

export interface NotifyPayload {
  title: string;
  body?: string;
  runId?: string;
}

export function showNotification(payload: NotifyPayload): boolean {
  if (!Notification.isSupported()) return false;
  const n = new Notification({ title: payload.title, body: payload.body ?? "" });
  n.on("click", () => {
    const win = getMainWindow();
    if (win) {
      win.show();
      win.focus();
      if (payload.runId) {
        win.webContents.send("agent:open-run", payload.runId);
      }
    }
  });
  n.show();
  return true;
}
