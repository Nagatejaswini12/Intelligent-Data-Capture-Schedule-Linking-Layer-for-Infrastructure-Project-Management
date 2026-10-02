import { ApiError } from "../api/client";
import { p2e, type Evidence as EvidenceT } from "../api/p2e";
import { useApi } from "../hooks/useApi";
import { useApp } from "../state";
import { Badge, ErrorBox, Loading, Modal } from "./ui";

/** Shows exactly where an event came from (Phase 2 evidence endpoint), including the Phase 3.2 "source unavailable" case. */
export function EvidenceView({ eventId }: { eventId: number }) {
  const { project } = useApp();
  const state = useApi(async (): Promise<{ ev?: EvidenceT; missing?: Record<string, unknown> }> => {
    try {
      return { ev: await p2e.evidence(project.code, eventId) };
    } catch (e) {
      const d = e instanceof ApiError ? (e.detail as Record<string, unknown> | undefined) : undefined;
      if (d && d.status === "source_unavailable") return { missing: d };   // Phase 3.2 controlled 404
      throw e;
    }
  }, [eventId]);
  const unavailable = state.data?.missing;
  if (unavailable) {
    const meta = (unavailable.evidence ?? {}) as Record<string, unknown>;
    return (
      <div className="evidence">
        <Badge tone="warn">raw source file unavailable</Badge> <span className="muted">{String(unavailable.reason ?? "")}</span>
        <p className="muted">The audit record is intact; the stored metadata is shown instead.</p>
        <pre className="source">{String(meta.source_text ?? "")}</pre>
        <p className="muted">{String(meta.filename ?? "")} · {JSON.stringify(meta.source_ref ?? {})}</p>
      </div>
    );
  }
  if (state.error) return <ErrorBox error={state.error} onRetry={state.reload} />;
  if (state.loading || !state.data?.ev) return <Loading what="Reading the stored source" />;
  const ev = state.data.ev;
  return (
    <div className="evidence">
      <p>
        <strong>{ev.filename}</strong> · {ev.kind === "spreadsheet" ? `sheet ${ev.sheet}, row ${ev.row}` : `line ${ev.line_number}`}{" "}
        {ev.found_in_source ? <Badge tone="ok">verified in source</Badge> : <Badge tone="bad">not found in source</Badge>}
      </p>
      {ev.context && (
        <pre className="source">
          {ev.context.map((c) => (
            <div key={c.line} className={c.line === ev.line_number ? "hl-line" : ""}>
              <span className="ln">{c.line}</span>
              {c.line === ev.line_number && ev.span_start != null && ev.span_end != null ? (
                <>{c.text.slice(0, ev.span_start)}<mark>{c.text.slice(ev.span_start, ev.span_end)}</mark>{c.text.slice(ev.span_end)}</>
              ) : c.text}
            </div>
          ))}
        </pre>
      )}
      {ev.cells && (
        <table className="table compact">
          <thead><tr><th>Cell</th><th>Header</th><th>Value</th><th>In file</th></tr></thead>
          <tbody>{ev.cells.map((c) => (
            <tr key={c.cell}><td className="mono">{c.cell}</td><td>{c.header}</td><td>{String(c.value)}</td>
              <td>{c.matches ? <Badge tone="ok">match</Badge> : <Badge tone="bad">{String(c.value_in_file)}</Badge>}</td></tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}

export function EvidenceModal({ eventId, onClose }: { eventId: number; onClose: () => void }) {
  return <Modal title={`Evidence · event ${eventId}`} onClose={onClose}><EvidenceView eventId={eventId} /></Modal>;
}
