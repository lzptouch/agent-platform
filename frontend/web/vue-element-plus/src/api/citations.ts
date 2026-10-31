/**
 * P4-05 · 统一「引用」概念。
 *
 * 此前 RAG 的 `references` 与 Web Research 的 `reference_cards` 是**两种结构**，
 * `ProcessSteps.vue` 分别消费 → 外观与点击行为不一致。
 *
 * 现在统一为 `Citation`：
 * ① 两条链路各自做**适配器**转换到该类型；
 * ② `ProcessSteps` 只渲染 `Citation[]`。
 */

/** 统一引用类型 */
export interface Citation {
  /** 序号（从 1 开始，用于正文角标） */
  index: number
  title: string
  url: string
  snippet: string
  /** 来源链路 */
  source: 'rag' | 'web'
}

function firstString(obj: Record<string, unknown>, keys: string[]): string {
  for (const k of keys) {
    const v = obj[k]
    if (typeof v === 'string' && v.trim()) return v
  }
  return ''
}

/** RAG 引用的条目形态多样（字符串 / {title,url,...} / {content}）——容错解析。 */
export function adaptRagReferences(raw: unknown): Citation[] {
  if (!Array.isArray(raw)) return []
  const out: Citation[] = []
  raw.forEach((item, i) => {
    if (typeof item === 'string') {
      out.push({ index: i + 1, title: item.slice(0, 80), url: '', snippet: item, source: 'rag' })
      return
    }
    if (!item || typeof item !== 'object') return
    const obj = item as Record<string, unknown>
    const title = firstString(obj, ['title', 'name', 'source', 'doc_name'])
    const url = firstString(obj, ['url', 'link', 'href'])
    const snippet = firstString(obj, ['snippet', 'quote', 'content', 'text', 'summary'])
    out.push({
      index: out.length + 1,
      title: title || url || `引用 ${out.length + 1}`,
      url,
      snippet,
      source: 'rag',
    })
  })
  return out
}

/** Web Research 的 `reference_cards`（`titles` / `url` / `content` 形态）。 */
export function adaptReferenceCards(raw: unknown): Citation[] {
  if (!Array.isArray(raw)) return []
  const out: Citation[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const obj = item as Record<string, unknown>
    const titles = obj.titles
    const title = Array.isArray(titles)
      ? String(titles[0] ?? '')
      : firstString(obj, ['title', 'name'])
    const url = firstString(obj, ['url', 'link', 'href'])
    const snippet = firstString(obj, ['content', 'snippet', 'quote', 'text'])
    out.push({
      index: out.length + 1,
      title: title || url || `引用 ${out.length + 1}`,
      url,
      snippet,
      source: 'web',
    })
  }
  return out
}

/** 合并两条链路的引用（RAG 在前，Web 在后），序号连续。 */
export function mergeCitations(...groups: Citation[][]): Citation[] {
  const out: Citation[] = []
  for (const g of groups) {
    for (const c of g) out.push({ ...c, index: out.length + 1 })
  }
  return out
}
