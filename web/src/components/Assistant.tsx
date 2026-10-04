import { useState } from "react";
import { p2e, type AssistantReply } from "../api/p2e";
import { useT } from "../i18n";
import { useApp } from "../state";
import { ErrorBox } from "./ui";

// Floating "Ask P2E" assistant: typed or spoken questions in English / Tamil / Hindi, answered by the backend's scoped
// assistant (this app, this project, Oil India only) with sources. Browser speech: recognition + optional spoken replies.
type Recognizer = { lang: string; interimResults: boolean; onresult: (e: { results: { 0: { transcript: string } }[] }) => void;
  onend: () => void; onerror: () => void; start: () => void };
const g = globalThis as unknown as { SpeechRecognition?: new () => Recognizer; webkitSpeechRecognition?: new () => Recognizer };
const SpeechRec = g.SpeechRecognition ?? g.webkitSpeechRecognition;

interface Turn { q: string; reply?: AssistantReply; error?: string }

export function Assistant() {
  const { t, lang, speech } = useT();
  const { project, asOf } = useApp();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [voice, setVoice] = useState(false);

  const say = (s: string, l: string) => {
    if (!voice || !("speechSynthesis" in globalThis)) return;
    const u = new SpeechSynthesisUtterance(s);
    u.lang = l;
    speechSynthesis.cancel();
    speechSynthesis.speak(u);
  };

  const ask = async (q: string) => {
    if (!q.trim()) return;
    setBusy(true);
    const turn: Turn = { q };
    try {
      turn.reply = await p2e.assistant(project.code, { question: q, lang, as_of: asOf });
      say(turn.reply.answer, { en: "en-IN", ta: "ta-IN", hi: "hi-IN" }[turn.reply.lang]);
    } catch (e) {
      turn.error = (e as Error).message;
    }
    setTurns((ts) => [...ts, turn]);
    setText("");
    setBusy(false);
  };

  const listen = () => {
    if (!SpeechRec) return;
    const r = new SpeechRec();
    r.lang = speech;
    r.interimResults = false;
    r.onresult = (e) => setText(e.results[0][0].transcript);
    r.onend = r.onerror = () => setListening(false);
    setListening(true);
    r.start();
  };

  if (!open) return <button type="button" className="assistant-fab btn btn-primary" onClick={() => setOpen(true)}>💬 {t("as.open")}</button>;
  return (
    <aside className="assistant card" aria-label={t("as.title")}>
      <header className="assistant-head">
        <strong>{t("as.title")}</strong>
        <button type="button" className="btn btn-sm" onClick={() => setOpen(false)} aria-label={t("as.close")}>✕</button>
      </header>
      <p className="muted small">{t("as.scope")}</p>
      <div className="assistant-log" aria-live="polite">
        {turns.length === 0 && (
          <div className="chips">{["as.ex1", "as.ex2", "as.ex3"].map((k) => (
            <button type="button" key={k} className="chip" onClick={() => ask(t(k))}>{t(k)}</button>
          ))}</div>
        )}
        {turns.map((tu, i) => (
          <div key={i} className="turn">
            <div className="bubble user">{tu.q}</div>
            {tu.error ? <ErrorBox error={tu.error} /> : tu.reply && (
              <div className="bubble agent">
                <p>{tu.reply.answer}</p>
                {tu.reply.sources.length > 0 && (
                  <p className="small">{t("as.sources")}: {tu.reply.sources.map((s, j) => (
                    <span key={j}>{j > 0 && " · "}<a href={s.url} target="_blank" rel="noreferrer noopener">{s.title}</a> ({s.as_of})</span>
                  ))}</p>
                )}
                {tu.reply.sources.length === 0 && tu.reply.citations.length > 0 && (
                  <p className="small muted">{tu.reply.citations.slice(0, 5).map((c) => String(c.id)).join(", ")}</p>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
      <form className="chat-input" onSubmit={(e) => { e.preventDefault(); ask(text); }}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder={t("as.placeholder")} aria-label={t("as.placeholder")} maxLength={500} />
        {SpeechRec && <button type="button" className="btn" onClick={listen} disabled={busy || listening} aria-label="🎤">{listening ? "…" : "🎤"}</button>}
        <button className="btn btn-primary" disabled={busy || !text.trim()}>{busy ? "…" : t("as.ask")}</button>
      </form>
      {"speechSynthesis" in globalThis && (
        <label className="small"><input type="checkbox" checked={voice} onChange={(e) => setVoice(e.target.checked)} /> {t("agent.speak")}</label>
      )}
    </aside>
  );
}
