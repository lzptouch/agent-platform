/**
 * 桌面端路由渲染自检：逐个访问关键路径 → 检查是否渲染出内容 → 截图。
 *
 * 用法：node tests/scripts/verify_desktop_routes.mjs [--port 9788] [--out tests/report/shots]
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
const PATHS = opt("paths", "/workspace,/assistant,/spaces,/admin/capabilities,/nope-404").split(",");

async function listTargets() {
  const res = await fetch(`http://127.0.0.1:${PORT}/json/list`);
  return res.json();
}

async function waitPage(seconds) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    try {
      const pages = (await listTargets()).filter((t) => t.type === "page" && t.webSocketDebuggerUrl);
      if (pages.length) return pages[0];
    } catch {
      /* 端口未就绪 */
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
  let failures = 0;

  for (const p of PATHS) {
    await evalJs(`location.href = ${JSON.stringify(p)}`);
    await new Promise((r) => setTimeout(r, 2500));
    const route = await evalJs("location.pathname");
    const len = await evalJs("document.body ? document.body.innerText.trim().length : -1");
    const children = await evalJs("document.querySelector('#app') ? document.querySelector('#app').children.length : -1");
    const ok = Number(len) > 20 && Number(children) > 0;
    if (!ok) failures += 1;
    console.log(`${ok ? "✓" : "✗"} ${p} → 实际路由 ${route} | 文本长度 ${len} | #app 子节点 ${children}`);

    const shot = await cdp.send("Page.captureScreenshot", { format: "png" });
    const file = path.join(OUT, `route${p.replace(/\//g, "_")}.png`);
    fs.writeFileSync(file, Buffer.from(shot.data, "base64"));
  }

  console.log(failures === 0 ? "全部路径渲染正常" : `${failures} 个路径渲染异常（空白）`);
  cdp.close();
  process.exit(failures === 0 ? 0 : 1);
}

main().catch((e) => {
  console.error("自检失败:", e.message);
  process.exit(1);
});
