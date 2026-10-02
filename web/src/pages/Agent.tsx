import { useState } from "react";
import { p2e, type AgentReply } from "../api/p2e";
import { Badge, Empty, ErrorBox, Field, PageTitle } from "../components/ui";
import { useApp } from "../state";
import { decisionTone, fmtDate, fmtNum, humanize } from "../utils/format";
import { href, useRoute } from "../utils/route";

const DISCIPLINES = ["civil", "piping", "electrical", "instrumentation", "hse", "static_eq", "rotating_eq"];
const EXAMPLES = ["LT-4011 loop check finished yesterday at 4 pm", "Line 1217 erection completed on 14/09/2026",
  "Line 1211 reinstatement completed.", "What should I report today?"];

interface Turn { message: string; answers?: Record<string, string>; reply?: AgentReply; error?: string }

export function AgentPage() {
  const { project, asOf } = useApp();
  const { params } = useRoute();
  const [discipline, setDiscipline] = useState(params.get("discipline") ?? "");
  const [time, setTime] = useState("18:00");
  const [text, setText] = useState(params.get("message") ?? "");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const reference = `${asOf}T${time}:00`;      // relative dates resolve against this (project timezone on the server)

  const send = async (message: string, answers?: Record<string, string>) => {
    setBusy(true);
    const turn: Turn = { message, answers };
    try {
      turn.reply = await p2e.agent(project.code, { message, reference_datetime: reference, discipline: discipline || undefined, answers });
    } catch (e) {
      turn.error = (e as Error).message;
    }
    setTurns((t) => [...t, turn]);
    setBusy(false);
  };

  return (
    <>
      <PageTitle title="Time Agent" subtitle="Supervisors report progress in plain words; the agent structures it and hands it to the schedule linker. It never picks an activity itself and never invents a value." />
      <div className="agent">
        <div className="agent-settings card">
          <label className="stacked">Supervisor discipline
            <select value={discipline} onChange={(e) => setDiscipline(e.target.value)}>
              <option value="">— state it in the message —</option>{DISCIPLINES.map((d) => <option key={d} value={d}>{humanize(d)}</option>)}
            </select>
          </label>
          <label className="stacked">Reporting time ({asOf})<input type="time" value={time} onChange={(e) => setTime(e.target.value)} /></label>
          <p className="muted small">"today" / "yesterday" resolve against {reference}. Change the date with "As of" in the top bar.</p>
          <div className="chips">{EXAMPLES.map((x) => <button type="button" key={x} className="chip" onClick={() => setText(x)}>{x}</button>)}</div>
        </div>
        <div className="chat card">
          <div className="chat-log" aria-live="polite">
            {turns.length === 0 && <Empty>Example: “LT-4011 loop check finished yesterday at 4 pm”, or ask “What should I report today?”.</Empty>}
            {turns.map((t, i) => (
              <div key={i} className="turn">
                <div className="bubble user">{t.message}{t.answers && <span className="muted small"> · answers {JSON.stringify(t.answers)}</span>}</div>
                {t.error ? <ErrorBox error={t.error} /> : t.reply && <ReplyCard reply={t.reply} onAnswer={(a) => send(t.message, { ...t.answers, ...a })} busy={busy} />}
              </div>
            ))}
          </div>
          <form className="chat-input" onSubmit={(e) => { e.preventDefault(); if (text.trim()) { send(text.trim()); setText(""); } }}>
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. Line 1203 hydrotest started today at 9 am" aria-label="Message" maxLength={1000} />
            <button className="btn btn-primary" disabled={busy || !text.trim()}>{busy ? "…" : "Send"}</button>
          </form>
        </div>
      </div>
    </>
  );
}

export function ReplyCard({ reply, onAnswer, busy }: { reply: AgentReply; onAnswer: (a: Record<string, string>) => void; busy: boolean }) {
  const it = reply.interpretation as Record<string, unknown>;
  const missing = (it.missing as string[] | undefined) ?? [];
  const tone = reply.status === "recorded" ? decisionTone(reply.link?.decision, reply.link?.state) : reply.status === "rejected" ? "bad" : reply.status === "needs_clarification" ? "warn" : "info";
  return (
    <div className={`bubble agent tone-${tone}`}>
      <p><Badge tone={tone}>{humanize(reply.status)}</Badge> {reply.reply}</p>
      {reply.status !== "checklist" && it.activity_text !== undefined && (
        <div className="fields">
          <Field label="Activity">{String(it.activity_text || "—")}</Field>
          <Field label="Status">{humanize(it.event_type)}</Field>
          <Field label="Date">{fmtDate(it.event_date)}{it.date_text ? ` (“${it.date_text}”)` : ""}</Field>
          <Field label="Time">{String(it.event_time ?? "—")}</Field>
          <Field label="Quantity">{it.quantity != null ? `${it.quantity} ${it.unit}` : "—"}</Field>
          <Field label="Discipline">{humanize(it.discipline)}</Field>
          <Field label="Tags"><span className="mono">{((it.tags as string[]) ?? []).join(", ") || "—"}</span></Field>
          <Field label="Extraction confidence">{fmtNum(it.extraction_confidence)} · {String(it.interpreted_by ?? "")}</Field>
        </div>
      )}
      {reply.link && (
        <div className="link-result">
          <Badge tone={decisionTone(reply.link.decision, reply.link.state)}>{reply.link.decision}</Badge>{" "}
          {reply.link.plan_node_code ? <a className="mono" href={href("schedule", { q: reply.link.plan_node_code })}>{reply.link.plan_node_code}</a> : <span>no activity applied</span>}{" "}
          <span className="muted">confidence {fmtNum(reply.link.confidence)}</span>{" "}
          <a href={href("linking", { event: reply.link.event_id, decision: "" })}>open in linking →</a>
          {reply.link.conflict && <p><Badge tone="bad">cross-source date conflict</Badge> {reply.link.conflict.dates.join(" vs ")}</p>}
          {reply.link.decision !== "matched" && reply.link.candidates.length > 0 && (
            <ol className="mini-cands">{reply.link.candidates.slice(0, 3).map((c) => <li key={c.rank}><span className="mono">{c.plan_node_code}</span> {c.activity_name} <span className="muted">{fmtNum(c.score)}</span></li>)}</ol>
          )}
        </div>
      )}
      {reply.status === "needs_clarification" && (missing.includes("date") || missing.includes("discipline")) && <ClarifyForm missing={missing} onAnswer={onAnswer} busy={busy} />}
      {reply.checklist && (
        <table className="table compact">
          <thead><tr><th>Activity</th><th>Expected because</th><th>Last report</th><th>Today</th></tr></thead>
          <tbody>{reply.checklist.map((c) => (
            <tr key={c.plan_node_code}><td><span className="mono">{c.plan_node_code}</span> {c.activity_name}</td><td className="small">{c.expectation}</td>
              <td>{fmtDate(c.last_reported)}</td><td>{c.reported_today ? <Badge tone="ok">reported</Badge> : <Badge tone="warn">not yet</Badge>}</td></tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}

function ClarifyForm({ missing, onAnswer, busy }: { missing: string[]; onAnswer: (a: Record<string, string>) => void; busy: boolean }) {
  const [date, setDate] = useState("");
  const [disc, setDisc] = useState("");
  return (
    <form className="inline clarify" onSubmit={(e) => { e.preventDefault(); const a: Record<string, string> = {}; if (date) a.date = date; if (disc) a.discipline = disc; onAnswer(a); }}>
      {missing.includes("date") && <input value={date} onChange={(e) => setDate(e.target.value)} placeholder="today, yesterday or 2026-09-14" aria-label="Date answer" />}
      {missing.includes("discipline") && (
        <select value={disc} onChange={(e) => setDisc(e.target.value)} aria-label="Discipline answer">
          <option value="">discipline…</option>{DISCIPLINES.map((d) => <option key={d} value={d}>{humanize(d)}</option>)}
        </select>
      )}
      <button className="btn btn-sm btn-primary" disabled={busy || (!date && !disc)}>Answer</button>
    </form>
  );
}
