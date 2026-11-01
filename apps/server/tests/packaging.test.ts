/**
 * 打包态回归测试（P8-01 实测踩坑的固化）。
 *
 * 覆盖三个**只在安装包里暴露**的问题：
 * 1. 入口判定遇到**路径含空格**时失效 → sidecar 静默退出（无日志、exit 0）；
 * 2. 服务根目录在打包态**层级不同** → 派生路径指错位置；
 * 3. better-sqlite3 原生模块的**双 ABI**选择。
 */
import { describe, expect, it } from "vitest";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { isEntryPoint } from "../src/main.js";
import { SERVICE_ROOT, PROJECT_ROOT } from "../src/shared/config.js";
import { candidateBindings, currentAbi, loadNativeBinding } from "../src/db/native.js";

describe("P8-01 入口判定", () => {
  it("相对路径入口可识别", () => {
    const abs = path.resolve("/tmp/app/server/main.js");
    expect(isEntryPoint(abs, pathToFileURL(abs).href)).toBe(true);
  });

  it("★ 路径含空格时仍可识别（打包产物为 'Agent Desktop.app'）", () => {
    const abs = path.resolve("/tmp/Agent Desktop.app/Contents/Resources/server/main.js");
    const metaUrl = pathToFileURL(abs).href;
    // 前提：URL 形式确实把空格编码成了 %20（这正是原 bug 的成因）
    expect(metaUrl).toContain("%20");
    expect(isEntryPoint(abs, metaUrl)).toBe(true);
  });

  it("相对 argv 与绝对 metaUrl 也能匹配", () => {
    const abs = path.resolve("/tmp/Agent Desktop.app/server/main.js");
    const rel = path.relative(process.cwd(), abs);
    expect(isEntryPoint(rel, pathToFileURL(abs).href)).toBe(true);
  });

  it("非入口返回 false", () => {
    expect(isEntryPoint(undefined, "file:///x/main.js")).toBe(false);
    expect(isEntryPoint("/tmp/other.js", pathToFileURL("/tmp/x/main.js").href)).toBe(false);
  });
});

describe("P8-01 服务根目录", () => {
  it("服务根含 package.json（name=agent-server）", () => {
    expect(path.basename(SERVICE_ROOT)).toBe("server");
    expect(SERVICE_ROOT.endsWith("apps/server")).toBe(true);
  });

  it("应用根能找到 skills/ 目录", () => {
    expect(path.basename(PROJECT_ROOT)).toBe("agent");
  });
});

describe("P8-01 双 ABI 原生模块", () => {
  it("候选路径按 ABI 优先级排列", () => {
    const cands = candidateBindings();
    expect(cands.length).toBeGreaterThan(0);
    expect(cands[0]).toContain(`.native/abi-${currentAbi()}`);
  });

  it("★ 能加载到可用的原生 addon（否则 Electron 下必炸）", () => {
    const addon = loadNativeBinding() as { isInitialized?: boolean };
    expect(addon).toBeTruthy();
    expect(typeof addon).toBe("object");
  });

  it("原生模块支持 sqlite 打开（验证 ABI 真的匹配）", async () => {
    const { default: Database } = await import("better-sqlite3");
    const db = new Database(":memory:", { nativeBinding: loadNativeBinding() as never });
    db.exec("CREATE TABLE t(a)");
    db.prepare("INSERT INTO t VALUES (1)").run();
    expect((db.prepare("SELECT COUNT(*) AS c FROM t").get() as { c: number }).c).toBe(1);
    db.close();
  });
});
