import { useState } from "react";
import { p2e, type LinkOut } from "../api/p2e";
import { EvidenceModal } from "../components/Evidence";
import { Async, Badge, Card, Empty, ErrorBox, PageTitle } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useApp } from "../state";
import { decisionTone, fmtDate, humanize } from "../utils/format";
import { href, navigate, useRoute } from "../utils/route";

export function ReportsPage() {
  const { project, live } = useApp();
  const c = project.code;
  const { params } = useRoute();
  const selected = params.get("doc") ? Number(params.get("doc")) : null;
  const [kind, setKind] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const docs = useApi(() => p2e.documents(c, { kind: kind || undefined, limit: 500 }), [c, kind, live]);

  const act = async (label: string, fn: () => Promise<string>) => {
    setBusy(label);
    setMsg(null);
    try {
      setMsg({ tone: "ok", text: await fn() });
      docs.reload();
    } catch (e) {
      setMsg({ tone: "bad", text: (e as Error).message });
    } finally {
      setBusy(null);
    }
  };

  const upload = (file: File) => act("upload", async () => {
    const d = await p2e.upload(c, file);
    const r = await p2e.process(c, d.id);
    const l = await p2e.runLinker(c);
    navigate("reports", { doc: d.id });
    return `${d.filename}: stored, extraction ${r.outcome} (${r.run.events_total} events), linking ${JSON.stringify(l.counts)}.`;
  });

  return (
    <>
      <PageTitle title="Field reports" subtitle="Daily progress reports, discipline trackers and Time Agent messages, with what was extracted from each."
        actions={<>
          <label className="btn btn-primary">{busy === "upload" ? "Uploading…" : "Upload DPR / sheet"}
            <input type="file" accept=".txt,.xlsx" hidden disabled={!!busy} onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) upload(f); }} />
          </label>
          <button type="button" className="btn" disabled={!!busy} onClick={() => act("process", async () => `Processed: ${JSON.stringify((await p2e.processAll(c)).counts)}`)}>Process all</button>
          <button type="button" className="btn" disabled={!!busy} onClick={() => act("link", async () => { const r = await p2e.runLinker(c); return `Linker: ${JSON.stringify(r.counts)}; conflicts ${JSON.stringify(r.conflicts)}`; })}>Run linker</button>
        </>} />
      {msg && (msg.tone === "bad" ? <ErrorBox error={msg.text} /> : <div className="state state-ok">{msg.text}</div>)}
      <div className="split">
        <Card title="Source documents" actions={
          <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Document type">
            <option value="">All types</option><option value="dpr_text">Text reports</option><option value="spreadsheet">Spreadsheets</option><option value="schedule_import">Schedule imports</option>
          </select>}>
          <Async state={docs} what="Loading documents">
            {(page) => page.items.length === 0 ? <Empty>No documents.</Empty> : (
              <div className="scroll">
                <table className="table compact clickable-rows">
                  <thead><tr><th>Document</th><th>Type</th><th>Report date</th><th>Status</th><th>Events</th></tr></thead>
                  <tbody>{page.items.map((d) => (
                    <tr key={d.id} className={d.id === selected ? "selected" : ""} onClick={() => navigate("reports", { doc: d.id })}>
                      <td><a href={href("reports", { doc: d.id })}>{d.filename}</a>{d.latest_run?.extractor === "time-agent" && <Badge tone="ai">agent</Badge>}</td>
                      <td>{humanize(d.kind)}{d.discipline_group ? ` · ${d.discipline_group}` : ""}</td>
                      <td>{fmtDate(d.report_date)}</td>
                      <td><Badge tone={d.status === "extracted" ? "ok" : d.status === "failed" ? "bad" : "muted"}>{d.status}</Badge></td>
                      <td>{d.latest_run ? `${d.latest_run.events_valid}/${d.latest_run.events_total}` : "—"}</td>
                    </tr>
                  ))}</tbody>
                </table>
                <p className="muted small">{page.total} documents</p>
              </div>
            )}
          </Async>
        </Card>
        {selected ? <DocumentDetail id={selected} /> : <Card title="Extracted events"><Empty>Select a document to see what was extracted and how each event was linked.</Empty></Card>}
      </div>
    </>
  );
}

function DocumentDetail({ id }: { id: number }) {
  const { project, live } = useApp();
  const c = project.code;
  const [evidence, setEvidence] = useState<number | null>(null);
  const state = useApi(async () => {
    const [status, events, links] = await Promise.all([p2e.documentStatus(c, id), p2e.events(c, { document_id: id, limit: 1000 }), p2e.links(c, { document_id: id, limit: 1000 })]);
    return { status, events: events.items, links: new Map<number, LinkOut>(links.items.map((l) => [l.event_id, l])) };
  }, [c, id, live]);
  return (
    <Card title={`Document ${id}`}>
      <Async state={state} what="Loading extraction">
        {({ status, events, links }) => (
          <>
            <p className="muted">Status <Badge tone={status.status === "extracted" ? "ok" : "muted"}>{status.status}</Badge> · runs {status.runs}
              {status.latest_run && <> · extractor {status.latest_run.extractor} {status.latest_run.parser_version} · {status.latest_run.events_valid} valid / {status.latest_run.events_invalid} invalid · {status.latest_run.issues_count} issues</>}</p>
            {status.issues.length > 0 && <ul className="issues">{status.issues.map((i, k) => <li key={k}><Badge tone="warn">issue</Badge> {i.message}: <code>{i.source_text}</code></li>)}</ul>}
            {events.length === 0 ? <Empty>No events extracted from this document.</Empty> : (
              <div className="scroll">
                <table className="table compact">
                  <thead><tr><th>Field text</th><th>Type</th><th>Date</th><th>Qty</th><th>Tags</th><th>Validation</th><th>Link</th><th></th></tr></thead>
                  <tbody>{events.map((e) => {
                    const l = links.get(e.id);
                    return (
                      <tr key={e.id}>
                        <td className="source-cell">{e.source_text}</td>
                        <td>{e.event_type ?? "—"}</td>
                        <td>{fmtDate(e.event_date)}{e.event_time ? ` ${e.event_time}` : ""}</td>
                        <td>{e.quantity != null ? `${e.quantity} ${e.unit}` : "—"}</td>
                        <td className="mono small">{e.tags.join(", ") || "—"}</td>
                        <td><Badge tone={e.validation_status === "valid" ? "ok" : "bad"} title={e.validation_errors.join("; ")}>{e.validation_status}</Badge></td>
                        <td>{l ? <a href={href("linking", { event: e.id })}><Badge tone={decisionTone(l.decision, l.state)}>{l.decision}{l.plan_node_code ? ` · ${l.plan_node_code}` : ""}</Badge></a> : <Badge>not linked yet</Badge>}</td>
                        <td><button type="button" className="btn btn-sm" onClick={() => setEvidence(e.id)}>Evidence</button></td>
                      </tr>
                    );
                  })}</tbody>
                </table>
              </div>
            )}
          </>
        )}
      </Async>
      {evidence !== null && <EvidenceModal eventId={evidence} onClose={() => setEvidence(null)} />}
    </Card>
  );
}
