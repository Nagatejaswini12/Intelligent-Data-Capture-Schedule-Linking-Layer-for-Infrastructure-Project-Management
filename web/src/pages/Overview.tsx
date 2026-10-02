import { p2e } from "../api/p2e";
import { Async, Bars, Card, CompareBars, Flow, Kpi, PageTitle, StackBars } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useApp } from "../state";
import { pct } from "../utils/format";
import { navigate } from "../utils/route";

const STATUS = [
  { key: "completed", label: "Completed", tone: "ok" as const },
  { key: "in_progress", label: "In progress", tone: "info" as const },
  { key: "not_started", label: "Not started", tone: "muted" as const },
];

export function OverviewPage() {
  const { project, asOf, live } = useApp();
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
      <PageTitle title="Project control overview" subtitle={`Recorded history as of ${asOf}. Every figure comes from the backend.`} />
      <Async state={state} what="Loading project status">
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
                { label: "Field execution", value: `${docs} reports`, tone: "info" },
                { label: "AI understanding", value: `${events} events`, tone: "ai" },
                { label: "Schedule linking", value: `${matched} linked`, tone: "ai" },
                { label: "Human validation", value: `${review} in review`, tone: review ? "warn" : "ok" },
                { label: "Verified progress", value: `${sum("completed") + sum("in_progress")} activities with actuals`, tone: "ok" },
                { label: "Project intelligence", value: "Q&A + analytics", tone: "info" },
              ]} />
              <div className="kpis">
                <Kpi label="Actually complete" value={`${sum("completed")} / ${total}`} hint={`${pct(sum("completed"), total)} of activities`} tone="ok" onClick={() => navigate("schedule", { status: "completed" })} />
                <Kpi label="Planned complete by as-of" value={`${plannedDone} / ${total}`} hint={`${pct(plannedDone, total)} per baseline`} tone="info" />
                <Kpi label="In progress" value={sum("in_progress")} tone="info" onClick={() => navigate("schedule", { status: "in_progress" })} />
                <Kpi label="Needs planner review" value={dash.review_backlog.pending_events} hint={`${dash.review_backlog.blocked_activities} activities blocked by a rule`} tone={dash.review_backlog.pending_events ? "warn" : "ok"} onClick={() => navigate("linking")} />
                <Kpi label="Cross-source conflicts" value={dash.review_backlog.pending_conflicts} tone={dash.review_backlog.pending_conflicts ? "bad" : "ok"} onClick={() => navigate("linking", { conflict: "true" })} />
                <Kpi label="Unmatched reports" value={unmatched} hint="not safely linkable" tone={unmatched ? "bad" : "ok"} onClick={() => navigate("linking", { decision: "unmatched" })} />
                <Kpi label="Silent activities" value={silent} hint="expected active, no recent report" tone={silent ? "warn" : "ok"} onClick={() => navigate("watch")} />
                <Kpi label="Started late" value={sum("started_late")} tone="warn" onClick={() => navigate("schedule", { late: "1" })} />
                <Kpi label="Finished late" value={sum("finished_late")} tone="warn" onClick={() => navigate("schedule", { late: "1" })} />
                <Kpi label="Overdue, not started" value={sum("due_not_started")} tone={sum("due_not_started") ? "bad" : "ok"} onClick={() => navigate("schedule", { status: "not_started" })} />
              </div>
              <div className="grid-2">
                <Card title="Planned vs actual completion by discipline">
                  <CompareBars rows={plannedVsActual} a={{ label: "Planned complete by as-of", tone: "muted" }} b={{ label: "Actually complete", tone: "ok" }} />
                </Card>
                <Card title="Status by discipline">
                  <StackBars rows={byDisc} segments={STATUS} />
                </Card>
                <Card title="Reporting freshness (daily progress reports)" actions={<a href="#/watch">Silent activities →</a>}>
                  <table className="table compact">
                    <thead><tr><th>Discipline</th><th>Last report</th><th>Days since</th><th>Silent activities</th></tr></thead>
                    <tbody>{Object.entries(dash.freshness).map(([g, f]) => (
                      <tr key={g}><td>{g}</td><td>{f.last_report}</td><td className={f.days_since > 1 ? "warn-text" : ""}>{f.days_since}</td>
                        <td>{g === "mechanical" ? (dash.silent_activities_by_discipline.static_eq ?? 0) + (dash.silent_activities_by_discipline.rotating_eq ?? 0) : dash.silent_activities_by_discipline[g] ?? 0}</td></tr>
                    ))}</tbody>
                  </table>
                </Card>
                <Card title="Reported delay causes" actions={<a href="#/analytics">Delay intelligence →</a>}>
                  <Bars data={Object.entries(delays.by_category)} tone="warn" />
                  <p className="muted small">{delays.reports.length} hold reports up to {asOf}; recurring: {delays.recurring.map((r) => `${r.discipline}/${r.category} ×${r.reports}`).join(", ") || "none"}.</p>
                </Card>
              </div>
            </>
          );
        }}
      </Async>
    </>
  );
}
