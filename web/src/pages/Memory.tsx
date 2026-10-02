import { useState } from "react";
import { p2e, type Answer, type Citation } from "../api/p2e";
import { EvidenceModal } from "../components/Evidence";
import { Async, Badge, Card, Empty, ErrorBox, PageTitle } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useApp } from "../state";
import { fmtDate, humanize } from "../utils/format";
import { href } from "../utils/route";

const SUGGESTED = [
  "What delayed piping work?", "Which activities started late?", "Which civil activities in Area 3 finished late by 2026-08-31?",
  "How long did backfilling take?", "How many spools per day were erected on line 1405?", "When did each discipline last report?",
  "What is the status of P-101A grouting?", "Why was HT-SWBD-1 installation held up?",
];

export function MemoryPage() {
  const { project, asOf } = useApp();
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
      <PageTitle title="Project memory" subtitle="Ask the recorded project history. Answers come from fixed query templates or cited retrieval; every number cites its records. No free-form SQL." />
      <div className="split split-wide">
        <div>
          <Card title="Ask">
            <form className="ask" onSubmit={(e) => { e.preventDefault(); if (question.trim()) ask(question.trim()); }}>
              <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="e.g. What delayed electrical cable pulling in Area 3?" aria-label="Question" maxLength={500} />
              <button className="btn btn-primary" disabled={busy || question.trim().length < 3}>{busy ? "…" : "Ask"}</button>
            </form>
            <div className="chips">{SUGGESTED.map((s) => <button type="button" key={s} className="chip" onClick={() => { setQuestion(s); ask(s); }}>{s}</button>)}</div>
            <p className="muted small">Questions are answered as of {asOf} unless they name a date (“by 2026-08-31”). For today's reporting checklist use the <a href={href("agent", { message: "What should I report today?" })}>Time Agent</a>.</p>
          </Card>
          {history.length === 0 && <Empty>Ask a question or pick one above.</Empty>}
          {history.map((h, i) => <AnswerCard key={history.length - i} q={h.q} a={h.a} error={h.error} />)}
        </div>
        <Card title="Knowledge entries">
          <Async state={knowledge} what="Distilling knowledge">
            {(ks) => ks.length === 0 ? <Empty>No knowledge yet.</Empty> : (
              <ul className="knowledge">{ks.map((k) => (
                <li key={k.id}><Badge tone={k.kind === "delays" ? "warn" : "ai"}>{k.kind}</Badge> <strong>{k.title}</strong><p className="small">{k.text}</p>
                  <span className="muted small">{k.citations.length} cited records</span></li>
              ))}</ul>
            )}
          </Async>
        </Card>
      </div>
    </>
  );
}

export function AnswerCard({ q, a, error }: { q: string; a?: Answer; error?: string }) {
  const [evidence, setEvidence] = useState<number | null>(null);
  return (
    <Card title={q} className="answer">
      {error ? <ErrorBox error={error} /> : a && (
        <>
          <p className="answer-text">{a.answer}</p>
          <p className="muted small"><Badge tone="info">{a.intent}</Badge> as of {fmtDate(a.filters.as_of)}
            {Object.entries(a.filters).filter(([k, v]) => k !== "as_of" && v && (!Array.isArray(v) || v.length)).map(([k, v]) => ` · ${humanize(k)}: ${Array.isArray(v) ? v.join(", ") : v}`)}</p>
          {a.citations.length === 0 ? <p className="muted small">No records cited — nothing is claimed.</p> : (
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
  if (c.kind === "activity") return <li><Badge tone="ai">activity</Badge> <a className="mono" href={href("schedule", { q: String(c.id) })}>{c.id}</a> {c.text} <span className="muted small">{c.date}</span></li>;
  if (c.kind === "event") return <li><Badge tone="info">report</Badge> <button type="button" className="linkish" onClick={() => onEvidence(Number(c.id))}>#{c.id}</button> {c.text} <span className="muted small">{c.date}{c.activity ? ` · ${c.activity}` : ""}</span></li>;
  return <li><Badge>document</Badge> <a href={href("reports", { doc: c.id })}>{c.text}</a> <span className="muted small">{c.date}</span></li>;
}
