import { describe, expect, it } from "vitest";

import { isLocalOrigin, localOrigin } from "./navigation";

describe("导航守卫的 origin 比较", () => {
  it("本地 origin 精确匹配才放行", () => {
    expect(isLocalOrigin("http://127.0.0.1:8080/workspace", 8080)).toBe(true);
    expect(isLocalOrigin("http://127.0.0.1:8080/api/v1/x?a=1", 8080)).toBe(true);
  });

  it("前缀相同的外部站点一律拒绝", () => {
    // **D4**：此前用 startsWith 前缀匹配 → `127.0.0.1:8080.evil.com` 可绕过
    expect(isLocalOrigin("http://127.0.0.1:8080.evil.com/", 8080)).toBe(false);
    expect(isLocalOrigin("http://127.0.0.1:8080@evil.com/", 8080)).toBe(false);
    expect(isLocalOrigin("https://127.0.0.1:8080/", 8080)).toBe(false);
    expect(isLocalOrigin("http://localhost:8080/", 8080)).toBe(false);
    expect(isLocalOrigin("http://127.0.0.1:9090/", 8080)).toBe(false);
  });

  it("后端未就绪（无端口）时一律拒绝", () => {
    // **D4**：此前 handle===null 时守卫整体失效 → 任意导航都被允许
    expect(isLocalOrigin("http://127.0.0.1:8080/", null)).toBe(false);
    expect(isLocalOrigin("http://127.0.0.1:8080/", undefined)).toBe(false);
    expect(localOrigin(null)).toBeNull();
    expect(localOrigin(0)).toBeNull();
  });

  it("非法 URL 一律拒绝", () => {
    expect(isLocalOrigin("not-a-url", 8080)).toBe(false);
    expect(isLocalOrigin("", 8080)).toBe(false);
  });
});
