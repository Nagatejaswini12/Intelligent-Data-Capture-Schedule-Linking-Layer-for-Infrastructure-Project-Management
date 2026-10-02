// Thin fetch wrapper: base URL, X-API-Key header, JSON, RFC 9457 problem responses -> ApiError.
// The backend is the source of truth; nothing here computes business results.

const BASE: string = (import.meta.env?.VITE_API_BASE_URL as string | undefined) ?? "";
const KEY_STORE = "p2e.apiKey";

export class ApiError extends Error {
  constructor(public status: number, message: string, public detail?: unknown) {
    super(message);
  }
}

/** API key lives only in this browser tab (sessionStorage); it is never part of the build. */
export const apiKey = {
  get(): string | null {
    try {
      return sessionStorage.getItem(KEY_STORE);
    } catch {
      return null;
    }
  },
  set(key: string) {
    try {
      sessionStorage.setItem(KEY_STORE, key);
    } catch {
      /* storage blocked: key lasts for this page only */
      memoryKey = key;
    }
  },
  clear() {
    try {
      sessionStorage.removeItem(KEY_STORE);
    } catch {
      memoryKey = null;
    }
  },
};
let memoryKey: string | null = null;

type Query = Record<string, string | number | boolean | null | undefined>;

export function buildUrl(path: string, query?: Query): string {
  const qs = Object.entries(query ?? {})
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join("&");
  return `${BASE}${path}${qs ? `?${qs}` : ""}`;
}

export function problemMessage(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => `${(d.loc ?? []).join(".")}: ${d.msg}`).join("; ");
  if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: unknown }).message);
  if (status === 401) return "Missing or invalid API key";
  if (status === 403) return "Your role may not perform this action (planner or admin required)";
  return `Request failed (HTTP ${status})`;
}

export interface RequestOptions {
  method?: string;
  query?: Query;
  body?: unknown;
  form?: FormData;
  signal?: AbortSignal;
}

export async function request(path: string, opts: RequestOptions = {}): Promise<Response> {
  const headers: Record<string, string> = {};
  const key = apiKey.get() ?? memoryKey;
  if (key) headers["X-API-Key"] = key;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.query), { method: opts.method ?? "GET", headers, body, signal: opts.signal });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "Backend unavailable - is the API server running?");
  }
  if (!res.ok) {
    let parsed: unknown = null;
    try {
      parsed = await res.json();
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, problemMessage(res.status, parsed), (parsed as { detail?: unknown } | null)?.detail);
  }
  return res;
}

export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  return (await request(path, opts)).json() as Promise<T>;
}

/** Download a protected file (the key cannot go in a plain link). */
export async function download(path: string, filename: string, query?: Query): Promise<void> {
  const blob = await (await request(path, { query })).blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
