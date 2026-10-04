import { useState } from "react";
import { p2e, type Answer, type Citation } from "../api/p2e";
import { EvidenceModal } from "../components/Evidence";
import { Async, Badge, Card, Empty, ErrorBox, PageTitle } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useApp } from "../state";
import { useT, T } from "../i18n";
import { fmtDate, humanize } from "../utils/format";
import { href } from "../utils/route";

const SUGGESTED = [
  "What delayed piping work?", "Which activities started late?", "Which civil activities in Area 3 finished late by 2026-08-31?",
  "How long did backfilling take?", "How many spools per day were erected on line 1405?", "When did each discipline last report?",
  "What is the status of P-101A grouting?", "Why was HT-SWBD-1 installation held up?",
];

export function MemoryPage() {
  const { project, asOf } = useApp();
  const { t } = useT();
  const [question, setQuestion] = useState("");
  const [history, setHistory] = useState<{ q: string; a?: Answer; error?: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const knowledge = useApi(() => p2e.knowledge(project.code, asOf), [project.code, asOf]);
  const ask = async (q: string) => {
    setBusy(true);
    try {
      const a = await p2e.ask(project.code, q, asOf);
      setHistory((h) => [{ q, a }, ...h]);
    } catch (e) {
      setHistory((h) => [{ q, error: (e as Error).message }, ...h]);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <PageTitle icon="agent-memory" title={t("memory.title")} subtitle={t("memory.sub")} />
      <div className="split split-wide">
        <div>
          <Card title={T("as.ask")}>
            <form className="ask" onSubmit={(e) => { e.preventDefault(); if (question.trim()) ask(question.trim()); }}>
              <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder={T("me.placeholder")} aria-label={T("me.question")} maxLength={500} />
              <button className="btn btn-primary" disabled={busy || question.trim().length < 3}>{busy ? "…" : T("as.ask")}</button>
            </form>
            <div className="chips">{SUGGESTED.map((s) => <button type="button" key={s} className="chip" onClick={() => { setQuestion(s); ask(s); }}>{s}</button>)}</div>
            <p className="muted small">{T("me.note", { asOf })} <a href={href("agent", { message: "What should I report today?" })}>{T("nav.agent")}</a>.</p>
          </Card>
          {history.length === 0 && <Empty>{T("me.empty")}</Empty>}
          {history.map((h, i) => <AnswerCard key={history.length - i} q={h.q} a={h.a} error={h.error} />)}
        </div>
        <Card title={T("me.knowledge")}>
          <Async state={knowledge} what={T("me.loading")}>
            {(ks) => ks.length === 0 ? <Empty>{T("me.noKnowledge")}</Empty> : (
              <ul className="knowledge">{ks.map((k) => (
                <li key={k.id}><Badge tone={k.kind === "delays" ? "warn" : "ai"}>{humanize(k.kind)}</Badge> <strong>{k.title}</strong><p className="small">{k.text}</p>
                  <span className="muted small">{T("me.cited", { n: k.citations.length })}</span></li>
              ))}</ul>
            )}
          </Async>
        </Card>
      </div>
    </>
  );
}

export function AnswerCard({ q, a, error }: { q: string; a?: Answer; error?: string }) {
  const { t } = useT();
  const [evidence, setEvidence] = useState<number | null>(null);
  return (
    <Card title={q} className="answer">
      {error ? <ErrorBox error={error} /> : a && (
        <>
          <p className="answer-text">{a.answer}</p>
          <p className="muted small"><Badge tone="info">{humanize(a.intent)}</Badge> <Badge tone="ok">{t("memory.tokens")}</Badge> as of {fmtDate(a.filters.as_of)}
            {Object.entries(a.filters).filter(([k, v]) => k !== "as_of" && v && (!Array.isArray(v) || v.length)).map(([k, v]) => ` · ${humanize(k)}: ${Array.isArray(v) ? v.join(", ") : v}`)}</p>
          {a.citations.length === 0 ? <p className="muted small">{T("me.noCite")}</p> : (
            <details open={a.citations.length <= 12}>
              <summary>{a.citations.length} citations</summary>
              <ol className="citations">{a.citations.map((c, i) => <CitationItem key={i} c={c} onEvidence={setEvidence} />)}</ol>
            </details>
          )}
        </>
      )}
      {evidence !== null && <EvidenceModal eventId={evidence} onClose={() => setEvidence(null)} />}
    </Card>
  );
}

function CitationItem({ c, onEvidence }: { c: Citation; onEvidence: (id: number) => void }) {
  if (c.kind === "activity") return <li><Badge tone="ai">{T("f.activity")}</Badge> <a className="mono" href={href("schedule", { q: String(c.id) })}>{c.id}</a> {c.text} <span className="muted small">{c.date}</span></li>;
  if (c.kind === "event") return <li><Badge tone="info">{T("f.report")}</Badge> <button type="button" className="linkish" onClick={() => onEvidence(Number(c.id))}>#{c.id}</button> {c.text} <span className="muted small">{c.date}{c.activity ? ` · ${c.activity}` : ""}</span></li>;
  return <li><Badge>{T("rp.doc")}</Badge> <a href={href("reports", { doc: c.id })}>{c.text}</a> <span className="muted small">{c.date}</span></li>;
}
