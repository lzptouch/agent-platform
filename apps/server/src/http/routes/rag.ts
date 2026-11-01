/**
 * RAG 路由（契约对齐：app/api/v1/rag.py）。
 *
 * 端点：`POST /query` · `POST /retrieval` · `POST /ingest` · `GET /stats`
 */
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import type { FastifyInstance } from "fastify";
import { HttpError } from "../../shared/errors.js";
import { RagStore, ragStore, chunkText } from "../../domain/rag/store.js";
import { settings } from "../../shared/config.js";
import { getDb } from "../../db/client.js";
import { utcNow } from "../../db/schema.js";
import { getEmbeddingClient, chat } from "../../shared/llm.js";
import { LIMITS } from "../../shared/config.js";

/** Embedding（DashScope text-embedding-v3，1024 维，批 10 条）。 */
async function embed(texts: string[]): Promise<Float32Array[]> {
  const client = getEmbeddingClient();
  const out: Float32Array[] = [];
  for (let i = 0; i < texts.length; i += LIMITS.embeddingBatch) {
    const batch = texts.slice(i, i + LIMITS.embeddingBatch);
    const response = await client.embeddings.create({
      model: "text-embedding-v3",
      input: batch,
      dimensions: LIMITS.embeddingDim,
    });
    for (const item of response.data) {
      out.push(new Float32Array(item.embedding));
    }
  }
  return out;
}

export async function registerRagRoutes(app: FastifyInstance): Promise<void> {
  app.post("/api/v1/rag/retrieval", async (req) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const query = String(body.query ?? "");
    if (!query) throw new HttpError(422, "缺少 query");
    const limit = Number(body.limit ?? LIMITS.ragLimit);
    if (!settings.has_api_key) {
      throw new HttpError(503, "未配置 DASHSCOPE_API_KEY，Embedding 不可用");
    }
    const chunks = await ragStore.hybridSearch(query, async (q) => {
      const [vec] = await embed([q]);
      return vec;
    }, limit);
    return { query, chunks, count: chunks.length };
  });

  app.post("/api/v1/rag/query", async (req) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const query = String(body.query ?? "");
    if (!query) throw new HttpError(422, "缺少 query");
    const limit = Number(body.limit ?? LIMITS.ragLimit);
    if (!settings.has_api_key) {
      throw new HttpError(503, "未配置 DASHSCOPE_API_KEY，RAG 问答不可用");
    }
    const chunks = await ragStore.hybridSearch(query, async (q) => {
      const [vec] = await embed([q]);
      return vec;
    }, limit);
    const references = chunks.map((c, i) => `[${i + 1}] ${c}`).join("\n\n");
    if (!chunks.length) {
      return { query, references: "", answer: "" };
    }
    const answer = await chat(
      `请基于以下资料回答问题，并在引用处标注 [n] 编号。\n\n${references}\n\n问题：${query}`,
      settings.rag_model,
    );
    return { query, references, answer };
  });

  app.post("/api/v1/rag/ingest", async (req) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const recreate = Boolean(body.recreate ?? true);
    if (!settings.has_api_key) {
      throw new HttpError(503, "未配置 DASHSCOPE_API_KEY，无法入库");
    }
    const pdfDir = settings.pdf_dir;
    if (!fs.existsSync(pdfDir)) {
      throw new HttpError(404, `PDF 目录不存在: ${pdfDir}`);
    }
    const files = fs
      .readdirSync(pdfDir)
      .filter((f) => f.toLowerCase().endsWith(".pdf"))
      .map((f) => path.join(pdfDir, f));

    const db = getDb();
    if (recreate) db.prepare("DELETE FROM rag_documents").run();

    let ingested = 0;
    let skipped = 0;
    let totalChunks = 0;
    for (const file of files) {
      const content = fs.readFileSync(file);
      const contentHash = crypto.createHash("sha256").update(content).digest("hex");
      const docId = RagStore.docId(file, contentHash);
      const exists = db
        .prepare("SELECT doc_id FROM rag_documents WHERE doc_id = ?")
        .get(docId);
      if (exists && !recreate) {
        skipped += 1;
        continue;
      }
      const text = extractPdfText(content);
      const chunks = chunkText(text);
      if (!chunks.length) {
        skipped += 1;
        continue;
      }
      const vectors = await embed(chunks);
      ragStore.upsertDocument(
        docId,
        chunks.map((c, i) => ({ text: c, dense: vectors[i] })),
      );
      const now = utcNow();
      db.prepare(
        `INSERT INTO rag_documents (doc_id, source_path, content_hash, chunk_count, collection,
          created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(doc_id) DO UPDATE SET chunk_count = excluded.chunk_count,
           updated_at = excluded.updated_at`,
      ).run(
        docId,
        file,
        contentHash,
        chunks.length,
        settings.milvus_collection,
        now,
        now,
      );
      ingested += 1;
      totalChunks += chunks.length;
    }
    return {
      chunks: totalChunks,
      entities: ingested,
      collection: settings.milvus_collection,
      ingested,
      skipped,
      removed: 0,
      documents: ingested,
    };
  });

  app.get("/api/v1/rag/stats", async () => {
    const stats = ragStore.stats();
    return {
      collection: stats.collection,
      entities: stats.documents,
      dense_dim: LIMITS.embeddingDim,
      embedding_model: "text-embedding-v3",
      llm_available: settings.has_api_key,
    };
  });
}

/** 极简 PDF 文本抽取（PDF 头尾解析；生产环境走 pdfjs-dist）。 */
function extractPdfText(buffer: Buffer): string {
  const raw = buffer.toString("latin1");
  const chunks: string[] = [];
  const re = /\((?:\\.|[^\\()])*\)\s*Tj/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(raw)) !== null) {
    const text = match[0].slice(1, match[0].lastIndexOf(")"));
    chunks.push(text.replace(/\\([()\\])/g, "$1"));
  }
  return chunks.join("\n");
}
