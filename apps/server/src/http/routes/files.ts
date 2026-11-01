/**
 * 文件路由（契约对齐：app/api/v1/files.py）。
 *
 * 端点：`GET /policy` · `GET /` · `POST /upload` · `GET /{filename}` · `DELETE /{filename}`
 */
import fs from "node:fs";
import path from "node:path";
import type { FastifyInstance } from "fastify";
import { HttpError } from "../../shared/errors.js";
import { settings } from "../../shared/config.js";
import { getLogger } from "../../shared/logger.js";

const logger = getLogger("routes.files");

/** 内置扩展名白名单。 */
const DEFAULT_ALLOWED_EXTENSIONS = [
  ".txt", ".md", ".markdown", ".pdf", ".doc", ".docx", ".xls", ".xlsx",
  ".csv", ".json", ".yaml", ".yml", ".xml", ".html", ".htm",
  ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp",
  ".py", ".js", ".ts", ".tsx", ".jsx", ".sh", ".sql", ".zip",
];

/** 当前生效的扩展名白名单。 */
export function allowedExtensions(): string[] {
  const custom = settings.upload_extension_list;
  return custom.length ? custom : DEFAULT_ALLOWED_EXTENSIONS;
}

/** 内置（默认）扩展名白名单 —— 与「自定义覆盖」区分（契约对齐 Python 侧）。 */
export function builtinExtensions(): string[] {
  return [...DEFAULT_ALLOWED_EXTENSIONS];
}

export async function registerFileRoutes(app: FastifyInstance): Promise<void> {
  app.get("/api/v1/files/policy", async () => ({
    max_file_bytes: settings.upload_max_file_bytes,
    max_request_bytes: settings.upload_max_request_bytes,
    allowed_extensions: allowedExtensions(),
    output_dir: settings.output_dir,
    // 契约对齐（Python 侧）：`builtin_extensions` / `extensions`
    builtin_extensions: builtinExtensions(),
    extensions: allowedExtensions(),
  }));

  app.get("/api/v1/files", async () => {
    const dir = settings.output_dir;
    const items: Array<Record<string, unknown>> = [];
    if (fs.existsSync(dir)) {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (!entry.isFile()) continue;
        const stat = fs.statSync(path.join(dir, entry.name));
        items.push({
          name: entry.name,
          size: stat.size,
          is_image: /\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(entry.name),
          modified_at: stat.mtime.toISOString(),
        });
      }
    }
    items.sort((a, b) => String(b.modified_at).localeCompare(String(a.modified_at)));
    // ⚠️ **键名必须与契约一致**：Python 侧返回 `{"total": N, "files": [...]}` →
    //    前端 `items.value = (await filesList()).files` 读的是 **`files`**。
    //    此前返回 `{items, total}` → 前端拿到 `undefined` → `items.length` 抛错。
    return { total: items.length, files: items };
  });

  app.post("/api/v1/files/upload", async (req, reply) => {
    const parts = req.parts();
    const allowed = allowedExtensions();
    const saved: Array<Record<string, unknown>> = [];
    for await (const part of parts) {
      if (part.type !== "file") continue;
      const ext = path.extname(part.filename).toLowerCase();
      if (!allowed.includes(ext)) {
        throw new HttpError(415, `不支持的文件类型: ${ext || "(无扩展名)"}`);
      }
      const target = path.join(settings.output_dir, path.basename(part.filename));
      await pipeline(part.file, target);
      const stat = fs.statSync(target);
      if (stat.size > settings.upload_max_file_bytes) {
        fs.rmSync(target, { force: true });
        throw new HttpError(413, `文件超过上限（${settings.upload_max_file_bytes} 字节）`);
      }
      saved.push({
        name: path.basename(part.filename),
        size: stat.size,
        path: target,
        is_image: /\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(part.filename),
      });
    }
    if (!saved.length) throw new HttpError(422, "未收到文件");
    logger.info("文件上传完成", { count: saved.length });
    return reply.code(201).send({ ok: true, files: saved, items: saved });
  });

  app.get("/api/v1/files/:filename", async (req, reply) => {
    const filename = String((req.params as Record<string, string>).filename);
    const target = safeJoin(settings.output_dir, filename);
    if (!target) throw new HttpError(400, "非法文件名");
    if (!fs.existsSync(target) || !fs.statSync(target).isFile()) {
      throw new HttpError(404, "文件不存在");
    }
    const stat = fs.statSync(target);
    return reply
      .code(200)
      .type(mimeOf(target))
      .header("Content-Length", String(stat.size))
      .send(fs.readFileSync(target));
  });

  app.delete("/api/v1/files/:filename", async (req) => {
    const filename = String((req.params as Record<string, string>).filename);
    const target = safeJoin(settings.output_dir, filename);
    if (!target) throw new HttpError(400, "非法文件名");
    if (!fs.existsSync(target)) throw new HttpError(404, "文件不存在");
    fs.rmSync(target, { force: true });
    return { ok: true, deleted: filename };
  });
}

/** 安全拼接（防路径穿越）。 */
export function safeJoin(base: string, name: string): string | null {
  const resolved = path.resolve(base, name);
  const resolvedBase = path.resolve(base);
  if (resolved !== resolvedBase && !resolved.startsWith(resolvedBase + path.sep)) return null;
  return resolved;
}

/** MIME 推断。 */
function mimeOf(file: string): string {
  const ext = path.extname(file).toLowerCase();
  const map: Record<string, string> = {
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".zip": "application/zip",
  };
  return map[ext] ?? "application/octet-stream";
}

/** 把可读流写到文件。 */
async function pipeline(stream: NodeJS.ReadableStream, target: string): Promise<void> {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  await new Promise<void>((resolve, reject) => {
    const ws = fs.createWriteStream(target);
    stream.pipe(ws);
    ws.on("finish", () => resolve());
    ws.on("error", reject);
    stream.on("error", reject);
  });
}
