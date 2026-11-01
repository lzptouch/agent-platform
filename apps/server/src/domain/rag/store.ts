/**
 * RAG 向量层（design §7.1：Milvus Lite → 本地混合检索）。
 *
 * 现状语义（必须等价）：
 * - 稠密：DashScope `text-embedding-v3`，**1024 维**，度量 IP；
 * - 稀疏：BM25（`k1=1.5, b=0.75`）；
 * - 融合：`WeightedRanker(sparse=0.7, dense=1.0)`，`limit=10`；
 * - 幂等：`doc_id = sha256(路径 | 内容哈希)`。
 *
 * 实现：**SQLite BLOB + 内存 BM25 倒排**（零原生依赖）。
 */
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import Database from "better-sqlite3";
import { getDb } from "../../db/client.js";
import { loadNativeBinding } from "../../db/native.js";
import { settings, type Settings } from "../../shared/config.js";
import { getLogger } from "../../shared/logger.js";
import { LIMITS } from "../../shared/config.js";

const logger = getLogger("rag.store");

const CHUNKS_DDL = `
CREATE TABLE IF NOT EXISTS chunks (
  id         INTEGER PRIMARY KEY,
  doc_id     TEXT NOT NULL,
  seq        INTEGER NOT NULL,
  text       TEXT NOT NULL,
  dense      BLOB NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
`;

/** 中英文分词（`Intl.Segmenter` 支持中文，零依赖）。 */
const segmenter = new Intl.Segmenter("zh", { granularity: "word" });

export function tokenize(text: string): string[] {
  if (!text) return [];
  const out: string[] = [];
  for (const seg of segmenter.segment(text)) {
    const word = seg.segment.trim().toLowerCase();
    if (!word) continue;
    // 英文再按非字母数字切分
    if (/^[a-z0-9_\-]+$/.test(word)) {
      out.push(word);
    } else {
      for (const part of word.split(/[^\p{L}\p{N}_-]+/u)) {
        if (part) out.push(part.toLowerCase());
      }
    }
  }
  return out;
}

/** 切块（RecursiveCharacterTextSplitter 等价，chunk_size=1000, overlap=0）。 */
export function chunkText(text: string, chunkSize = 1000): string[] {
  const normalized = text.replace(/\r\n/g, "\n").trim();
  if (!normalized) return [];
  const chunks: string[] = [];
  let start = 0;
  while (start < normalized.length) {
    let end = Math.min(start + chunkSize, normalized.length);
    if (end < normalized.length) {
      // 优先在换行或空格处切分
      const window = normalized.slice(start, end);
      const breakAt = Math.max(window.lastIndexOf("\n"), window.lastIndexOf(" "));
      if (breakAt > chunkSize * 0.5) end = start + breakAt + 1;
    }
    chunks.push(normalized.slice(start, end).trim());
    start = end;
  }
  return chunks.filter((c) => c.length > 0);
}

/** BM25 打分（参数对齐 Milvus 默认）。 */
export class Bm25Index {
  private postings = new Map<string, number[]>();
  private docLengths: number[] = [];
  private avgLength = 0;
  private totalDocs = 0;

  /** 重建索引。 */
  rebuild(docs: string[]): void {
    this.postings.clear();
    this.docLengths = [];
    this.totalDocs = docs.length;
    docs.forEach((doc, docId) => {
      const tokens = tokenize(doc);
      this.docLengths.push(tokens.length);
      const counts = new Map<string, number>();
      for (const t of tokens) counts.set(t, (counts.get(t) ?? 0) + 1);
      for (const [term, count] of counts) {
        let list = this.postings.get(term);
        if (!list) {
          list = [];
          this.postings.set(term, list);
        }
        for (let i = 0; i < count; i += 1) list.push(docId);
      }
    });
    const total = this.docLengths.reduce((a, b) => a + b, 0);
    this.avgLength = this.totalDocs ? total / this.totalDocs : 0;
  }

  /** 检索（返回 docId → 分数）。 */
  search(query: string, limit = 50): Map<number, number> {
    const scores = new Map<number, number>();
    const terms = tokenize(query);
    if (!terms.length || !this.totalDocs) return scores;
    const k1 = LIMITS.bm25K1;
    const b = LIMITS.bm25B;
    for (const term of terms) {
      const list = this.postings.get(term);
      if (!list?.length) continue;
      const df = list.length;
      const idf = Math.log(1 + (this.totalDocs - df + 0.5) / (df + 0.5));
      const tfMap = new Map<number, number>();
      for (const docId of list) tfMap.set(docId, (tfMap.get(docId) ?? 0) + 1);
      for (const [docId, tf] of tfMap) {
        const dl = this.docLengths[docId] ?? 0;
        const denom = tf + k1 * (1 - b + (b * dl) / (this.avgLength || 1));
        scores.set(docId, (scores.get(docId) ?? 0) + idf * ((tf * (k1 + 1)) / denom));
      }
    }
    return new Map(
      [...scores.entries()].sort((a, b) => b[1] - a[1]).slice(0, limit),
    );
  }
}

/** 向量索引抽象（为将来规模增长预留）。 */
export interface VectorIndex {
  upsert(docId: string, chunks: Array<{ text: string; dense: Float32Array }>): void;
  remove(docId: string): void;
  search(query: Float32Array, topK: number): Array<{ index: number; score: number }>;
}

/** 暴力检索实现（先落地）。 */
export class BruteForceIndex implements VectorIndex {
  private texts: string[] = [];
  private vectors: Float32Array[] = [];

  upsert(docId: string, chunks: Array<{ text: string; dense: Float32Array }>): void {
    this.remove(docId);
    for (const c of chunks) {
      this.texts.push(c.text);
      this.vectors.push(c.dense);
    }
  }

  remove(docId: string): void {
    // 由 store 统一处理（此处仅接口占位）
    void docId;
  }

  search(query: Float32Array, topK: number): Array<{ index: number; score: number }> {
    const scored: Array<{ index: number; score: number }> = [];
    for (let i = 0; i < this.vectors.length; i += 1) {
      const v = this.vectors[i];
      let dot = 0;
      for (let j = 0; j < query.length; j += 1) dot += v[j] * query[j];
      scored.push({ index: i, score: dot });
    }
    scored.sort((a, b) => b.score - a.score);
    return scored.slice(0, topK);
  }
}

export interface RagStats {
  documents: number;
  chunks: number;
  collection: string;
  vectors_dir: string;
}

/** min-max 归一化（对齐 Milvus `WeightedRanker` 内部行为）。 */
function minMaxNormalize(values: number[]): number[] {
  if (!values.length) return values;
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (max === min) return values.map(() => 0);
  return values.map((v) => (v - min) / (max - min));
}

export class RagStore {
  private db: Database.Database | null = null;
  private index = new BruteForceIndex();
  private bm25 = new Bm25Index();
  private texts: string[] = [];
  private loaded = false;

  constructor(private readonly s: Settings = settings) {}

  /** 打开向量库（`userData/data/vectors/chunks.db`）。 */
  private db_(): Database.Database {
    if (this.db) return this.db;
    fs.mkdirSync(this.s.vectors_dir, { recursive: true });
    const file = path.join(this.s.vectors_dir, "chunks.db");
    // ⚠️ **必须显式传 `nativeBinding`**（design/16 R5）：否则 better-sqlite3 会走
    // `bindings` 的路径猜测 → 在 Electron（ABI 130）下加载到 Node 版（ABI 137）
    // 二进制 → 抛 ERR_DLOPEN_FAILED → 整个 RAG 路由 500。
    this.db = new Database(file, { nativeBinding: loadNativeBinding() as never });
    this.db.pragma("journal_mode = WAL");
    this.db.pragma("synchronous = NORMAL");
    this.db.exec(CHUNKS_DDL);
    return this.db;
  }

  /** 载入全部 chunk 到内存（稠密向量扁平化 + BM25 倒排）。 */
  load(): void {
    if (this.loaded) return;
    const db = this.db_();
    const rows = db.prepare("SELECT id, text, dense FROM chunks ORDER BY id").all() as Array<{
      id: number;
      text: string;
      dense: Buffer;
    }>;
    this.texts = [];
    const vectors: Float32Array[] = [];
    for (const row of rows) {
      this.texts.push(row.text);
      vectors.push(new Float32Array(row.dense.buffer, row.dense.byteOffset, row.dense.byteLength / 4));
    }
    this.index = new BruteForceIndex();
    // 逐 doc 重建（doc_id 需从表中取）
    const docRows = db.prepare("SELECT doc_id, seq, text, dense FROM chunks ORDER BY id").all() as Array<{
      doc_id: string;
      seq: number;
      text: string;
      dense: Buffer;
    }>;
    const grouped = new Map<string, Array<{ text: string; dense: Float32Array }>>();
    for (const row of docRows) {
      const arr = grouped.get(row.doc_id) ?? [];
      arr.push({
        text: row.text,
        dense: new Float32Array(
          row.dense.buffer,
          row.dense.byteOffset,
          row.dense.byteLength / 4,
        ),
      });
      grouped.set(row.doc_id, arr);
    }
    for (const [docId, chunks] of grouped) {
      this.index.upsert(docId, chunks);
    }
    this.bm25.rebuild(this.texts);
    this.loaded = true;
    logger.info("向量库已载入", { chunks: this.texts.length });
  }

  /** 入库（幂等：同 doc_id 直接覆盖）。 */
  upsertDocument(docId: string, chunks: Array<{ text: string; dense: Float32Array }>): void {
    const db = this.db_();
    const del = db.prepare("DELETE FROM chunks WHERE doc_id = ?");
    const ins = db.prepare(
      "INSERT INTO chunks (doc_id, seq, text, dense, created_at) VALUES (?, ?, ?, ?, ?)",
    );
    const now = new Date().toISOString();
    db.transaction(() => {
      del.run(docId);
      chunks.forEach((c, i) => {
        ins.run(docId, i, c.text, Buffer.from(c.dense.buffer, c.dense.byteOffset, c.dense.byteLength), now);
      });
    })();
    this.loaded = false;
    this.load();
  }

  /** 删除某文档的全部 chunk。 */
  removeDocument(docId: string): void {
    this.db_().prepare("DELETE FROM chunks WHERE doc_id = ?").run(docId);
    this.loaded = false;
    this.load();
  }

  /** 混合检索（稠密 + BM25，min-max 归一化后加权融合）。 */
  async hybridSearch(
    query: string,
    embed: (text: string) => Promise<Float32Array>,
    limit: number = LIMITS.ragLimit as number,
  ): Promise<string[]> {
    this.load();
    const denseVec = await embed(query);

    const denseHits = this.index.search(denseVec, Math.max(limit * 5, 50));
    const sparseHits = this.bm25.search(query, Math.max(limit * 5, 50));

    const denseNorm = minMaxNormalize(denseHits.map((h) => h.score));
    const sparseNorm = minMaxNormalize([...sparseHits.values()]);

    const fused = new Map<number, number>();
    denseHits.forEach((hit, i) => {
      fused.set(hit.index, (fused.get(hit.index) ?? 0) + LIMITS.ragDenseWeight * (denseNorm[i] ?? 0));
    });
    for (const [docIdx, score] of sparseHits) {
      const norm = sparseNorm[[...sparseHits.keys()].indexOf(docIdx)] ?? 0;
      fused.set(docIdx, (fused.get(docIdx) ?? 0) + LIMITS.ragSparseWeight * norm);
    }

    return [...fused.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, limit)
      .map(([idx]) => this.texts[idx])
      .filter(Boolean);
  }

  /** 统计（台账在主库，向量在向量库）。 */
  stats(): RagStats {
    const vectorDb = this.db_();
    const chunks = vectorDb.prepare("SELECT COUNT(*) AS c FROM chunks").get() as { c: number };
    let documents = 0;
    try {
      const main = getDb();
      const docs = main.prepare("SELECT COUNT(*) AS c FROM rag_documents").get() as { c: number };
      documents = docs?.c ?? 0;
    } catch {
      documents = 0;
    }
    return {
      documents,
      chunks: chunks?.c ?? 0,
      collection: this.s.milvus_collection,
      vectors_dir: this.s.vectors_dir,
    };
  }

  /** 计算 doc_id（幂等键）= sha256(路径 | 内容哈希)。 */
  static docId(sourcePath: string, contentHash: string): string {
    return crypto
      .createHash("sha256")
      .update(`${sourcePath}|${contentHash}`)
      .digest("hex");
  }
}

/** 全局单例。 */
export const ragStore = new RagStore();
