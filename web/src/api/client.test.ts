import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, apiKey, buildUrl, problemMessage, request } from "./client";

const store = new Map<string, string>();
beforeEach(() => {
  store.clear();
  vi.stubGlobal("sessionStorage", {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => store.set(k, v),
    removeItem: (k: string) => store.delete(k),
  });
});
afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("builds URLs and drops empty query values", () => {
    expect(buildUrl("/api/v1/x", { a: 1, b: "", c: undefined, d: "x y" })).toBe("/api/v1/x?a=1&d=x%20y");
  });

  it("sends the API key from the tab and JSON bodies", async () => {
    apiKey.set("planner-key-0123456789ab");
    const fetch = vi.fn(async () => new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    expect(await api("/api/v1/projects/P/apply", { method: "POST", body: { as_of: "2026-09-16" } })).toEqual({ ok: true });
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/projects/P/apply");
    expect((init.headers as Record<string, string>)["X-API-Key"]).toBe("planner-key-0123456789ab");
    expect(init.body).toBe('{"as_of":"2026-09-16"}');
    apiKey.clear();
    expect(apiKey.get()).toBeNull();
  });

  it("maps problem+json errors and keeps structured detail", async () => {
    const detail = { status: "source_unavailable", reason: "raw_source_file_missing", message: "raw source file for document 3 is unavailable" };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ title: "Not Found", status: 404, detail }), { status: 404 })));
    const err = await request("/x").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.message).toBe(detail.message);
    expect(err.detail).toEqual(detail);
  });

  it("reports an unreachable backend instead of a fake result", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("network"); }));
    const err = (await api("/x").catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
    expect(err.message).toMatch(/Backend unavailable/);
  });

  it("explains validation, auth and role errors", () => {
    expect(problemMessage(422, { detail: [{ loc: ["body", "question"], msg: "too short" }] })).toBe("body.question: too short");
    expect(problemMessage(401, null)).toMatch(/API key/);
    expect(problemMessage(403, {})).toMatch(/planner or admin/);
    expect(problemMessage(409, { detail: "nothing to change" })).toBe("nothing to change");
  });
});
