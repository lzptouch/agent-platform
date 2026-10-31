/** 导航守卫的纯逻辑（便于单测）。

**D4**：此前用 `url.startsWith("http://127.0.0.1:<port>")` 前缀匹配 ——
`http://127.0.0.1:8080.evil.com/` 满足该前缀 → 放行到外部站点；
且后端未就绪（handle === null）时守卫整体失效 → 任意导航都被允许。
修复：origin **精确**比较；后端未就绪时**一律拒绝**。
*/

/** 本地 sidecar 的 origin（端口未知 → null）。 */
export function localOrigin(port: number | null | undefined): string | null {
  if (typeof port !== "number" || !Number.isInteger(port) || port <= 0) return null;
  return `http://127.0.0.1:${port}`;
}

/** URL 的 origin 是否**精确**等于本地 sidecar 的 origin。 */
export function isLocalOrigin(url: string, port: number | null | undefined): boolean {
  const origin = localOrigin(port);
  if (!origin) return false;
  try {
    return new URL(url).origin === origin;
  } catch {
    return false; // 非法 URL 一律拒绝
  }
}
