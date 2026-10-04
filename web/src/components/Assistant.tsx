import { useState } from "react";
import { p2e, type AssistantReply } from "../api/p2e";
import { useSpeech, type VoiceLang } from "../hooks/useSpeech";
import { useT } from "../i18n";
import { useApp } from "../state";
import { ErrorBox } from "./ui";

// Floating "Ask P2E" assistant: typed or spoken questions, answered by the backend's scoped assistant (this app, this
// project, Oil India from official sources only). Voice uses BHASHINI when the server has it (adds Assamese: the question
// is translated to English, answered, and the answer translated back), otherwise the browser's speech engine.
interface Turn { q: string; reply?: AssistantReply; shown?: string; error?: string }

export function Assistant() {
  const { t, lang } = useT();
  const { project, asOf } = useApp();
  const voice = useSpeech();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [speakReplies, setSpeakReplies] = useState(false);
  const [voiceLang, setVoiceLang] = useState<VoiceLang>(lang);

  const ask = async (q: string, spokenIn: VoiceLang = lang) => {
    if (!q.trim()) return;
    setBusy(true);
    const turn: Turn = { q };
    try {
      const assamese = spokenIn === "as";
      const question = assamese ? await voice.translate(q, "as", "en") : q;
      turn.reply = await p2e.assistant(project.code, { question, lang: assamese ? "en" : lang, as_of: asOf });
      turn.shown = assamese ? await voice.translate(turn.reply.answer, "en", "as") : turn.reply.answer;
      if (speakReplies) voice.speak(turn.shown, assamese ? "as" : turn.reply.lang);
    } catch (e) {
      turn.error = (e as Error).message;
    }
    setTurns((ts) => [...ts, turn]);
    setText("");
    setBusy(false);
  };

  const mic = async () => {
    if (voice.listening) { voice.stop(); return; }
    try {
      const heard = await voice.listen(voiceLang);
      if (voiceLang === "as") ask(heard, "as"); else setText(heard);
    } catch (e) {
      setTurns((ts) => [...ts, { q: "🎤", error: (e as Error).message }]);
    }
  };

  if (!open) return <button type="button" className="assistant-fab btn btn-primary" onClick={() => setOpen(true)}>💬 {t("as.open")}</button>;
  return (
    <aside className="assistant card" aria-label={t("as.title")}>
      <header className="assistant-head">
        <strong>{t("as.title")}</strong>
        <button type="button" className="btn btn-sm" onClick={() => setOpen(false)} aria-label={t("as.close")}>✕</button>
      </header>
      <p className="muted small">{t("as.scope")}{voice.provider === "bhashini" && " · 🎤 BHASHINI"}</p>
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
                <p>{tu.shown ?? tu.reply.answer}</p>
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
        {voice.provider !== "none" && (
          <button type="button" className="btn" onClick={mic} disabled={busy} aria-label="🎤">{voice.listening ? "■" : "🎤"}</button>
        )}
        <button className="btn btn-primary" disabled={busy || !text.trim()}>{busy ? "…" : t("as.ask")}</button>
      </form>
      <div className="assistant-foot small">
        {voice.provider !== "none" && (
          <select value={voiceLang} onChange={(e) => setVoiceLang(e.target.value as VoiceLang)} aria-label="Voice language">
            {voice.languages.map((l) => <option key={l} value={l}>{{ en: "English", hi: "हिन्दी", ta: "தமிழ்", as: "অসমীয়া" }[l]}</option>)}
          </select>
        )}
        <label><input type="checkbox" checked={speakReplies} onChange={(e) => setSpeakReplies(e.target.checked)} /> {t("agent.speak")}</label>
      </div>
    </aside>
  );
}
