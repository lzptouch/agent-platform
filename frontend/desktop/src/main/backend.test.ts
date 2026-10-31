import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./paths", () => ({
  getPaths: () => ({
    installDir: ".",
    userDataDir: ".",
    dataDir: ".",
    logsDir: ".",
    configPath: "config.json",
    runStatePath: "run-state.json",
  }),
  resolveBackendDir: () => ".",
  resolveFrontendDist: () => ".",
  resolvePython: () => "python",
}));

import { isOwnedBySidecar, readRunState } from "./backend";

describe("孤儿回收：pid 归属校验", () => {
  const record = {
    pid: 4242,
    port: 51862,
    started_at: "2026-10-28T10:00:00.000Z",
    exe: "/opt/agent/backend/.venv/bin/python",
  };

  it("命令行含 sidecar 模块名 → 认定归属", () => {
    expect(
      isOwnedBySidecar(
        record,
        "/opt/agent/backend/.venv/bin/python -m app.desktop.launcher",
      ),
    ).toBe(true);
  });

  it("命令行含记录的解释器全路径 → 认定归属", () => {
    expect(
      isOwnedBySidecar(record, "/opt/agent/backend/.venv/bin/python -m other"),
    ).toBe(true);
  });

  it("无关进程 → 不认定归属（pid 已被复用，绝不能杀）", () => {
    expect(
      isOwnedBySidecar(record, "/usr/bin/google-chrome --type=renderer"),
    ).toBe(false);
    expect(
      isOwnedBySidecar(record, "/opt/other/.venv/bin/python -m something_else"),
    ).toBe(false);
  });

  it("读不到命令行 → 不认定归属", () => {
    expect(isOwnedBySidecar(record, null)).toBe(false);
  });
});

describe("run-state 解析", () => {
  let tmp = "";

  beforeEach(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), "wb-runstate-"));
  });

  it("读取 pid / port / started_at / exe", () => {
    const p = path.join(tmp, "run-state.json");
    fs.writeFileSync(
      p,
      JSON.stringify({
        pid: 42,
        port: 51862,
        started_at: "2026-10-28T10:00:00.000Z",
        exe: "/x/python",
      }),
    );
    const rec = readRunState(p);
    expect(rec?.pid).toBe(42);
    expect(rec?.port).toBe(51862);
    expect(rec?.started_at).toBe("2026-10-28T10:00:00.000Z");
    expect(rec?.exe).toBe("/x/python");
  });

  it("文件不存在 / 损坏 / 无有效 pid → null", () => {
    expect(readRunState(path.join(tmp, "missing.json"))).toBeNull();
    const bad = path.join(tmp, "bad.json");
    fs.writeFileSync(bad, "{not-json");
    expect(readRunState(bad)).toBeNull();
    const noPid = path.join(tmp, "nopid.json");
    fs.writeFileSync(noPid, JSON.stringify({ port: 1 }));
    expect(readRunState(noPid)).toBeNull();
  });
});
