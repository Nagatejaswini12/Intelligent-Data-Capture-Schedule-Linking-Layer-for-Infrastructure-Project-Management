import { useEffect, useState } from "react";
import { p2e } from "../api/p2e";
import { Async, Badge, Card, PageTitle } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useT } from "../i18n";

// Guide and terms come from the backend (data/help/*.json), the same text the assistant answers from.
export function GuidePage() {
  const { t, lang } = useT();
  const state = useApi(() => p2e.helpDoc("guide"), []);
  return (
    <>
      <PageTitle title={t("guide.title")} subtitle={t("guide.sub")} />
      <Async state={state}>
        {(doc) => (
          <div className="grid-2">
            {doc.sections.map((s) => (
              <Card key={s.id} title={s.title?.[lang]}>
                <ol className="guide-steps">{(s.steps?.[lang] ?? []).map((step, i) => <li key={i}>{step}</li>)}</ol>
              </Card>
            ))}
          </div>
        )}
      </Async>
    </>
  );
}

export function TermsPage() {
  const { t, lang } = useT();
  const state = useApi(() => p2e.helpDoc("terms"), []);
  return (
    <Async state={state}>
      {(doc) => (
        <>
          <PageTitle title={doc.title?.[lang] ?? t("nav.terms")} subtitle={<><Badge tone="warn">{doc.status?.[lang]}</Badge> {t("terms.draft")}</>} />
          <Card>
            {doc.sections.map((s, i) => (
              <section key={i} className="terms-section"><h3>{s.heading?.[lang]}</h3><p>{s.text?.[lang]}</p></section>
            ))}
          </Card>
        </>
      )}
    </Async>
  );
}

const VIDEO = "guide-video.mp4";   // drop the NotebookLM export at web/public/guide-video.mp4

export function VideoPage() {
  const { t } = useT();
  const [available, setAvailable] = useState<boolean | null>(null);
  useEffect(() => {
    fetch(VIDEO, { method: "HEAD" }).then((r) => setAvailable(r.ok && (r.headers.get("content-type") ?? "").startsWith("video")),
      () => setAvailable(false));
  }, []);
  return (
    <>
      <PageTitle title={t("video.title")} subtitle={t("video.sub")} />
      <Card>
        {available === null ? null : available
          ? <video className="guide-video" src={VIDEO} controls preload="metadata" />
          : <p className="muted">{t("video.missing")}</p>}
      </Card>
    </>
  );
}
