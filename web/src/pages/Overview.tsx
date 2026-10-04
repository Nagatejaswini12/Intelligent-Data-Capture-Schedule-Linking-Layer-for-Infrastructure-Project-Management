import { p2e } from "../api/p2e";
import { useState } from "react";
import { Async, Bars, Card, CompareBars, Flow, Kanban, Kpi, PageTitle, SCurve, StackBars } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useApp } from "../state";
import { useT, T } from "../i18n";
import { humanize, pct } from "../utils/format";
import { navigate } from "../utils/route";

const STATUS = [
  { key: "completed", label: "completed", tone: "ok" as const },        // labels go through humanize(): translated
  { key: "in_progress", label: "in_progress", tone: "info" as const },
  { key: "not_started", label: "not_started", tone: "muted" as const },
];

export function OverviewPage() {
  const { project, asOf, live } = useApp();
  const { t } = useT();
  const [disc, setDisc] = useState("");
  const c = project.code;
  const state = useApi(async () => {
    const [dash, data, matched, review, unmatched, docs, events, delays] = await Promise.all([
      p2e.dashboard(c, asOf), p2e.dataset(c, asOf),
      p2e.links(c, { decision: "matched", limit: 1 }), p2e.links(c, { decision: "review", limit: 1 }), p2e.links(c, { decision: "unmatched", limit: 1 }),
      p2e.documents(c, { limit: 1 }), p2e.events(c, { limit: 1 }), p2e.delays(c, asOf),
    ]);
    return { dash, rows: data.items, matched: matched.total, review: review.total, unmatched: unmatched.total, docs: docs.total, events: events.total, delays };
  }, [c, asOf, live]);

  return (
    <>
      <PageTitle title={t("overview.title")} subtitle={t("overview.sub", { asOf })} />
      <Async state={state} what={T("ov.loading")}>
        {({ dash, rows, matched, review, unmatched, docs, events, delays }) => {
          const sum = (k: "completed" | "in_progress" | "not_started" | "started_late" | "finished_late" | "due_not_started") =>
            Object.values(dash.by_discipline).reduce((a, v) => a + (v[k] ?? 0), 0);
          const total = rows.length;
          const plannedDone = rows.filter((r) => r.planned_finish <= asOf).length;
          const silent = Object.values(dash.silent_activities_by_discipline).reduce((a, b) => a + b, 0);
          const byDisc = Object.entries(dash.by_discipline).map(([d, v]) => [d, v as unknown as Record<string, number>] as [string, Record<string, number>]);
          const plannedVsActual = Object.keys(dash.by_discipline).map((d) => {
            const rs = rows.filter((r) => (r.discipline ?? "-") === d);
            return [d, rs.filter((r) => r.planned_finish <= asOf).length, rs.filter((r) => r.status === "completed").length] as [string, number, number];
          });
          return (
            <>
              <Flow steps={[
                { label: T("ov.f1"), value: T("ov.v1", { n: docs }), tone: "info" },
                { label: T("ov.f2"), value: T("ov.v2", { n: events }), tone: "ai" },
                { label: T("ov.f3"), value: T("ov.v3", { n: matched }), tone: "ai" },
                { label: T("ov.f4"), value: T("ov.v4", { n: review }), tone: review ? "warn" : "ok" },
                { label: T("ov.f5"), value: T("ov.v5", { n: sum("completed") + sum("in_progress") }), tone: "ok" },
                { label: T("ov.f6"), value: T("ov.v6"), tone: "info" },
              ]} />
              <div className="kpis">
                <Kpi label={t("kpi.complete")} value={`${sum("completed")} / ${total}`} hint={T("ov.ofActivities", { p: pct(sum("completed"), total) })} tone="ok" onClick={() => navigate("schedule", { status: "completed" })} />
                <Kpi label={t("kpi.plannedComplete")} value={`${plannedDone} / ${total}`} hint={T("ov.perBaseline", { p: pct(plannedDone, total) })} tone="info" />
                <Kpi label={t("kpi.inProgress")} value={sum("in_progress")} tone="info" onClick={() => navigate("schedule", { status: "in_progress" })} />
                <Kpi label={t("kpi.review")} value={dash.review_backlog.pending_events} hint={T("ov.blocked", { n: dash.review_backlog.blocked_activities })} tone={dash.review_backlog.pending_events ? "warn" : "ok"} onClick={() => navigate("linking")} />
                <Kpi label={t("kpi.conflicts")} value={dash.review_backlog.pending_conflicts} tone={dash.review_backlog.pending_conflicts ? "bad" : "ok"} onClick={() => navigate("linking", { conflict: "true" })} />
                <Kpi label={t("kpi.unmatched")} value={unmatched} hint={T("ov.notLinkable")} tone={unmatched ? "bad" : "ok"} onClick={() => navigate("linking", { decision: "unmatched" })} />
                <Kpi label={t("kpi.silent")} value={silent} hint={T("ov.silentHint")} tone={silent ? "warn" : "ok"} onClick={() => navigate("watch")} />
                <Kpi label={t("kpi.startedLate")} value={sum("started_late")} tone="warn" onClick={() => navigate("schedule", { late: "1" })} />
                <Kpi label={t("kpi.finishedLate")} value={sum("finished_late")} tone="warn" onClick={() => navigate("schedule", { late: "1" })} />
                <Kpi label={t("kpi.overdue")} value={sum("due_not_started")} tone={sum("due_not_started") ? "bad" : "ok"} onClick={() => navigate("schedule", { status: "not_started" })} />
              </div>
              <Card title={t("card.sCurve")}>
                <SCurve rows={rows} asOf={asOf} planned={T("sc.planned")} actual={T("sc.actual")} today={T("sc.today")} />
              </Card>
              <Card title={t("card.kanban")} actions={
                <select aria-label={T("f.discipline")} value={disc} onChange={(e) => setDisc(e.target.value)}>
                  <option value="">{T("kb.allDisc")}</option>
                  {Object.keys(dash.by_discipline).map((d) => <option key={d} value={d}>{humanize(d)}</option>)}
                </select>}>
                <Kanban rows={disc ? rows.filter((r) => (r.discipline ?? "-") === disc) : rows} asOf={asOf} columns={STATUS}
                  onOpen={(r) => navigate("schedule", { q: r.code })} onMore={(status) => navigate("schedule", { status, ...(disc ? { discipline: disc } : {}) })} />
              </Card>
              <div className="grid-2">
                <Card title={t("card.plannedVsActual")}>
                  <CompareBars rows={plannedVsActual} a={{ label: t("kpi.plannedComplete"), tone: "muted" }} b={{ label: t("kpi.complete"), tone: "ok" }} />
                </Card>
                <Card title={t("card.statusByDiscipline")}>
                  <StackBars rows={byDisc} segments={STATUS} />
                </Card>
                <Card title={t("card.freshness")} actions={<a href="#/watch">{t("kpi.silent")} →</a>}>
                  <table className="table compact">
                    <thead><tr><th>{T("f.discipline")}</th><th>{T("agent.lastReport")}</th><th>{T("ov.daysSince")}</th><th>{t("kpi.silent")}</th></tr></thead>
                    <tbody>{Object.entries(dash.freshness).map(([g, f]) => (
                      <tr key={g}><td>{humanize(g)}</td><td>{f.last_report}</td><td className={f.days_since > 1 ? "warn-text" : ""}>{f.days_since}</td>
                        <td>{g === "mechanical" ? (dash.silent_activities_by_discipline.static_eq ?? 0) + (dash.silent_activities_by_discipline.rotating_eq ?? 0) : dash.silent_activities_by_discipline[g] ?? 0}</td></tr>
                    ))}</tbody>
                  </table>
                </Card>
                <Card title={t("card.delayCauses")} actions={<a href="#/analytics?tab=delays">{T("ov.delayIntel")} →</a>}>
                  <Bars data={Object.entries(delays.by_category)} tone="warn" />
                  <p className="muted small">{T("ov.holds", { n: delays.reports.length, asOf, rec: delays.recurring.map((r) => `${humanize(r.discipline)}/${humanize(r.category)} ×${r.reports}`).join(", ") || T("lk.none") })}</p>
                </Card>
              </div>
            </>
          );
        }}
      </Async>
    </>
  );
}
