import { useState } from "react";
import { useT, T } from "../i18n";
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
        <a role="tab" aria-selected={tab === "events"} className={tab === "events" ? "active" : ""} href={href("linking")}>{T("lk.tabDecisions")}</a>
        <a role="tab" aria-selected={tab === "blocked"} className={tab === "blocked" ? "active" : ""} href={href("linking", { tab: "blocked" })}>{T("lk.tabBlocked")}</a>
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
      <Card title={node ? T("lk.decisionsFor", { node }) : T("lk.decisions")} actions={<>
        <select aria-label={T("lk.decision")} value={decision} onChange={(e) => setFilter("decision", e.target.value)}>
          <option value="">{T("lk.allDecisions")}</option><option value="review">{humanize("review")}</option><option value="matched">{humanize("matched")}</option><option value="unmatched">{humanize("unmatched")}</option>
        </select>
        <select aria-label={T("lk.state")} value={state} onChange={(e) => setFilter("state", e.target.value)}>
          <option value="">{T("lk.anyState")}</option>{["pending", "auto", "confirmed", "rejected"].map((v) => <option key={v} value={v}>{humanize(v)}</option>)}
        </select>
        <label className="check"><input type="checkbox" checked={conflict === "true"} onChange={(e) => setFilter("conflict", e.target.checked ? "true" : "")} />{T("lk.conflicts")}</label>
      </>}>
        <Async state={list} what={T("lk.loadingDecisions")}>
          {(page) => page.items.length === 0 ? <Empty>{T("lk.nothing")} {decision === "review" && T("lk.queueEmpty")}</Empty> : (
            <ul className="queue">
              {page.items.map((l) => (
                <li key={l.event_id} className={l.event_id === eventId ? "selected" : ""}>
                  <a href={href("linking", { decision, state, conflict, node, event: l.event_id })}>
                    <span className="queue-text">{l.activity_text}</span>
                    <span className="queue-meta">
                      <Badge tone={decisionTone(l.decision, l.state)}>{humanize(l.decision)} · {humanize(l.state)}</Badge>
                      {l.plan_node_code && <span className="mono">{l.plan_node_code}</span>}
                      {l.conflict && <Badge tone="bad">{T("lk.dateConflict")}</Badge>}
                      <span className="muted">{fmtDate(l.event_date)} · {fmtNum(l.confidence)}</span>
                    </span>
                  </a>
                </li>
              ))}
              <li className="muted small">{T("lk.total", { n: page.total })}</li>
            </ul>
          )}
        </Async>
      </Card>
      {eventId ? <LinkWorkspace eventId={eventId} onChanged={list.reload} /> : <Card title={T("lk.detail")}><Empty>{T("lk.select")}</Empty></Card>}
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
    ? T("lk.appliedTo", { items: a.applied.map((e) => `${e.plan_node_code} ${Object.keys(e.changes).join(", ")}`).join("; ") })
    : a.blocked.length ? T("lk.notApplied", { items: a.blocked.map((b) => `${b.plan_node_code}: ${b.blockers.join("; ")}`).join(" | ") }) : T("lk.noChange");
  const approve = (code?: string) => run(async () => {
    const r = await p2e.approve(c, eventId, asOf, code);
    return `${T("lk.confirmed", { code: String(r.link.plan_node_code) })} ${r.learned.length ? T("lk.learned", { n: r.learned.length }) + " " : ""}${applied(r.apply)}`;
  });

  return (
    <Card title={T("lk.event", { id: eventId })}>
      <Async state={state} what={T("lk.loadingDecision")}>
        {({ link, event }) => {
          const top = link.candidates[0];
          return (
            <>
              <Flow steps={[
                { label: T("flow.report"), value: <span className="source-inline">{link.source_text}</span>, tone: "info" },
                { label: T("flow.extract"), value: `${humanize(link.event_type)} · ${fmtDate(link.event_date)}${event.quantity != null ? ` · ${event.quantity} ${event.unit}` : ""}`, tone: "ai" },
                { label: T("flow.candidate"), value: top ? `${top.plan_node_code}` : T("lk.none"), tone: top ? "ai" : "bad" },
                { label: T("f.confidence"), value: `${fmtNum(link.confidence)} (${T("lk.margin")} ${fmtNum(link.margin)})`, tone: link.confidence >= 0.7 ? "ok" : "warn" },
                { label: T("flow.decision"), value: `${humanize(link.decision)} · ${humanize(link.state)}`, tone: decisionTone(link.decision, link.state) },
              ]} />
              <div className="fields">
                <Field label={T("lk.extracted")}>{link.activity_text}</Field>
                <Field label={T("f.discipline")}>{humanize(event.discipline)}</Field>
                <Field label={T("f.area")}>{event.area ?? "—"}</Field>
                <Field label={T("f.tags")}><span className="mono">{event.tags.join(", ") || "—"}</span></Field>
                <Field label={T("f.source")}>{event.document_filename} <button type="button" className="btn btn-sm" onClick={() => setEvidence(eventId)}>{T("lk.evidence")}</button></Field>
                <Field label={T("lk.linked")}>{link.plan_node_code ? <a href={href("schedule", { q: link.plan_node_code })}>{link.plan_node_code}</a> : "—"}</Field>
                <Field label={T("lk.retrieval")}>{link.method}{link.retrieval_used ? T("lk.rag") : T("lk.deterministic")}</Field>
                <Field label={T("lk.decidedBy")}>{link.decided_by ? `${link.decided_by} · ${fmtDate(link.decided_at)}` : T("lk.linker")}</Field>
              </div>
              <div className="reasons">{link.reasons.map((r, i) => <Badge key={i} tone={link.decision === "matched" ? "ai" : "warn"}>{r}</Badge>)}</div>
              {link.unmatched_type && <p><Badge tone="bad">{humanize("unmatched")}: {humanize(link.unmatched_type)}</Badge></p>}
              {link.conflict && <ConflictBox link={link} onEvidence={setEvidence} />}
              {link.llm_suggestion && <p className="muted small">{T("lk.tiebreak")}: {JSON.stringify(link.llm_suggestion)}</p>}

              <h3>{T("lk.candidates")}</h3>
              {link.candidates.length === 0 ? <Empty>{T("lk.noCandidate")}</Empty> : (
                <ol className="candidates">
                  {link.candidates.slice(0, 8).map((cd) => (
                    <li key={cd.rank}>
                      <div className="cand-head">
                        <span className="score"><span className="score-bar" style={{ width: `${Math.round(cd.score * 100)}%` }} /></span>
                        <strong>{fmtNum(cd.score)}</strong>
                        <a className="mono" href={href("schedule", { q: cd.plan_node_code })}>{cd.plan_node_code}</a>
                        <span>{cd.activity_name}</span>
                        <span className="muted">{humanize(cd.discipline)} · {cd.area ?? "—"}</span>
                        <button type="button" className="btn btn-sm" disabled={busy} onClick={() => approve(cd.plan_node_code)}>{cd.rank === 1 ? T("lk.approve") : T("lk.choose")}</button>
                      </div>
                      <div className="cand-why">
                        {cd.retrieval_methods.map((m) => <Badge key={m} tone="info">{m}</Badge>)}
                        {cd.reasons.map((r, i) => <span key={i} className="reason">{r}</span>)}
                      </div>
                    </li>
                  ))}
                </ol>
              )}

              <h3>{T("lk.actions")}</h3>
              <div className="actions">
                <button type="button" className="btn btn-primary" disabled={busy || !top} onClick={() => approve()}>{T("lk.confirmTop")}</button>
                <form className="inline" onSubmit={(e) => { e.preventDefault(); if (other.trim()) approve(other.trim()); }}>
                  <input placeholder={T("lk.otherCode")} value={other} onChange={(e) => setOther(e.target.value)} aria-label={T("lk.otherCode")} />
                  <button className="btn" disabled={busy || !other.trim()}>{T("lk.choose")}</button>
                </form>
                <button type="button" className="btn" disabled={busy || link.state !== "auto"} title={T("lk.holdHint")} onClick={() => run(async () => { await p2e.hold(c, eventId); return T("lk.held"); })}>{T("lk.sendReview")}</button>
                <button type="button" className="btn btn-danger" disabled={busy || link.state === "rejected"} onClick={() => run(async () => { await p2e.reject(c, eventId); return T("lk.rejectedMsg"); })}>{T("lk.reject")}</button>
                <button type="button" className="btn" disabled={busy} onClick={() => setShowNew(!showNew)}>{T("lk.newActivity")}</button>
              </div>
              {showNew && <NewActivityForm eventId={eventId} defaultName={link.activity_text} busy={busy} run={run} />}
              {result && (result.ok ? <div className="state state-ok">{result.text}</div> : <ErrorBox error={result.text} />)}
              {link.state === "auto" && link.decision === "matched" && <p className="muted small">{T("lk.revert")} <a href="#/audit">{T("nav.audit")}</a>.</p>}
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
      <strong>{T("lk.conflictOn", { code: cf.plan_node_code })}</strong> — {cf.dates.join(" vs ")}. {T("lk.conflictKeep")}
      <ul>{cf.findings.map((f, i) => <li key={i}><Badge tone="bad">{humanize(f.rule)}</Badge> {f.detail}</li>)}</ul>
      <table className="table compact">
        <thead><tr><th>{T("f.report")}</th><th>{T("f.source")}</th><th>{T("f.type")}</th><th>{T("f.date")}</th><th>{T("f.qty")}</th><th></th></tr></thead>
        <tbody>{cf.events.map((e) => (
          <tr key={e.event_id}><td className="source-cell">{e.source_text}</td><td>{e.document}</td><td>{humanize(e.event_type)}</td><td>{e.event_date}</td>
            <td>{e.quantity != null ? `${e.quantity} ${e.unit}` : "—"}</td>
            <td><button type="button" className="btn btn-sm" onClick={() => onEvidence(e.event_id)}>{T("lk.evidence")}</button> <a href={href("linking", { event: e.event_id, conflict: "true" })}>{T("lk.open")}</a></td></tr>
        ))}</tbody>
      </table>
      <p className="muted small">{T("lk.resolve")}</p>
    </div>
  );
}

function NewActivityForm({ eventId, defaultName, busy, run }: { eventId: number; defaultName: string; busy: boolean; run: (fn: () => Promise<string>) => void }) {
  const { project, asOf } = useApp();
  const [form, setForm] = useState({ parent_code: "", code: "", name: defaultName });
  return (
    <form className="subform" onSubmit={(e) => { e.preventDefault(); run(async () => {
      const r = await p2e.newActivity(project.code, eventId, { ...form, as_of: asOf });
      return `${T("lk.created", { code: String(r.link.plan_node_code) })} ${r.apply.applied.length ? T("lk.actualsApplied") : ""}`;
    }); }}>
      <p className="muted small">{T("lk.newHint")}</p>
      <label className="stacked">{T("lk.parent")}<input required value={form.parent_code} onChange={(e) => setForm({ ...form, parent_code: e.target.value })} placeholder="e.g. CGS-EXP-01.A3.CIV.PR3" /></label>
      <label className="stacked">{T("lk.newCode")}<input required value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="e.g. CIV-A3-NW01" /></label>
      <label className="stacked">{T("auth.name")}<input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
      <button className="btn btn-primary" disabled={busy}>{humanize("create_activity")}</button>
    </form>
  );
}

function BlockedActuals() {
  const { project, asOf, live } = useApp();
  const state = useApi(() => p2e.review(project.code, asOf), [project.code, asOf, live]);
  return (
    <Card title={T("lk.blockedTitle", { asOf })}>
      <Async state={state} what={T("lk.loadingQueue")}>
        {(q) => q.activities.length === 0 ? <Empty>{T("lk.noBlocked")}</Empty> : (
          <div className="scroll">
            <table className="table compact">
              <thead><tr><th>{T("f.activity")}</th><th>{T("lk.why")}</th><th>{T("lk.proposed")}</th><th>{T("lk.evidence")}</th><th>{humanize("override")}</th></tr></thead>
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
      setMsg({ ok: true, text: T("lk.auditEntry", { id: e.id }) });
      onDone();
    } catch (err) {
      setMsg({ ok: false, text: (err as Error).message });
    }
  };
  return (
    <tr>
      <td><a className="mono" href={href("schedule", { q: a.plan_node_code })}>{a.plan_node_code}</a><div className="small muted">{a.activity_name}</div></td>
      <td>{a.blockers.map((b, i) => <div key={i} className="small">{b}</div>)}</td>
      <td className="small">{humanize("start")} {fmtDate(a.proposed.actual_start)}<br />{humanize("finish")} {fmtDate(a.proposed.actual_finish)}</td>
      <td className="small">{a.evidence_event_ids.map((id) => <a key={id} href={href("linking", { event: id, decision: "" })}>#{id} </a>)}</td>
      <td>
        <form className="inline" onSubmit={(e) => { e.preventDefault(); submit(); }}>
          <input type="date" aria-label={T("f.actualStart")} value={start} onChange={(e) => setStart(e.target.value)} />
          <input type="date" aria-label={T("f.actualFinish")} value={finish} onChange={(e) => setFinish(e.target.value)} />
          <button className="btn btn-sm" disabled={!start && !finish}>{T("lk.set")}</button>
        </form>
        {msg && <div className={msg.ok ? "ok-text small" : "bad-text small"}>{msg.text}</div>}
      </td>
    </tr>
  );
}
