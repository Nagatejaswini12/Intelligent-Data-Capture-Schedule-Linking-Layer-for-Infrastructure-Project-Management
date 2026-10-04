import { p2e } from "../api/p2e";
import { Async, Badge, Bars, Card, Empty, PageTitle } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useApp } from "../state";
import { useT } from "../i18n";
import { fmtDate, humanize } from "../utils/format";
import { href, navigate, useRoute } from "../utils/route";

const DISCIPLINES = ["civil", "piping", "electrical", "instrumentation", "hse", "static_eq", "rotating_eq"];

export function WatchPage() {
  const { project, asOf, live } = useApp();
  const { t } = useT();
  const { params } = useRoute();
  const f = { days: params.get("days") ?? "3", discipline: params.get("discipline") ?? "", area: params.get("area") ?? "" };
  const set = (k: string, v: string) => navigate("watch", { ...f, [k]: v });
  const state = useApi(() => p2e.silent(project.code, { as_of: asOf, days: Number(f.days), discipline: f.discipline || undefined, area: f.area || undefined }),
    [project.code, asOf, f.days, f.discipline, f.area, live]);
  return (
    <>
      <PageTitle icon="agent-watch" title={t("watch.title")} subtitle={t("watch.sub")}
        actions={<a className="btn" href={href("agent", { message: "What should I report today?", discipline: f.discipline })}>{t("watch.ask")}</a>} />
      <Card title={`Silent as of ${asOf}`} actions={<>
        <label className="check">no report in
          <select aria-label="Days" value={f.days} onChange={(e) => set("days", e.target.value)}>{[1, 2, 3, 5, 7, 14].map((d) => <option key={d} value={d}>{d} day{d > 1 ? "s" : ""}</option>)}</select>
        </label>
        <select aria-label="Discipline" value={f.discipline} onChange={(e) => set("discipline", e.target.value)}><option value="">All disciplines</option>{DISCIPLINES.map((d) => <option key={d} value={d}>{humanize(d)}</option>)}</select>
        <select aria-label="Area" value={f.area} onChange={(e) => set("area", e.target.value)}><option value="">All areas</option>{["A1", "A2", "A3", "A4"].map((a) => <option key={a}>{a}</option>)}</select>
      </>}>
        <Async state={state} what="Checking which activities went silent">
          {(w) => (
            <>
              <div className="grid-2">
                <div><h3>Why they are expected</h3><Bars data={Object.entries(w.counts)} tone="warn" /></div>
                <div className="note">
                  <strong>{w.items.length}</strong> activities expected to be active have no linked report in {w.days} day(s).
                  <p className="muted small">Expected = no actual finish, and started or past planned start. Never-reported first, then longest silence. Read-only: nothing in the schedule changes.</p>
                </div>
              </div>
              {w.items.length === 0 ? <Empty>Every expected activity was reported recently.</Empty> : (
                <div className="scroll tall">
                  <table className="table compact sticky">
                    <thead><tr><th>Activity</th><th>Discipline</th><th>Area</th><th>Planned</th><th>Actual start</th><th>Last report</th><th>Expected because</th></tr></thead>
                    <tbody>{w.items.map((i) => (
                      <tr key={i.plan_node_code}>
                        <td><a className="mono" href={href("schedule", { q: i.plan_node_code })}>{i.plan_node_code}</a><div className="small muted">{i.activity_name}</div></td>
                        <td>{humanize(i.discipline)}</td><td>{i.area ?? "—"}</td>
                        <td className="small">{fmtDate(i.planned_start)} → {fmtDate(i.planned_finish)}</td>
                        <td>{fmtDate(i.actual_start)}</td>
                        <td>{i.last_reported ? <>{fmtDate(i.last_reported)} <span className="muted">({i.days_silent} d)</span></> : <Badge tone="bad">never reported</Badge>}</td>
                        <td className="small">{i.expectation}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </Async>
      </Card>
    </>
  );
}
