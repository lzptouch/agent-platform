/**
 * Token 估算（契约对齐：services/exec/limits.py 的 `estimate_tokens`）。
 *
 * 粗略估算：4 字符 ≈ 1 token（英文），中文按 1.5 字符 ≈ 1 token。
 */

/** 估算 token 数。 */
export function estimateTokens(text: string): number {
  if (!text) return 0;
  let ascii = 0;
  let cjk = 0;
  for (const ch of text) {
    const code = ch.codePointAt(0) ?? 0;
    if (code >= 0x4e00 && code <= 0x9fff) cjk += 1;
    else if (code < 128) ascii += 1;
    else cjk += 1;
  }
  return Math.ceil(ascii / 4 + cjk / 1.5);
}

/** 估算消息数组的 token 数。 */
export function estimateMessagesTokens(
  messages: Array<{ content?: unknown; role?: string }>,
): number {
  let total = 0;
  for (const m of messages) {
    total += 4; // 每条消息的角色/分隔开销
    total += estimateTokens(String(m.content ?? ""));
  }
  return total;
}
