import { useState } from "react";
import { useT } from "../i18n";
import { p2e, type ApplyOut, type LinkDetail } from "../api/p2e";
import { EvidenceModal } from "../components/Evidence";
import { Async, Badge, Card, Empty, ErrorBox, Field, Flow, PageTitle } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useApp } from "../state";
import { decisionTone, fmtDate, fmtNum, humanize } from "../utils/format";
import { href, navigate, useRoute } from "../utils/route";

export function LinkingPage() {
  const { t } = useT();
  const { params } = useRoute();
  const tab = params.get("tab") ?? "events";
  return (
    <>
      <PageTitle icon="agent-linker" title={t("linking.title")} subtitle={t("linking.sub")} />
      <div className="tabs" role="tablist">
        <a role="tab" aria-selected={tab === "events"} className={tab === "events" ? "active" : ""} href={href("linking")}>Link decisions</a>
        <a role="tab" aria-selected={tab === "blocked"} className={tab === "blocked" ? "active" : ""} href={href("linking", { tab: "blocked" })}>Blocked actuals</a>
      </div>
      {tab === "blocked" ? <BlockedActuals /> : <LinkDecisions />}
    </>
  );
}

function LinkDecisions() {
  const { project, live } = useApp();
  const c = project.code;
  const { params } = useRoute();
  const decision = params.get("decision") ?? (params.get("conflict") ? "" : "review");
  const conflict = params.get("conflict") ?? "";
  const state = params.get("state") ?? "";
  const node = params.get("node") ?? "";
  const eventId = params.get("event") ? Number(params.get("event")) : null;
  const list = useApi(() => p2e.links(c, { decision: decision || undefined, state: state || undefined, conflict: conflict || undefined, plan_node_code: node || undefined, limit: 500 }), [c, decision, state, conflict, node, live]);
  const setFilter = (k: string, v: string) => navigate("linking", { decision, state, conflict, node, [k]: v, event: undefined });
  return (
    <div className="split">
      <Card title={node ? `Decisions linked to ${node}` : "Decisions"} actions={<>
        <select aria-label="Decision" value={decision} onChange={(e) => setFilter("decision", e.target.value)}>
          <option value="">All decisions</option><option value="review">Review</option><option value="matched">Matched</option><option value="unmatched">Unmatched</option>
        </select>
        <select aria-label="State" value={state} onChange={(e) => setFilter("state", e.target.value)}>
          <option value="">Any state</option><option value="pending">Pending</option><option value="auto">Auto</option><option value="confirmed">Confirmed</option><option value="rejected">Rejected</option>
        </select>
        <label className="check"><input type="checkbox" checked={conflict === "true"} onChange={(e) => setFilter("conflict", e.target.checked ? "true" : "")} />conflicts</label>
      </>}>
        <Async state={list} what="Loading decisions">
          {(page) => page.items.length === 0 ? <Empty>Nothing here. {decision === "review" && "The review queue is empty."}</Empty> : (
            <ul className="queue">
              {page.items.map((l) => (
                <li key={l.event_id} className={l.event_id === eventId ? "selected" : ""}>
                  <a href={href("linking", { decision, state, conflict, node, event: l.event_id })}>
                    <span className="queue-text">{l.activity_text}</span>
                    <span className="queue-meta">
                      <Badge tone={decisionTone(l.decision, l.state)}>{l.decision} · {l.state}</Badge>
                      {l.plan_node_code && <span className="mono">{l.plan_node_code}</span>}
                      {l.conflict && <Badge tone="bad">date conflict</Badge>}
                      <span className="muted">{fmtDate(l.event_date)} · {fmtNum(l.confidence)}</span>
                    </span>
                  </a>
                </li>
              ))}
              <li className="muted small">{page.total} decisions</li>
            </ul>
          )}
        </Async>
      </Card>
      {eventId ? <LinkWorkspace eventId={eventId} onChanged={list.reload} /> : <Card title="Decision detail"><Empty>Select a decision to see the evidence, the candidates and the planner actions.</Empty></Card>}
    </div>
  );
}

function LinkWorkspace({ eventId, onChanged }: { eventId: number; onChanged: () => void }) {
  const { project, asOf, live } = useApp();
  const c = project.code;
  const state = useApi(async () => ({ link: await p2e.link(c, eventId), event: await p2e.event(c, eventId) }), [c, eventId, live]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [other, setOther] = useState("");
  const [evidence, setEvidence] = useState<number | null>(null);
  const [showNew, setShowNew] = useState(false);

  const run = async (fn: () => Promise<string>) => {
    setBusy(true);
    setResult(null);
    try {
      setResult({ ok: true, text: await fn() });
      state.reload();
      onChanged();
    } catch (e) {
      setResult({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };
  const applied = (a: ApplyOut) => a.applied.length
    ? `Applied to the schedule: ${a.applied.map((e) => `${e.plan_node_code} ${Object.keys(e.changes).join(", ")}`).join("; ")}.`
    : a.blocked.length ? `Not applied: ${a.blocked.map((b) => `${b.plan_node_code}: ${b.blockers.join("; ")}`).join(" | ")}` : "No schedule change needed.";
  const approve = (code?: string) => run(async () => {
    const r = await p2e.approve(c, eventId, asOf, code);
    return `Confirmed ${r.link.plan_node_code}. ${r.learned.length ? `Alias memory learned ${r.learned.length} phrase(s). ` : ""}${applied(r.apply)}`;
  });

  return (
    <Card title={`Event ${eventId}`}>
      <Async state={state} what="Loading the decision">
        {({ link, event }) => {
          const top = link.candidates[0];
          return (
            <>
              <Flow steps={[
                { label: "Field report", value: <span className="source-inline">{link.source_text}</span>, tone: "info" },
                { label: "AI extraction", value: `${humanize(link.event_type)} · ${fmtDate(link.event_date)}${event.quantity != null ? ` · ${event.quantity} ${event.unit}` : ""}`, tone: "ai" },
                { label: "Candidate activity", value: top ? `${top.plan_node_code}` : "none", tone: top ? "ai" : "bad" },
                { label: "Confidence", value: `${fmtNum(link.confidence)} (margin ${fmtNum(link.margin)})`, tone: link.confidence >= 0.7 ? "ok" : "warn" },
                { label: "Planner decision", value: `${link.decision} · ${link.state}`, tone: decisionTone(link.decision, link.state) },
              ]} />
              <div className="fields">
                <Field label="Extracted activity">{link.activity_text}</Field>
                <Field label="Discipline">{humanize(event.discipline)}</Field>
                <Field label="Area">{event.area ?? "—"}</Field>
                <Field label="Tags"><span className="mono">{event.tags.join(", ") || "—"}</span></Field>
                <Field label="Source">{event.document_filename} <button type="button" className="btn btn-sm" onClick={() => setEvidence(eventId)}>Evidence</button></Field>
                <Field label="Linked activity">{link.plan_node_code ? <a href={href("schedule", { q: link.plan_node_code })}>{link.plan_node_code}</a> : "—"}</Field>
                <Field label="Retrieval">{link.method}{link.retrieval_used ? " + stage-2 retrieval (RAG)" : " (deterministic)"}</Field>
                <Field label="Decided by">{link.decided_by ? `${link.decided_by} · ${fmtDate(link.decided_at)}` : "linker"}</Field>
              </div>
              <div className="reasons">{link.reasons.map((r, i) => <Badge key={i} tone={link.decision === "matched" ? "ai" : "warn"}>{r}</Badge>)}</div>
              {link.unmatched_type && <p><Badge tone="bad">unmatched: {humanize(link.unmatched_type)}</Badge></p>}
              {link.conflict && <ConflictBox link={link} onEvidence={setEvidence} />}
              {link.llm_suggestion && <p className="muted small">LLM tie-breaker (advisory): {JSON.stringify(link.llm_suggestion)}</p>}

              <h3>Candidate L5/L6 activities</h3>
              {link.candidates.length === 0 ? <Empty>No candidate was retrieved.</Empty> : (
                <ol className="candidates">
                  {link.candidates.slice(0, 8).map((cd) => (
                    <li key={cd.rank}>
                      <div className="cand-head">
                        <span className="score"><span className="score-bar" style={{ width: `${Math.round(cd.score * 100)}%` }} /></span>
                        <strong>{fmtNum(cd.score)}</strong>
                        <a className="mono" href={href("schedule", { q: cd.plan_node_code })}>{cd.plan_node_code}</a>
                        <span>{cd.activity_name}</span>
                        <span className="muted">{humanize(cd.discipline)} · {cd.area ?? "—"}</span>
                        <button type="button" className="btn btn-sm" disabled={busy} onClick={() => approve(cd.plan_node_code)}>{cd.rank === 1 ? "Approve" : "Choose"}</button>
                      </div>
                      <div className="cand-why">
                        {cd.retrieval_methods.map((m) => <Badge key={m} tone="info">{m}</Badge>)}
                        {cd.reasons.map((r, i) => <span key={i} className="reason">{r}</span>)}
                      </div>
                    </li>
                  ))}
                </ol>
              )}

              <h3>Planner actions</h3>
              <div className="actions">
                <button type="button" className="btn btn-primary" disabled={busy || !top} onClick={() => approve()}>Confirm top candidate</button>
                <form className="inline" onSubmit={(e) => { e.preventDefault(); if (other.trim()) approve(other.trim()); }}>
                  <input placeholder="Other activity code" value={other} onChange={(e) => setOther(e.target.value)} aria-label="Other activity code" />
                  <button className="btn" disabled={busy || !other.trim()}>Choose</button>
                </form>
                <button type="button" className="btn" disabled={busy || link.state !== "auto"} title="Hold an automatic decision for planner review" onClick={() => run(async () => { await p2e.hold(c, eventId); return "Sent to planner review; the linker will not override it."; })}>Send to review</button>
                <button type="button" className="btn btn-danger" disabled={busy || link.state === "rejected"} onClick={() => run(async () => { await p2e.reject(c, eventId); return "Rejected: the report matches no schedule activity."; })}>Reject</button>
                <button type="button" className="btn" disabled={busy} onClick={() => setShowNew(!showNew)}>New activity…</button>
              </div>
              {showNew && <NewActivityForm eventId={eventId} defaultName={link.activity_text} busy={busy} run={run} />}
              {result && (result.ok ? <div className="state state-ok">{result.text}</div> : <ErrorBox error={result.text} />)}
              {link.state === "auto" && link.decision === "matched" && <p className="muted small">If actuals were already applied from this report, revert them in the <a href="#/audit">audit trail</a>.</p>}
            </>
          );
        }}
      </Async>
      {evidence !== null && <EvidenceModal eventId={evidence} onClose={() => setEvidence(null)} />}
    </Card>
  );
}

function ConflictBox({ link, onEvidence }: { link: LinkDetail; onEvidence: (id: number) => void }) {
  const cf = link.conflict!;
  return (
    <div className="conflict">
      <strong>Cross-source date conflict on {cf.plan_node_code}</strong> — dates {cf.dates.join(" vs ")}. The system does not choose between them; both reports are kept.
      <ul>{cf.findings.map((f, i) => <li key={i}><Badge tone="bad">{humanize(f.rule)}</Badge> {f.detail}</li>)}</ul>
      <table className="table compact">
        <thead><tr><th>Report</th><th>Source</th><th>Type</th><th>Date</th><th>Qty</th><th></th></tr></thead>
        <tbody>{cf.events.map((e) => (
          <tr key={e.event_id}><td className="source-cell">{e.source_text}</td><td>{e.document}</td><td>{e.event_type}</td><td>{e.event_date}</td>
            <td>{e.quantity != null ? `${e.quantity} ${e.unit}` : "—"}</td>
            <td><button type="button" className="btn btn-sm" onClick={() => onEvidence(e.event_id)}>Evidence</button> <a href={href("linking", { event: e.event_id, conflict: "true" })}>open</a></td></tr>
        ))}</tbody>
      </table>
      <p className="muted small">Resolve by rejecting the wrong report, or confirm the activity and set the date by override under “Blocked actuals”.</p>
    </div>
  );
}

function NewActivityForm({ eventId, defaultName, busy, run }: { eventId: number; defaultName: string; busy: boolean; run: (fn: () => Promise<string>) => void }) {
  const { project, asOf } = useApp();
  const [form, setForm] = useState({ parent_code: "", code: "", name: defaultName });
  return (
    <form className="subform" onSubmit={(e) => { e.preventDefault(); run(async () => {
      const r = await p2e.newActivity(project.code, eventId, { ...form, as_of: asOf });
      return `Created ${r.link.plan_node_code} and linked the report. ${r.apply.applied.length ? "Actuals applied." : ""}`;
    }); }}>
      <p className="muted small">Mark as NEW work: creates an L5 activity under an L4 WBS node (or L6 under a summary). Audited.</p>
      <label className="stacked">Parent WBS code<input required value={form.parent_code} onChange={(e) => setForm({ ...form, parent_code: e.target.value })} placeholder="e.g. CGS-EXP-01.A3.CIV.PR3" /></label>
      <label className="stacked">New activity code<input required value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="e.g. CIV-A3-NW01" /></label>
      <label className="stacked">Name<input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
      <button className="btn btn-primary" disabled={busy}>Create activity</button>
    </form>
  );
}

function BlockedActuals() {
  const { project, asOf, live } = useApp();
  const state = useApi(() => p2e.review(project.code, asOf), [project.code, asOf, live]);
  return (
    <Card title={`Activities whose reported actuals are blocked by a rule (as of ${asOf})`}>
      <Async state={state} what="Loading the review queue">
        {(q) => q.activities.length === 0 ? <Empty>No blocked activities.</Empty> : (
          <div className="scroll">
            <table className="table compact">
              <thead><tr><th>Activity</th><th>Why blocked</th><th>Proposed</th><th>Evidence</th><th>Override</th></tr></thead>
              <tbody>{q.activities.map((a) => <BlockedRow key={a.plan_node_code} a={a} onDone={state.reload} />)}</tbody>
            </table>
          </div>
        )}
      </Async>
    </Card>
  );
}

function BlockedRow({ a, onDone }: { a: { plan_node_code: string; activity_name: string; blockers: string[]; proposed: Record<string, unknown>; evidence_event_ids: number[] }; onDone: () => void }) {
  const { project, asOf } = useApp();
  const [start, setStart] = useState("");
  const [finish, setFinish] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const submit = async () => {
    const body: Record<string, unknown> = { as_of: asOf, evidence_event_ids: a.evidence_event_ids };
    if (start) body.actual_start = start;
    if (finish) body.actual_finish = finish;
    try {
      const e = await p2e.override(project.code, a.plan_node_code, body);
      setMsg({ ok: true, text: `Audit entry ${e.id}` });
      onDone();
    } catch (err) {
      setMsg({ ok: false, text: (err as Error).message });
    }
  };
  return (
    <tr>
      <td><a className="mono" href={href("schedule", { q: a.plan_node_code })}>{a.plan_node_code}</a><div className="small muted">{a.activity_name}</div></td>
      <td>{a.blockers.map((b, i) => <div key={i} className="small">{b}</div>)}</td>
      <td className="small">start {fmtDate(a.proposed.actual_start)}<br />finish {fmtDate(a.proposed.actual_finish)}</td>
      <td className="small">{a.evidence_event_ids.map((id) => <a key={id} href={href("linking", { event: id, decision: "" })}>#{id} </a>)}</td>
      <td>
        <form className="inline" onSubmit={(e) => { e.preventDefault(); submit(); }}>
          <input type="date" aria-label="Actual start" value={start} onChange={(e) => setStart(e.target.value)} />
          <input type="date" aria-label="Actual finish" value={finish} onChange={(e) => setFinish(e.target.value)} />
          <button className="btn btn-sm" disabled={!start && !finish}>Set</button>
        </form>
        {msg && <div className={msg.ok ? "ok-text small" : "bad-text small"}>{msg.text}</div>}
      </td>
    </tr>
  );
}
