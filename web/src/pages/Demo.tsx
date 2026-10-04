import { useState, type ReactNode } from "react";
import { p2e, type AgentReply, type Answer, type ApplyOut, type AuditEntry, type DatasetRow } from "../api/p2e";
import { Badge, Card, ErrorBox, Field, Flow, PageTitle } from "../components/ui";
import { useApp } from "../state";
import { useT } from "../i18n";
import { decisionTone, fmtDate, fmtNum, humanize, statusTone } from "../utils/format";
import { href } from "../utils/route";
import { ReplyCard } from "./Agent";
import { AnswerCard } from "./Memory";

/** Guided SIH demonstration: every step calls the real backend; nothing is simulated. */
export function DemoPage() {
  const { project, asOf } = useApp();
  const { t } = useT();
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
        actions={<button type="button" className="btn" onClick={reset}>Restart</button>} />
      <Flow steps={[
        { label: "1 Field report", value: reply ? "sent" : "—", tone: reply ? "ok" : "muted" },
        { label: "2–4 AI extraction · matching · confidence", value: reply?.link ? `${reply.link.decision} ${fmtNum(reply.link.confidence)}` : "—", tone: reply?.link ? decisionTone(reply.link.decision, reply.link.state) : "muted" },
        { label: "5–6 Planner validates · actual applied", value: approved ? `${approved.applied.length} applied` : "—", tone: approved ? "ok" : "muted" },
        { label: "7 Schedule", value: row ? humanize(row.status) : "—", tone: row ? statusTone(row.status) : "muted" },
        { label: "8 Audit trail", value: audit ? `${audit.length} entries` : "—", tone: audit ? "ok" : "muted" },
        { label: "9–10 Question · citations", value: answer ? `${answer.citations.length} cited` : "—", tone: answer ? "ai" : "muted" },
      ]} />
      {error && <ErrorBox error={error} />}

      <Step n="1" title="A supervisor reports progress (Time Agent)">
        <form className="inline" onSubmit={(e) => { e.preventDefault(); reset(); step(async () => setReply(await p2e.agent(c, { message, discipline, reference_datetime: `${asOf}T18:00:00` }))); }}>
          <input value={message} onChange={(e) => setMessage(e.target.value)} aria-label="Field report" className="grow" />
          <select value={discipline} onChange={(e) => setDiscipline(e.target.value)} aria-label="Discipline">
            {["civil", "piping", "electrical", "instrumentation", "hse", "static_eq", "rotating_eq"].map((d) => <option key={d}>{d}</option>)}
          </select>
          <button className="btn btn-primary" disabled={busy}>Send report</button>
        </form>
        <p className="muted small">Or upload a DPR / tracker on <a href="#/reports">Field Reports</a>. The same pipeline runs.</p>
      </Step>

      {reply && (
        <Step n="2–4" title="Extraction, schedule matching and confidence">
          <ReplyCard reply={reply} onAnswer={() => undefined} busy={busy} />
          {reply.status === "needs_clarification" && <p className="muted">The agent asked a question; answer it on the <a href={href("agent", { message })}>Time Agent</a> page or adjust the message.</p>}
        </Step>
      )}

      {reply?.link && code && (
        <Step n="5–6" title="Planner validation → verified actual applied">
          <p>The linker {reply.link.decision === "matched" ? "matched" : "proposed"} <span className="mono">{code}</span>. The planner confirms it; the apply engine then checks every rule and writes an audited actual.</p>
          <button type="button" className="btn btn-primary" disabled={busy || !!approved} onClick={() => step(async () => {
            const r = await p2e.approve(c, reply.link!.event_id, asOf, code);
            setApproved(r.apply);
          })}>Confirm {code} and apply</button>
          {approved && (
            <p>{approved.applied.length
              ? <>Applied: {approved.applied.map((e) => Object.entries(e.changes).map(([k, [a, b]]) => `${humanize(k)} ${a ?? "—"} → ${b}`).join(", ")).join("; ")}</>
              : approved.blocked.length ? <>Held for review: {approved.blocked.flatMap((b) => b.blockers).join("; ")}</> : "No change needed (already recorded)."}</p>
          )}
        </Step>
      )}

      {approved && code && (
        <Step n="7" title="Schedule updated">
          <button type="button" className="btn" disabled={busy} onClick={() => step(async () => setRow((await p2e.dataset(c, asOf)).items.find((r) => r.code === code) ?? null))}>Show the activity in the schedule</button>
          {row && (
            <div className="fields">
              <Field label="Activity"><a className="mono" href={href("schedule", { q: row.code })}>{row.code}</a> {row.name}</Field>
              <Field label="Planned">{fmtDate(row.planned_start)} → {fmtDate(row.planned_finish)}</Field>
              <Field label="Actual">{fmtDate(row.actual_start)} → {fmtDate(row.actual_finish)}</Field>
              <Field label="Status"><Badge tone={statusTone(row.status)}>{humanize(row.status)}</Badge></Field>
              <Field label="Reports">{row.reports} from {row.sources} source(s)</Field>
            </div>
          )}
        </Step>
      )}

      {row && code && (
        <Step n="8" title="Audit trail">
          <button type="button" className="btn" disabled={busy} onClick={() => step(async () => setAudit((await p2e.audit(c, { plan_node_code: code })).items))}>Show audit entries</button>
          {audit && (audit.length === 0 ? <p className="muted">No change was recorded for this activity.</p> : (
            <ul>{audit.map((e) => <li key={e.id}><Badge tone="ai">{e.action}</Badge> #{e.id} by {e.actor} ({humanize(e.rule)}) · {Object.entries(e.changes).map(([k, [a, b]]) => `${humanize(k)} ${a ?? "—"} → ${b}`).join(", ")} · source reports {e.evidence_event_ids.map((id) => `#${id}`).join(" ")}</li>)}</ul>
          ))}
          <p className="muted small">Full history and undo: <a href={href("audit", { node: code })}>Audit Trail</a>.</p>
        </Step>
      )}

      {audit && reply && (
        <Step n="9–10" title="Ask the project memory">
          <button type="button" className="btn" disabled={busy} onClick={() => step(async () => setAnswer(await p2e.ask(c, `What is the status of ${String(reply.interpretation.activity_text ?? code)}?`, asOf)))}>
            Ask: “What is the status of {String(reply.interpretation.activity_text ?? code)}?”
          </button>
          {answer && <AnswerCard q={answer.question} a={answer} />}
        </Step>
      )}

      {answer && (
        <Step n="11" title="Prove the return">
          <p>Every step above used <b>0 AI tokens</b>: the rules, linker and question templates decided everything, with a planner in the loop for anything uncertain.</p>
          <a className="btn btn-primary" href={href("roi")}>Open ROI &amp; Efficiency</a>{" "}
          <button type="button" className="btn" disabled={busy} onClick={() => step(() => p2e.pmReport(c, asOf, "weekly"))}>Download the weekly PM report</button>
        </Step>
      )}
    </>
  );
}

function Step({ n, title, children }: { n: string; title: string; children: ReactNode }) {
  return <Card title={<><span className="step-n">{n}</span> {title}</>}>{children}</Card>;
}
