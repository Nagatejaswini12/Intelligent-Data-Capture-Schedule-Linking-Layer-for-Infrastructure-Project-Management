import type { ReactNode } from "react";
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

export function Loading({ what = "Loading" }: { what?: string }) {
  return <div className="state" role="status"><span className="spinner" aria-hidden /> {what}…</div>;
}

export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="state state-error" role="alert">
      <strong>Could not load:</strong> {error}
      {onRetry && <button type="button" className="btn btn-sm" onClick={onRetry}>Retry</button>}
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
  if (!data.length) return <Empty>No data.</Empty>;
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
  if (!rows.length) return <Empty>No data.</Empty>;
  return (
    <div className="stack">
      <div className="legend">{segments.map((s) => <span key={s.key}><i className={`dot tone-${s.tone}`} />{s.label}</span>)}</div>
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
        <header className="card-head"><h2>{title}</h2><button type="button" className="btn btn-sm" onClick={onClose} aria-label="Close">✕</button></header>
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
  if (!rows.length) return <Empty>No data.</Empty>;
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
