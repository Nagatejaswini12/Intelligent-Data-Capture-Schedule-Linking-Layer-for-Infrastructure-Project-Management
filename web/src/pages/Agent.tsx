import { useEffect, useState } from "react";
import { p2e, type AgentReply } from "../api/p2e";
import { Badge, Empty, ErrorBox, Field, PageTitle } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useSpeech, type VoiceLang } from "../hooks/useSpeech";
import { useApp } from "../state";
import { useT, T } from "../i18n";
import { decisionTone, fmtDate, fmtNum, humanize } from "../utils/format";
import { href, useRoute } from "../utils/route";

const DISCIPLINES = ["civil", "piping", "electrical", "instrumentation", "hse", "static_eq", "rotating_eq"];
const EXAMPLES = ["agent.ex1", "agent.ex2", "agent.ex3", "agent.ex4"];

// Menu taps send the plan name plus a glossary verb through the normal rules interpreter and linker (0 LLM tokens; the
// linker's gates still apply, so near-identical names go to planner review instead of a guess).
const TAP: [label: string, verb: string][] = [["agent.start", "tap.start"], ["agent.finish", "tap.finish"], ["agent.hold", "tap.hold"]];

interface Turn { message: string; answers?: Record<string, string>; reply?: AgentReply; error?: string; retracted?: boolean; note?: string }

const PRONOUN = /\b(that one|the same one|same one|it)\b/i;
export const UNDO = /^\s*(undo|undo last|cancel last)\s*$/i;

/** Session memory: "it finished today" -> "<last recorded activity> finished today". The expanded text is what gets sent
 * and shown, so the stored evidence is exactly what the supervisor saw. No previous activity -> unchanged. */
export function expandReference(message: string, lastActivity: string | null): string {
  return lastActivity && PRONOUN.test(message) ? message.replace(PRONOUN, lastActivity) : message;
}

export function AgentPage() {
  const { project, asOf } = useApp();
  const { t: tr, lang } = useT();
  const { params } = useRoute();
  const [discipline, setDiscipline] = useState(params.get("discipline") ?? "");
  const [time, setTime] = useState("18:00");
  const [text, setText] = useState(params.get("message") ?? "");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const voice = useSpeech();
  const [voiceLang, setVoiceLang] = useState<VoiceLang>(lang);
  useEffect(() => setVoiceLang(lang), [lang]);           // the voice follows the page language
  const [heardNote, setHeardNote] = useState<string | null>(null);
  const [voiceReplies, setVoiceReplies] = useState(false);
  const reference = `${asOf}T${time}:00`;      // relative dates resolve against this (project timezone on the server)
  const menu = useApi(() => (discipline ? p2e.checklist(project.code, { as_of: asOf, discipline }) : Promise.resolve(null)),
    [project.code, asOf, discipline]);

  const recorded = turns.filter((t) => t.reply?.status === "recorded" && t.reply.event_id && !t.retracted);
  const last = recorded[recorded.length - 1];
  const lastActivity = last ? String(last.reply!.interpretation.activity_text ?? "") || null : null;

  const retract = async (eventId: number) => {
    setBusy(true);
    try {
      await p2e.retract(project.code, eventId);
      setTurns((ts) => [...ts.map((t) => (t.reply?.event_id === eventId ? { ...t, retracted: true } : t)),
        { message: "undo", note: tr("agent.undone") }]);
      if (voiceReplies) voice.speak(tr("agent.undone"), lang);
    } catch (e) {
      setTurns((ts) => [...ts, { message: "undo", error: (e as Error).message }]);
    }
    setBusy(false);
  };

  const send = async (typed: string, answers?: Record<string, string>, spoken = false) => {
    if (UNDO.test(typed)) {
      if (last) return retract(last.reply!.event_id!);
      setTurns((ts) => [...ts, { message: typed, error: tr("agent.nothingUndo") }]);
      return;
    }
    const message = answers ? typed : expandReference(typed, lastActivity);
    setBusy(true);
    const turn: Turn = { message, answers };
    try {
      turn.reply = await p2e.agent(project.code, { message, reference_datetime: reference, discipline: discipline || undefined, answers, lang });
      if ((voiceReplies || spoken) && !(await voice.speak(turn.reply.reply, lang))) turn.note = T("as.noVoice");
      if (turn.reply.status === "recorded") menu.reload();
    } catch (e) {
      turn.error = (e as Error).message;
    }
    setTurns((t) => [...t, turn]);
    setBusy(false);
  };

  // Voice: BHASHINI when configured (adds Assamese, translated to English for the Time Agent), else the browser.
  const listen = async () => {
    if (voice.listening) { voice.stop(); return; }
    try {
      const heard = await voice.listen(voiceLang);
      setHeardNote(voiceLang === "as" ? heard : null);
      send(voiceLang === "as" ? await voice.translate(heard, "as", "en") : heard, undefined, true);   // spoken: sent at once, answered aloud
    } catch (e) {
      setTurns((ts) => [...ts, { message: "🎤", error: (e as Error).message }]);
    }
  };

  return (
    <>
      <PageTitle icon="agent-time" title={tr("agent.title")} subtitle={tr("agent.sub")} />
      <div className="agent">
        <div className="agent-settings card">
          <label className="stacked">{tr("agent.discipline")}
            <select value={discipline} onChange={(e) => setDiscipline(e.target.value)}>
              <option value="">{tr("agent.stateIt")}</option>{DISCIPLINES.map((d) => <option key={d} value={d}>{humanize(d)}</option>)}
            </select>
          </label>
          <label className="stacked">{tr("agent.time")} ({asOf})<input type="time" value={time} onChange={(e) => setTime(e.target.value)} /></label>
          <p className="muted small">{T("agent.relNote", { ref: reference })}</p>
          <div className="chips">{EXAMPLES.map((k) => <button type="button" key={k} className="chip" onClick={() => setText(tr(k))}>{tr(k)}</button>)}</div>
          {"speechSynthesis" in globalThis && (
            <label className="small"><input type="checkbox" checked={voiceReplies} onChange={(e) => setVoiceReplies(e.target.checked)} /> {tr("agent.speak")}</label>
          )}
          <h3>{tr("agent.menu")}</h3>
          {!discipline ? <p className="muted small">{tr("agent.pick")}</p>
            : menu.error ? <ErrorBox error={menu.error} />
            : menu.loading ? <p className="muted small">{T("common.loading")}…</p>
            : menu.data && menu.data.items.length === 0 ? <p className="muted small">{tr("agent.nothing")}</p>
            : (
              <ul className="menu-list">{menu.data?.items.map((i) => (
                <li key={i.plan_node_code}>
                  <span><span className="mono">{i.plan_node_code}</span> {i.activity_name}
                    {(i as { reported_today?: boolean }).reported_today && <> <Badge tone="ok">{tr("agent.reported")}</Badge></>}</span>
                  <span className="menu-actions">{TAP.map(([label, verb]) => (
                    <button type="button" key={label} className="btn btn-sm" disabled={busy}
                      onClick={() => send(`${i.activity_name} ${tr(verb)}`)}>{tr(label)}</button>
                  ))}</span>
                </li>
              ))}</ul>
            )}
        </div>
        <div className="chat card">
          <div className="chat-log" aria-live="polite">
            {turns.length === 0 && <Empty>{tr("agent.empty")}</Empty>}
            {turns.map((t, i) => (
              <div key={i} className="turn">
                <div className="bubble user">{t.message}{t.answers && <span className="muted small"> · {T("agent.answers")} {Object.values(t.answers).join(", ")}</span>}</div>
                {t.error ? <ErrorBox error={t.error} /> : t.note && !t.reply ? <div className="bubble agent tone-info"><p>{t.note}</p></div>
                  : t.reply && <ReplyCard reply={t.reply} onAnswer={(a) => send(t.message, { ...t.answers, ...a })} busy={busy} />}
                {t.reply && t.note && <p className="small warn-text">{t.note}</p>}
                {t.retracted && <Badge tone="warn">{tr("agent.retracted")}</Badge>}
                {!t.retracted && t === last && <button type="button" className="btn btn-sm" disabled={busy} onClick={() => retract(t.reply!.event_id!)}>{tr("agent.undo")}</button>}
              </div>
            ))}
          </div>
          {heardNote && <p className="muted small heard-note">অসমীয়া: {heardNote} → EN (BHASHINI)</p>}
          <form className="chat-input" onSubmit={(e) => { e.preventDefault(); if (text.trim()) { send(text.trim()); setText(""); } }}>
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder={tr("agent.placeholder")} aria-label={T("agent.message")} maxLength={1000} />
            {voice.provider !== "none" && <button type="button" className="btn" onClick={listen} disabled={busy} aria-label={T("as.mic")} title={T("as.mic")}>{voice.listening ? "■ " + tr("agent.listening") : <img src="/brand/voice.webp" alt="" width={20} height={20} />}</button>}
            {voice.provider !== "none" && (
              <select value={voiceLang} onChange={(e) => setVoiceLang(e.target.value as VoiceLang)} aria-label={T("as.voiceLang")}>
                {voice.languages.map((l) => <option key={l} value={l}>{{ en: "EN", hi: "हि", ta: "த", as: "অ" }[l]}</option>)}
              </select>
            )}
            <button className="btn btn-primary" disabled={busy || !text.trim()}>{busy ? "…" : tr("agent.send")}</button>
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
          <Field label={T("f.activity")}>{String(it.activity_text || "—")}</Field>
          <Field label={T("f.status")}>{humanize(it.event_type)}</Field>
          <Field label={T("f.date")}>{fmtDate(it.event_date)}{it.date_text ? ` (“${it.date_text}”)` : ""}</Field>
          <Field label={T("f.time")}>{String(it.event_time ?? "—")}</Field>
          <Field label={T("f.quantity")}>{it.quantity != null ? `${it.quantity} ${it.unit}` : "—"}</Field>
          <Field label={T("f.discipline")}>{humanize(it.discipline)}</Field>
          <Field label={T("f.tags")}><span className="mono">{((it.tags as string[]) ?? []).join(", ") || "—"}</span></Field>
          <Field label={T("agent.extConf")}>{fmtNum(it.extraction_confidence)} · {String(it.interpreted_by ?? "")}</Field>
        </div>
      )}
      {reply.link && (
        <div className="link-result">
          <Badge tone={decisionTone(reply.link.decision, reply.link.state)}>{humanize(reply.link.decision)}</Badge>{" "}
          {reply.link.plan_node_code ? <a className="mono" href={href("schedule", { q: reply.link.plan_node_code })}>{reply.link.plan_node_code}</a> : <span>{T("agent.noApplied")}</span>}{" "}
          <span className="muted">{T("f.confidence")} {fmtNum(reply.link.confidence)}</span>{" "}
          <a href={href("linking", { event: reply.link.event_id, decision: "" })}>{T("agent.openLinking")}</a>
          {reply.link.conflict && <p><Badge tone="bad">{T("lk.dateConflict")}</Badge> {reply.link.conflict.dates.join(" vs ")}</p>}
          {reply.link.decision !== "matched" && reply.link.candidates.length > 0 && (
            <ol className="mini-cands">{reply.link.candidates.slice(0, 3).map((c) => <li key={c.rank}><span className="mono">{c.plan_node_code}</span> {c.activity_name} <span className="muted">{fmtNum(c.score)}</span></li>)}</ol>
          )}
        </div>
      )}
      {reply.status === "needs_clarification" && (missing.includes("date") || missing.includes("discipline")) && <ClarifyForm missing={missing} onAnswer={onAnswer} busy={busy} />}
      {reply.checklist && (
        <table className="table compact">
          <thead><tr><th>{T("f.activity")}</th><th>{T("agent.expected")}</th><th>{T("agent.lastReport")}</th><th>{T("agent.today")}</th></tr></thead>
          <tbody>{reply.checklist.map((c) => (
            <tr key={c.plan_node_code}><td><span className="mono">{c.plan_node_code}</span> {c.activity_name}</td><td className="small">{humanize(c.expectation)}</td>
              <td>{fmtDate(c.last_reported)}</td><td>{c.reported_today ? <Badge tone="ok">{T("agent.reported")}</Badge> : <Badge tone="warn">{T("agent.notYet")}</Badge>}</td></tr>
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
      {missing.includes("date") && <input value={date} onChange={(e) => setDate(e.target.value)} placeholder={T("agent.dateHint")} aria-label={T("f.date")} />}
      {missing.includes("discipline") && (
        <select value={disc} onChange={(e) => setDisc(e.target.value)} aria-label={T("f.discipline")}>
          <option value="">{T("f.discipline")}…</option>{DISCIPLINES.map((d) => <option key={d} value={d}>{humanize(d)}</option>)}
        </select>
      )}
      <button className="btn btn-sm btn-primary" disabled={busy || (!date && !disc)}>{T("agent.answer")}</button>
    </form>
  );
}
