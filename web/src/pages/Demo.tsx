import { useState, type ReactNode } from "react";
import { p2e, type AgentReply, type Answer, type ApplyOut, type AuditEntry, type DatasetRow } from "../api/p2e";
import { Badge, Card, ErrorBox, Field, Flow, PageTitle } from "../components/ui";
import { useApp } from "../state";
import { useT, T } from "../i18n";
import { decisionTone, fmtDate, fmtNum, humanize, statusTone } from "../utils/format";
import { href } from "../utils/route";
import { ReplyCard } from "./Agent";
import { AnswerCard } from "./Memory";

/** Guided SIH demonstration: every step calls the real backend; nothing is simulated. */
export function DemoPage() {
  const { project, asOf } = useApp();
  const { t, lang } = useT();
  const c = project.code;
  const [message, setMessage] = useState("PT-1102 loop check started today at 9 am");
  const [discipline, setDiscipline] = useState("instrumentation");
  const [reply, setReply] = useState<AgentReply | null>(null);
  const [approved, setApproved] = useState<ApplyOut | null>(null);
  const [row, setRow] = useState<DatasetRow | null>(null);
  const [audit, setAudit] = useState<AuditEntry[] | null>(null);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const code = reply?.link?.plan_node_code ?? reply?.link?.candidates[0]?.plan_node_code ?? null;

  const step = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const reset = () => { setReply(null); setApproved(null); setRow(null); setAudit(null); setAnswer(null); setError(null); };

  return (
    <>
      <PageTitle title={t("demo.title")} subtitle={t("demo.sub", { asOf })}
        actions={<button type="button" className="btn" onClick={reset}>{T("de.restart")}</button>} />
      <Flow steps={[
        { label: `1 ${T("flow.report")}`, value: reply ? T("de.sent") : "—", tone: reply ? "ok" : "muted" },
        { label: `2–4 ${T("de.f2")}`, value: reply?.link ? `${humanize(reply.link.decision)} ${fmtNum(reply.link.confidence)}` : "—", tone: reply?.link ? decisionTone(reply.link.decision, reply.link.state) : "muted" },
        { label: `5–6 ${T("de.f3")}`, value: approved ? `${approved.applied.length} ${T("sc.applied")}` : "—", tone: approved ? "ok" : "muted" },
        { label: `7 ${T("nav.schedule")}`, value: row ? humanize(row.status) : "—", tone: row ? statusTone(row.status) : "muted" },
        { label: `8 ${T("nav.audit")}`, value: audit ? T("de.entries", { n: audit.length }) : "—", tone: audit ? "ok" : "muted" },
        { label: `9–10 ${T("de.f6")}`, value: answer ? T("de.cited", { n: answer.citations.length }) : "—", tone: answer ? "ai" : "muted" },
      ]} />
      {error && <ErrorBox error={error} />}

      <Step n="1" title={T("de.s1")}>
        <form className="inline" onSubmit={(e) => { e.preventDefault(); reset(); step(async () => setReply(await p2e.agent(c, { message, discipline, reference_datetime: `${asOf}T18:00:00`, lang }))); }}>
          <input value={message} onChange={(e) => setMessage(e.target.value)} aria-label={T("flow.report")} className="grow" />
          <select value={discipline} onChange={(e) => setDiscipline(e.target.value)} aria-label={T("f.discipline")}>
            {["civil", "piping", "electrical", "instrumentation", "hse", "static_eq", "rotating_eq"].map((d) => <option key={d} value={d}>{humanize(d)}</option>)}
          </select>
          <button className="btn btn-primary" disabled={busy}>{T("de.send")}</button>
        </form>
        <p className="muted small">{T("de.orUpload")} <a href="#/reports">{T("nav.reports")}</a>.</p>
      </Step>

      {reply && (
        <Step n="2–4" title={T("de.s2")}>
          <ReplyCard reply={reply} onAnswer={() => undefined} busy={busy} />
          {reply.status === "needs_clarification" && <p className="muted">{T("de.asked")} <a href={href("agent", { message })}>{T("nav.agent")}</a>.</p>}
        </Step>
      )}

      {reply?.link && code && (
        <Step n="5–6" title={T("de.s3")}>
          <p>{T(reply.link.decision === "matched" ? "de.linkerMatched" : "de.linkerProposed")} <span className="mono">{code}</span>. {T("de.plannerConfirms")}</p>
          <button type="button" className="btn btn-primary" disabled={busy || !!approved} onClick={() => step(async () => {
            const r = await p2e.approve(c, reply.link!.event_id, asOf, code);
            setApproved(r.apply);
          })}>{T("de.confirm", { code })}</button>
          {approved && (
            <p>{approved.applied.length
              ? <>{T("sc.applied")}: {approved.applied.map((e) => Object.entries(e.changes).map(([k, [a, b]]) => `${humanize(k)} ${a ?? "—"} → ${b}`).join(", ")).join("; ")}</>
              : approved.blocked.length ? <>{T("de.held")}: {approved.blocked.flatMap((b) => b.blockers).join("; ")}</> : T("de.noChange")}</p>
          )}
        </Step>
      )}

      {approved && code && (
        <Step n="7" title={T("de.s4")}>
          <button type="button" className="btn" disabled={busy} onClick={() => step(async () => setRow((await p2e.dataset(c, asOf)).items.find((r) => r.code === code) ?? null))}>{T("de.showActivity")}</button>
          {row && (
            <div className="fields">
              <Field label={T("f.activity")}><a className="mono" href={href("schedule", { q: row.code })}>{row.code}</a> {row.name}</Field>
              <Field label={T("sc.planned")}>{fmtDate(row.planned_start)} → {fmtDate(row.planned_finish)}</Field>
              <Field label={T("sc.actual")}>{fmtDate(row.actual_start)} → {fmtDate(row.actual_finish)}</Field>
              <Field label={T("f.status")}><Badge tone={statusTone(row.status)}>{humanize(row.status)}</Badge></Field>
              <Field label={T("sc.reports")}>{T("de.fromSources", { n: row.reports, s: row.sources })}</Field>
            </div>
          )}
        </Step>
      )}

      {row && code && (
        <Step n="8" title={T("nav.audit")}>
          <button type="button" className="btn" disabled={busy} onClick={() => step(async () => setAudit((await p2e.audit(c, { plan_node_code: code })).items))}>{T("de.showAudit")}</button>
          {audit && (audit.length === 0 ? <p className="muted">{T("de.noAudit")}</p> : (
            <ul>{audit.map((e) => <li key={e.id}><Badge tone="ai">{humanize(e.action)}</Badge> #{e.id} · {e.actor} ({humanize(e.rule)}) · {Object.entries(e.changes).map(([k, [a, b]]) => `${humanize(k)} ${a ?? "—"} → ${b}`).join(", ")} · {T("au.sources")} {e.evidence_event_ids.map((id) => `#${id}`).join(" ")}</li>)}</ul>
          ))}
          <p className="muted small">{T("de.fullHistory")} <a href={href("audit", { node: code })}>{T("nav.audit")}</a>.</p>
        </Step>
      )}

      {audit && reply && (
        <Step n="9–10" title={T("de.s6")}>
          <button type="button" className="btn" disabled={busy} onClick={() => step(async () => setAnswer(await p2e.ask(c, `What is the status of ${String(reply.interpretation.activity_text ?? code)}?`, asOf)))}>
            {T("as.ask")}: “What is the status of {String(reply.interpretation.activity_text ?? code)}?”
          </button>
          {answer && <AnswerCard q={answer.question} a={answer} />}
        </Step>
      )}

      {answer && (
        <Step n="11" title={T("de.s7")}>
          <p>{T("de.zero")}</p>
          <a className="btn btn-primary" href={href("roi")}>{T("nav.roi")}</a>{" "}
          <button type="button" className="btn" disabled={busy} onClick={() => step(() => p2e.pmReport(c, asOf, "weekly"))}>{T("analytics.weekly")}</button>
        </Step>
      )}
    </>
  );
}

function Step({ n, title, children }: { n: string; title: string; children: ReactNode }) {
  return <Card title={<><span className="step-n">{n}</span> {title}</>}>{children}</Card>;
}
