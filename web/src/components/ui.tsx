import { T } from "../i18n";
import { useState, type MouseEvent, type ReactNode } from "react";
import { humanize, type Tone } from "../utils/format";

export function Card({ title, actions, children, className = "" }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head">
          {title && <h2>{title}</h2>}
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      <div className="card-body">{children}</div>
    </section>
  );
}

export function Kpi({ label, value, hint, tone = "info", onClick }: { label: string; value: ReactNode; hint?: string; tone?: Tone; onClick?: () => void }) {
  return (
    <button type="button" className={`kpi tone-${tone}`} onClick={onClick} disabled={!onClick} title={hint}>
      <span className="kpi-value">{value}</span>
      <span className="kpi-label">{label}</span>
      {hint && <span className="kpi-hint">{hint}</span>}
    </button>
  );
}

export function Badge({ tone = "muted", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return <span className={`badge tone-${tone}`} title={title}>{children}</span>;
}

export function Loading({ what }: { what?: string }) {
  return <div className="state" role="status"><span className="spinner" aria-hidden /> {what ?? T("common.loading")}…</div>;
}

export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="state state-error" role="alert">
      <strong>{T("common.couldNot")}</strong> {error}
      {onRetry && <button type="button" className="btn btn-sm" onClick={onRetry}>{T("common.retry")}</button>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="state state-empty">{children}</div>;
}

/** Wraps an ApiState: loading / error / content. */
export function Async<T>({ state, children, what }: { state: { data: T | null; error: string | null; loading: boolean; reload: () => void }; children: (d: T) => ReactNode; what?: string }) {
  if (state.error) return <ErrorBox error={state.error} onRetry={state.reload} />;
  if (state.loading && state.data === null) return <Loading what={what} />;
  return state.data === null ? null : <>{children(state.data)}</>;
}

/** Horizontal bars for label -> value (real counts only). */
export function Bars({ data, tone = "ai", format = (v: number) => String(v), onPick }: { data: [string, number][]; tone?: Tone; format?: (v: number) => string; onPick?: (k: string) => void }) {
  const max = Math.max(1, ...data.map(([, v]) => v));
  if (!data.length) return <Empty>{T("common.noData")}</Empty>;
  return (
    <ul className="bars">
      {data.map(([k, v]) => (
        <li key={k} onClick={onPick ? () => onPick(k) : undefined} className={onPick ? "clickable" : ""}>
          <span className="bar-label">{humanize(k)}</span>
          <span className="bar-track"><span className={`bar-fill tone-${tone}`} style={{ width: `${(100 * v) / max}%` }} /></span>
          <span className="bar-value">{format(v)}</span>
        </li>
      ))}
    </ul>
  );
}

/** One row per key, stacked segments (e.g. completed / in progress / not started). */
export function StackBars({ rows, segments }: { rows: [string, Record<string, number>][]; segments: { key: string; label: string; tone: Tone }[] }) {
  if (!rows.length) return <Empty>{T("common.noData")}</Empty>;
  return (
    <div className="stack">
      <div className="legend">{segments.map((s) => <span key={s.key}><i className={`dot tone-${s.tone}`} />{humanize(s.label)}</span>)}</div>
      {rows.map(([k, v]) => {
        const total = segments.reduce((a, s) => a + (v[s.key] ?? 0), 0);
        return (
          <div className="stack-row" key={k}>
            <span className="bar-label">{humanize(k)}</span>
            <span className="stack-track" aria-label={segments.map((s) => `${s.label} ${v[s.key] ?? 0}`).join(", ")}>
              {segments.map((s) => (v[s.key] ?? 0) > 0 && (
                <span key={s.key} className={`stack-seg tone-${s.tone}`} style={{ width: `${(100 * (v[s.key] ?? 0)) / Math.max(total, 1)}%` }} title={`${s.label}: ${v[s.key]}`} />
              ))}
            </span>
            <span className="bar-value">{total}</span>
          </div>
        );
      })}
    </div>
  );
}

export function Modal({ title, onClose, children }: { title: ReactNode; onClose: () => void; children: ReactNode }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : undefined} onClick={(e) => e.stopPropagation()}>
        <header className="card-head"><h2>{title}</h2><button type="button" className="btn btn-sm" onClick={onClose} aria-label={T("as.close")}>✕</button></header>
        <div className="card-body">{children}</div>
      </div>
    </div>
  );
}

/** Field Execution -> AI Understanding -> Schedule Linking -> Human Validation -> Verified Progress */
export function Flow({ steps }: { steps: { label: string; value: ReactNode; tone?: Tone }[] }) {
  return (
    <ol className="flow">
      {steps.map((s, i) => (
        <li key={i} className={`flow-step tone-${s.tone ?? "muted"}`}>
          <span className="flow-label">{s.label}</span>
          <span className="flow-value">{s.value}</span>
        </li>
      ))}
    </ol>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return <div className="field"><span className="field-label">{label}</span><span className="field-value">{children ?? "—"}</span></div>;
}

/** Two values per row (e.g. planned vs actual), each with its own bar on a shared scale. */
export function CompareBars({ rows, a, b }: { rows: [string, number, number][]; a: { label: string; tone: Tone }; b: { label: string; tone: Tone } }) {
  const max = Math.max(1, ...rows.flatMap(([, x, y]) => [x, y]));
  if (!rows.length) return <Empty>{T("common.noData")}</Empty>;
  return (
    <div className="compare">
      <div className="legend"><span><i className={`dot tone-${a.tone}`} />{a.label}</span><span><i className={`dot tone-${b.tone}`} />{b.label}</span></div>
      {rows.map(([k, x, y]) => (
        <div className="compare-row" key={k}>
          <span className="bar-label">{humanize(k)}</span>
          <span className="compare-bars">
            <span className="bar-track"><span className={`bar-fill tone-${a.tone}`} style={{ width: `${(100 * x) / max}%` }} /></span>
            <span className="bar-track"><span className={`bar-fill tone-${b.tone}`} style={{ width: `${(100 * y) / max}%` }} /></span>
          </span>
          <span className="bar-value">{x} / {y}</span>
        </div>
      ))}
    </div>
  );
}

export function PageTitle({ title, subtitle, actions, icon }: { title: string; subtitle?: ReactNode; actions?: ReactNode; icon?: string }) {
  return (
    <div className="page-title">
      {icon && <img className="page-icon" src={`/brand/${icon}.webp`} alt="" width={48} height={48} />}
      <div className="grow"><h1>{title}</h1>{subtitle && <p className="muted">{subtitle}</p>}</div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

/** Cumulative planned vs actual completions over time (the classic project S-curve), with a hover read-out. */
export function SCurve({ rows, asOf, planned, actual, today }: {
  rows: { planned_finish: string; actual_finish: string | null }[]; asOf: string; planned: string; actual: string; today: string }) {
  const [hover, setHover] = useState<number | null>(null);
  if (!rows.length) return <Empty>{T("common.noData")}</Empty>;
  const day = (s: string) => Math.floor(Date.parse(s.slice(0, 10)) / 864e5);
  const iso = (d: number) => new Date(d * 864e5).toISOString().slice(0, 10);
  const pf = rows.map((r) => day(r.planned_finish)).sort((a, b) => a - b);
  const af = rows.flatMap((r) => (r.actual_finish ? [day(r.actual_finish)] : [])).sort((a, b) => a - b);
  const d0 = Math.min(pf[0], af[0] ?? pf[0]) - 1, d1 = Math.max(pf[pf.length - 1], day(asOf)), now = day(asOf);
  const upTo = (xs: number[], d: number) => { let n = 0; while (n < xs.length && xs[n] <= d) n++; return n; };
  const days = Array.from({ length: d1 - d0 + 1 }, (_, i) => d0 + i);
  const P = days.map((d) => upTo(pf, d)), A = days.map((d) => (d <= now ? upTo(af, d) : null));
  const W = 640, H = 220, L = 36, R = 64, T0 = 10, B = 24, n = rows.length;
  const x = (i: number) => L + ((W - L - R) * i) / Math.max(1, days.length - 1), y = (v: number) => T0 + (H - T0 - B) * (1 - v / n);
  const path = (vs: (number | null)[]) => vs.flatMap((v, i) => (v === null ? [] : [`${i && vs[i - 1] !== null ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`])).join("");
  const iNow = Math.min(days.length - 1, now - d0), lastA = A[iNow] ?? 0;
  const move = (e: MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const i = Math.round((((e.clientX - r.left) * W) / r.width - L) / ((W - L - R) / Math.max(1, days.length - 1)));
    setHover(i >= 0 && i < days.length ? i : null);
  };
  return (
    <div className="scurve">
      <div className="legend"><span><i className="dot tone-muted" />{planned}</span><span><i className="dot tone-ok" />{actual}</span></div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${planned} / ${actual}`} onMouseMove={move} onMouseLeave={() => setHover(null)}>
        {[0, 0.5, 1].map((f) => <g key={f}><line className="grid" x1={L} x2={W - R} y1={y(f * n)} y2={y(f * n)} /><text className="axis" x={L - 6} y={y(f * n) + 4} textAnchor="end">{Math.round(f * n)}</text></g>)}
        <text className="axis" x={L} y={H - 6}>{iso(d0)}</text><text className="axis" x={W - R} y={H - 6} textAnchor="end">{iso(d1)}</text>
        <line className="today" x1={x(iNow)} x2={x(iNow)} y1={T0} y2={H - B} /><text className="axis" x={x(iNow) - 4} y={T0 + 20} textAnchor="end">{today} {asOf}</text>
        <path className="line planned" d={path(P)} /><path className="line actual" d={path(A)} />
        <text className="axis" x={W - R + 6} y={y(P[P.length - 1]) + 4}>{P[P.length - 1]}</text>
        <circle className="pt actual" cx={x(iNow)} cy={y(lastA)} r={4} /><text className="axis strong" x={x(iNow) + 8} y={y(lastA) + 4}>{lastA}</text>
        {hover !== null && <g><line className="cross" x1={x(hover)} x2={x(hover)} y1={T0} y2={H - B} />
          <circle className="pt planned" cx={x(hover)} cy={y(P[hover])} r={4} />{A[hover] !== null && <circle className="pt actual" cx={x(hover)} cy={y(A[hover]!)} r={4} />}</g>}
      </svg>
      <p className="small muted" aria-live="polite">{hover !== null ? `${iso(days[hover])} · ${planned}: ${P[hover]} · ${actual}: ${A[hover] ?? "—"}` : `${today} ${asOf} · ${planned}: ${P[iNow]} · ${actual}: ${lastA} / ${n}`}</p>
    </div>
  );
}

/** Activities as a Kanban board by status; late items first, each card opens the schedule. */
export function Kanban<R extends { code: string; name: string; discipline: string | null; status: string; planned_finish: string; actual_finish: string | null }>(
  { rows, asOf, columns, limit = 8, onOpen, onMore }: { rows: R[]; asOf: string; columns: { key: string; tone: Tone }[]; limit?: number;
    onOpen: (r: R) => void; onMore: (status: string) => void }) {
  const late = (r: R) => (r.actual_finish ?? asOf) > r.planned_finish;
  return (
    <div className="kanban">
      {columns.map((c) => {
        const items = rows.filter((r) => r.status === c.key).sort((a, b) => Number(late(b)) - Number(late(a)) || a.planned_finish.localeCompare(b.planned_finish));
        return (
          <section key={c.key} className="kanban-col" aria-label={humanize(c.key)}>
            <header><Badge tone={c.tone}>{humanize(c.key)}</Badge><span className="muted small">{items.length}</span></header>
            {items.slice(0, limit).map((r) => (
              <button type="button" key={r.code} className="kanban-card" onClick={() => onOpen(r)}>
                <span className="mono small">{r.code}</span>
                <span className="kanban-name">{r.name}</span>
                <span className="small muted">{humanize(r.discipline ?? "other")} · {T("kb.due")} {r.planned_finish.slice(0, 10)}
                  {late(r) && <> · <span className="bad-text">{T("kb.late")}</span></>}</span>
              </button>
            ))}
            {items.length > limit && <button type="button" className="linkish small" onClick={() => onMore(c.key)}>{T("kb.more", { n: items.length - limit })}</button>}
          </section>
        );
      })}
    </div>
  );
}
