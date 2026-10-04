import { download } from "../api/client";
import { p2e } from "../api/p2e";
import { Async, Bars, Card, CompareBars, Kpi, PageTitle, StackBars } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useApp } from "../state";
import { useT } from "../i18n";
import { fmtNum, humanize } from "../utils/format";
import { href, navigate, useRoute } from "../utils/route";

const STATUS = [
  { key: "completed", label: "Completed", tone: "ok" as const },
  { key: "in_progress", label: "In progress", tone: "info" as const },
  { key: "not_started", label: "Not started", tone: "muted" as const },
];
const TABS = [["progress", "Progress"], ["productivity", "Productivity"], ["delays", "Delays"], ["health", "Schedule health"]];

export function AnalyticsPage() {
  const { project, asOf, live } = useApp();
  const { t } = useT();
  const c = project.code;
  const { params } = useRoute();
  const tab = params.get("tab") ?? "progress";
  const state = useApi(async () => {
    const [dash, prod, delays] = await Promise.all([p2e.dashboard(c, asOf), p2e.productivity(c, asOf), p2e.delays(c, asOf)]);
    return { dash, prod, delays };
  }, [c, asOf, live]);
  return (
    <>
      <PageTitle title={t("analytics.title")} subtitle={t("analytics.sub", { asOf })}
        actions={<>
          <button type="button" className="btn btn-primary" onClick={() => p2e.pmReport(c, asOf, "daily").catch((e) => alert(e.message))}>{t("analytics.daily")}</button>
          <button type="button" className="btn" onClick={() => p2e.pmReport(c, asOf, "weekly").catch((e) => alert(e.message))}>{t("analytics.weekly")}</button>
          <button type="button" className="btn" onClick={() => download(`/api/v1/projects/${c}/analytics/dataset.csv`, `${c}-actual-progress.csv`, { as_of: asOf }).catch((e) => alert(e.message))}>{t("analytics.dataset")}</button>
        </>} />
      <div className="tabs" role="tablist">{TABS.map(([k, l]) => <a key={k} role="tab" aria-selected={tab === k} className={tab === k ? "active" : ""} href={href("analytics", { tab: k })}>{l}</a>)}</div>
      <Async state={state} what="Computing analytics">
        {({ dash, prod, delays }) => {
          const disc = Object.entries(dash.by_discipline);
          const sum = (k: keyof (typeof dash.by_discipline)[string]) => disc.reduce((a, [, v]) => a + ((v[k] as number) ?? 0), 0);
          if (tab === "productivity") return (
            <div className="grid-2">
              <Card title="Actual vs planned duration by activity type (completed activities)">
                <CompareBars rows={Object.entries(prod.durations).map(([t, d]) => [t, d.mean_planned_days, d.mean_actual_days] as [string, number, number])}
                  a={{ label: "Planned days (mean)", tone: "muted" }} b={{ label: "Actual days (mean)", tone: "ai" }} />
              </Card>
              <Card title="Duration ratio (actual ÷ planned)">
                <table className="table compact"><thead><tr><th>Activity type</th><th>Completed</th><th>Mean actual</th><th>Mean planned</th><th>Ratio</th></tr></thead>
                  <tbody>{Object.entries(prod.durations).map(([t, d]) => (
                    <tr key={t}><td>{t}</td><td>{d.completed}</td><td>{fmtNum(d.mean_actual_days)} d</td><td>{fmtNum(d.mean_planned_days)} d</td>
                      <td className={d.mean_ratio > 1 ? "warn-text" : "ok-text"}>{fmtNum(d.mean_ratio, 3)}</td></tr>))}</tbody></table>
              </Card>
              <Card title="Reported quantity per day (most complete single source per activity)" className="span-2">
                <table className="table compact"><thead><tr><th>Activity type</th><th>Unit</th><th>Quantity</th><th>Reporting days</th><th>Per day</th></tr></thead>
                  <tbody>{Object.entries(prod.rates).flatMap(([t, units]) => Object.entries(units).map(([u, r]) => (
                    <tr key={`${t}-${u}`}><td>{t}</td><td>{u}</td><td>{fmtNum(r.quantity)}</td><td>{r.days}</td><td><strong>{fmtNum(r.per_day)}</strong> {u}/day</td></tr>)))}</tbody></table>
              </Card>
            </div>
          );
          if (tab === "delays") return (
            <div className="grid-2">
              <Card title="Delay categories"><Bars data={Object.entries(delays.by_category)} tone="warn" /></Card>
              <Card title="Recurring causes (≥ 2 reports in a discipline)">
                {delays.recurring.length ? <Bars data={delays.recurring.map((r) => [`${r.discipline} · ${r.category}`, r.reports] as [string, number])} tone="bad" /> : <p className="muted">No cause has recurred yet.</p>}
              </Card>
              <Card title="By discipline"><StackBars rows={Object.entries(delays.by_discipline)} segments={Object.keys(delays.by_category).map((k, i) => ({ key: k, label: k, tone: (["warn", "bad", "info", "ai", "muted", "ok"] as const)[i % 6] }))} /></Card>
              <Card title="By area"><StackBars rows={Object.entries(delays.by_area)} segments={Object.keys(delays.by_category).map((k, i) => ({ key: k, label: k, tone: (["warn", "bad", "info", "ai", "muted", "ok"] as const)[i % 6] }))} /></Card>
              <Card title="Hold reports (field evidence)" className="span-2">
                <table className="table compact"><thead><tr><th>Date</th><th>Discipline</th><th>Activity</th><th>Category</th><th>Reason</th><th>Report</th></tr></thead>
                  <tbody>{delays.reports.map((r) => (
                    <tr key={r.event_id}><td>{r.date}</td><td>{humanize(r.discipline)}</td><td>{r.activity ? <a className="mono" href={href("schedule", { q: r.activity })}>{r.activity}</a> : "—"}</td>
                      <td>{r.category}</td><td>{r.reason}</td><td className="source-cell"><a href={href("linking", { event: r.event_id, decision: "" })}>{r.source_text}</a></td></tr>))}</tbody></table>
              </Card>
            </div>
          );
          if (tab === "health") return (
            <>
              <div className="kpis">
                <Kpi label={t("kpi.startedLate")} value={sum("started_late")} tone="warn" onClick={() => navigate("schedule", { late: "1" })} />
                <Kpi label={t("kpi.finishedLate")} value={sum("finished_late")} tone="warn" onClick={() => navigate("schedule", { late: "1" })} />
                <Kpi label={t("kpi.overdue")} value={sum("due_not_started")} tone="bad" onClick={() => navigate("schedule", { status: "not_started" })} />
                <Kpi label="Pending review" value={dash.review_backlog.pending_events} tone="warn" onClick={() => navigate("linking")} />
                <Kpi label="Blocked actuals" value={dash.review_backlog.blocked_activities} tone="warn" onClick={() => navigate("linking", { tab: "blocked" })} />
                <Kpi label={t("kpi.silent")} value={Object.values(dash.silent_activities_by_discipline).reduce((a, b) => a + b, 0)} tone="warn" onClick={() => navigate("watch")} />
              </div>
              <div className="grid-2">
                <Card title="Late starts / late finishes by discipline">
                  <CompareBars rows={disc.map(([d, v]) => [d, v.started_late ?? 0, v.finished_late ?? 0] as [string, number, number])} a={{ label: "Started late", tone: "warn" }} b={{ label: "Finished late", tone: "bad" }} />
                </Card>
                <Card title="Overdue not started and silent activities by discipline">
                  <CompareBars rows={disc.map(([d, v]) => [d, v.due_not_started ?? 0, dash.silent_activities_by_discipline[d] ?? 0] as [string, number, number])} a={{ label: "Overdue, not started", tone: "bad" }} b={{ label: "Silent", tone: "warn" }} />
                </Card>
              </div>
            </>
          );
          return (
            <div className="grid-2">
              <Card title="Progress by discipline"><StackBars rows={disc.map(([d, v]) => [d, v as unknown as Record<string, number>] as [string, Record<string, number>])} segments={STATUS} /></Card>
              <Card title="Progress by area"><StackBars rows={Object.entries(dash.by_area).map(([d, v]) => [d, v as unknown as Record<string, number>] as [string, Record<string, number>])} segments={STATUS} /></Card>
              <Card title="Completion share by discipline" className="span-2">
                <Bars data={disc.map(([d, v]) => [d, v.activities ? Math.round((100 * (v.completed ?? 0)) / v.activities) : 0] as [string, number])} tone="ok" format={(v) => `${v}%`} />
              </Card>
            </div>
          );
        }}
      </Async>
    </>
  );
}
