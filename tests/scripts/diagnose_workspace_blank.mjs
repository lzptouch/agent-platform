/**
 * 桌面端「助理页空白」诊断：抓控制台错误 + 页面文本 + 截图。
 *
 * 用法：node tests/scripts/diagnose_workspace_blank.mjs [--port 9777] [--out tests/report/shots]
 */
import fs from "node:fs";
import path from "node:path";

const args = process.argv.slice(2);
function opt(name, fallback) {
  const i = args.indexOf(`--${name}`);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
}
const PORT = Number(opt("port", 9777));
const OUT = opt("out", "tests/report/shots");

async function listTargets() {
  const res = await fetch(`http://127.0.0.1:${PORT}/json/list`);
  return res.json();
}

async function waitPage(seconds) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    try {
      const targets = await listTargets();
      const pages = targets.filter((t) => t.type === "page" && t.webSocketDebuggerUrl);
      if (pages.length) return pages;
    } catch {
      // 端口未就绪
    }
    await new Promise((r) => setTimeout(r, 800));
  }
  return [];
}

function connect(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    const pending = new Map();
    const logs = [];
    let id = 0;
    ws.addEventListener("open", () =>
      resolve({
        send(method, params) {
          const msgId = ++id;
          ws.send(JSON.stringify({ id: msgId, method, params }));
          return new Promise((res, rej) => pending.set(msgId, { res, rej }));
        },
        logs,
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
        return;
      }
      if (msg.method === "Runtime.consoleAPICalled") {
        const text = (msg.params.args || [])
          .map((a) => a.value ?? a.description ?? a.type)
          .join(" ");
        logs.push(`[${msg.params.type}] ${text}`);
      }
      if (msg.method === "Runtime.exceptionThrown") {
        const d = msg.params.exceptionDetails;
        logs.push(`[exception] ${d.exception?.description ?? d.text}`);
      }
    });
    ws.addEventListener("error", reject);
  });
}

async function main() {
  const pages = await waitPage(90);
  if (!pages.length) {
    console.log("未找到可接管的窗口目标");
    process.exit(2);
  }
  const target = pages[0];
  console.log("窗口 URL:", target.url);

  const cdp = await connect(target.webSocketDebuggerUrl);
  await cdp.send("Runtime.enable");
  await cdp.send("Log.enable");
  await cdp.send("Page.enable");

  const evalJs = async (expr) => {
    const r = await cdp.send("Runtime.evaluate", { expression: expr, returnByValue: true });
    return r.result?.value;
  };

  // 先回到工作台（助理入口在 v3 侧栏里）
  await evalJs("location.href = '/workspace'");
  await new Promise((r) => setTimeout(r, 2500));

  console.log("--- 点击「助理」前 ---");
  console.log("当前路由:", await evalJs("location.pathname"));
  console.log("body 文本片段:", JSON.stringify((await evalJs("document.body ? document.body.innerText.slice(0,200) : ''")) || ""));

  // 点击侧栏的「助理」入口
  const clicked = await evalJs(`(() => {
    const nodes = Array.from(document.querySelectorAll('button, a, .nav-item, [class*="nav"] *'));
    const target = nodes.find((n) => (n.textContent || '').trim() === '助理' || (n.textContent || '').trim().includes('助理'));
    if (!target) return 'NOT_FOUND';
    target.click();
    return 'CLICKED:' + (target.className || target.tagName);
  })()`);
  console.log("点击结果:", clicked);

  // 等待路由切换与渲染
  await new Promise((r) => setTimeout(r, 2500));
  console.log("--- 点击后 ---");
  console.log("当前路由:", await evalJs("location.pathname"));
  console.log("body 文本长度:", await evalJs("document.body ? document.body.innerText.length : -1"));
  console.log("body 文本片段:", JSON.stringify((await evalJs("document.body ? document.body.innerText.slice(0,300) : ''")) || ""));
  console.log("根节点子元素数:", await evalJs("document.querySelector('#app') ? document.querySelector('#app').children.length : -1"));
  console.log("根节点 HTML 片段:", JSON.stringify((await evalJs("document.querySelector('#app') ? document.querySelector('#app').innerHTML.slice(0,400) : ''")) || ""));
  console.log("body 文本长度:", await evalJs("document.body ? document.body.innerText.length : -1"));
  console.log("body 文本片段:", JSON.stringify((await evalJs("document.body ? document.body.innerText.slice(0,300) : ''")) || ""));
  console.log("根节点子元素数:", await evalJs("document.querySelector('#app') ? document.querySelector('#app').children.length : -1"));
  console.log("根节点 HTML 片段:", JSON.stringify((await evalJs("document.querySelector('#app') ? document.querySelector('#app').innerHTML.slice(0,300) : ''")) || ""));

  console.log("--- 控制台 ---");
  for (const line of cdp.logs.slice(-30)) console.log(line);

  // 截图
  fs.mkdirSync(OUT, { recursive: true });
  const shot = await cdp.send("Page.captureScreenshot", { format: "png" });
  const file = path.join(OUT, "workspace-blank.png");
  fs.writeFileSync(file, Buffer.from(shot.data, "base64"));
  console.log("截图:", file);

  cdp.close();
}

main().catch((e) => {
  console.error("诊断失败:", e.message);
  process.exit(1);
});
