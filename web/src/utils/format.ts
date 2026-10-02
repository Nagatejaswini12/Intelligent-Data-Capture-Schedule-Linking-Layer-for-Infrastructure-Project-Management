// Display helpers only (no business rules).
export const dash = "—";

export function fmtDate(v: unknown): string {
  if (!v) return dash;
  const s = String(v);
  return s.length >= 10 ? s.slice(0, 10) : s;
}

export function fmtDateTime(v: unknown): string {
  if (!v) return dash;
  const d = new Date(String(v));
  return isNaN(d.getTime()) ? String(v) : `${d.toISOString().slice(0, 10)} ${d.toISOString().slice(11, 16)} UTC`;
}

export function fmtNum(v: unknown, digits = 2): string {
  if (v === null || v === undefined || v === "") return dash;
  const n = Number(v);
  return Number.isFinite(n) ? String(Math.round(n * 10 ** digits) / 10 ** digits) : String(v);
}

export function pct(part: number, whole: number): string {
  return whole ? `${Math.round((100 * part) / whole)}%` : dash;
}

export function humanize(s: unknown): string {
  return s === null || s === undefined ? dash : String(s).replace(/_/g, " ");
}

export type Tone = "ok" | "warn" | "bad" | "info" | "muted" | "ai";

export function decisionTone(decision?: string | null, state?: string | null): Tone {
  if (state === "confirmed") return "ok";
  if (state === "rejected") return "muted";
  if (decision === "matched") return "ai";
  if (decision === "review") return "warn";
  if (decision === "unmatched") return "bad";
  return "muted";
}

export function statusTone(status?: string | null): Tone {
  return status === "completed" ? "ok" : status === "in_progress" ? "info" : "muted";
}

export function variance(days: number | null | undefined): string {
  if (days === null || days === undefined) return dash;
  return days > 0 ? `+${days} d` : days < 0 ? `${days} d` : "on time";
}

export function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}
