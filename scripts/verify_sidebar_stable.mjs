/**
 * 侧栏恒定性自检：在多个路由下抓取左侧导航项文本，断言完全一致。
 *
 * 用法：node scripts/verify_sidebar_stable.mjs [--port 9788] [--out tests/report/shots]
 */
import fs from "node:fs";
import path from "node:path";

const args = process.argv.slice(2);
function opt(name, fallback) {
  const i = args.indexOf(`--${name}`);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
}
const PORT = Number(opt("port", 9788));
const OUT = opt("out", "tests/report/shots");
const PATHS = opt("paths", "/workspace,/assistant,/spaces,/admin/capabilities,/admin/artifacts,/chat").split(",");

async function waitPage(seconds) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const pages = (await res.json()).filter((t) => t.type === "page" && t.webSocketDebuggerUrl);
      if (pages.length) return pages[0];
    } catch {
      /* 未就绪 */
    }
    await new Promise((r) => setTimeout(r, 800));
  }
  return null;
}

function connect(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    const pending = new Map();
    let id = 0;
    ws.addEventListener("open", () =>
      resolve({
        send(method, params) {
          const msgId = ++id;
          ws.send(JSON.stringify({ id: msgId, method, params }));
          return new Promise((res, rej) => pending.set(msgId, { res, rej }));
        },
        close: () => ws.close(),
      }),
    );
    ws.addEventListener("message", (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && pending.has(msg.id)) {
        const { res, rej } = pending.get(msg.id);
        pending.delete(msg.id);
        if (msg.error) rej(new Error(msg.error.message));
        else res(msg.result);
      }
    });
    ws.addEventListener("error", reject);
  });
}

async function main() {
  const target = await waitPage(90);
  if (!target) {
    console.log("未找到窗口目标");
    process.exit(2);
  }
  const cdp = await connect(target.webSocketDebuggerUrl);
  await cdp.send("Runtime.enable");
  await cdp.send("Page.enable");
  const evalJs = async (expr) => {
    const r = await cdp.send("Runtime.evaluate", { expression: expr, returnByValue: true });
    return r.result?.value;
  };

  fs.mkdirSync(OUT, { recursive: true });
  const snapshots = [];
  for (const p of PATHS) {
    await evalJs(`location.href = ${JSON.stringify(p)}`);
    await new Promise((r) => setTimeout(r, 2200));
    const items = await evalJs(`(() => {
      const nav = document.querySelector('.sidenav .nav-list');
      if (!nav) return null;
      return Array.from(nav.querySelectorAll('.nav-item')).map((b) => (b.textContent || '').trim());
    })()`);
    snapshots.push({ path: p, items });
    console.log(`${p} → ${items ? items.length : 0} 项: ${items ? items.join(" | ") : "(无)"}`);

    const shot = await cdp.send("Page.captureScreenshot", { format: "png" });
    fs.writeFileSync(path.join(OUT, `sidebar${p.replace(/\//g, "_")}.png`), Buffer.from(shot.data, "base64"));
  }

  const baseline = JSON.stringify(snapshots[0]?.items ?? null);
  const diffs = snapshots.filter((s) => JSON.stringify(s.items ?? null) !== baseline);
  if (diffs.length) {
    console.log(`\n✗ 侧栏在 ${diffs.length} 个路由下与基线不一致：${diffs.map((d) => d.path).join(", ")}`);
    process.exit(1);
  }
  console.log("\n✓ 侧栏在所有路由下完全一致（点击只换右侧内容）");
  cdp.close();
}

main().catch((e) => {
  console.error("自检失败:", e.message);
  process.exit(1);
});
