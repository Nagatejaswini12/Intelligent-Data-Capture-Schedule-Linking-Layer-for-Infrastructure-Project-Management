import { useState } from "react";
import { p2e } from "../api/p2e";
import { Async, Badge, Bars, Card, Kpi, PageTitle } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useApp } from "../state";
import { useT } from "../i18n";
import { fmtDate, humanize } from "../utils/format";
import { href } from "../utils/route";

// Placeholders for OIL to replace with its own figures; every rupee/token value on this page is an estimate from them.
const DEFAULTS = { manual_minutes_per_item: 5, planner_inr_per_hour: 750, manual_lag_days: 3, tokens_per_llm_call: 1500, inr_per_1k_tokens: 0.25 };
const LABELS: Record<keyof typeof DEFAULTS, string> = {   // i18n keys
  manual_minutes_per_item: "roi.a.minutes", planner_inr_per_hour: "roi.a.rate", manual_lag_days: "roi.a.lag",
  tokens_per_llm_call: "roi.a.tokens", inr_per_1k_tokens: "roi.a.price",
};
const inr = (v: number) => `₹${Math.round(v).toLocaleString("en-IN")}`;

export function RoiPage() {
  const { project, asOf, live } = useApp();
  const { t } = useT();
  const [draft, setDraft] = useState(DEFAULTS);
  const [applied, setApplied] = useState(DEFAULTS);
  const state = useApi(async () => {
    const [eff, silent] = await Promise.all([p2e.efficiency(project.code, { as_of: asOf, ...applied }),
      p2e.silent(project.code, { as_of: asOf, days: 3 })]);
    return { eff, silent };
  }, [project.code, asOf, live, applied]);

  return (
    <>
      <PageTitle title={t("roi.title")} subtitle={t("roi.sub", { asOf })} />
      <Async state={state} what="Computing efficiency">
        {({ eff, silent }) => {
          const alerts = silent.items;
          return (
            <>
              <div className="kpis">
                <Kpi label={t("roi.auto")} value={eff.auto_link_rate != null ? `${Math.round(eff.auto_link_rate * 100)}%` : "—"} hint={t("roi.autoHint", { a: eff.tiers.automatic, n: eff.items })} tone="ok" />
                <Kpi label={t("roi.tokens")} value={eff.tokens.ours_per_1000_reports.toLocaleString("en-IN")} hint={t("roi.tokensHint", { n: eff.tokens.llm_for_everything_per_1000_reports.toLocaleString("en-IN") })} tone="ai" />
                <Kpi label={t("roi.cost")} value={inr(eff.inr_per_1000_reports.ours)} hint={t("roi.costHint", { n: inr(eff.inr_per_1000_reports.llm_for_everything) })} tone="ai" />
                <Kpi label={t("roi.saved")} value={`${eff.planner_hours_saved} h`} hint={t("roi.savedHint", { n: inr(eff.planner_inr_saved) })} tone="ok" />
                <Kpi label={t("roi.speed")} value={eff.processing_seconds_median != null ? `${eff.processing_seconds_median} s` : "—"} hint={t("roi.speedHint", { n: eff.manual_lag_days })} tone="info" />
                <Kpi label={t("roi.alerts")} value={alerts.length} hint={t("roi.alertsHint")} tone={alerts.length ? "warn" : "ok"} onClick={() => { location.href = href("watch"); }} />
              </div>
              <div className="grid-2">
                <Card title={t("roi.who")}>
                  <Bars data={Object.entries(eff.tiers).map(([k, v]) => [humanize(k), v] as [string, number])} />
                  <p className="muted small">{t("roi.whoNote")} LLM: {eff.llm_calls} ({eff.llm_call_ratio != null ? `${Math.round(eff.llm_call_ratio * 100)}%` : "—"}).</p>
                  <h4>{t("roi.byEvidence")}</h4>
                  <Bars data={Object.entries(eff.automatic_by_evidence).map(([k, v]) => [humanize(k), v] as [string, number])} tone="ok" />
                </Card>
                <Card title={t("roi.assumptions")}>
                  <form className="stack" onSubmit={(e) => { e.preventDefault(); setApplied(draft); }}>
                    {(Object.keys(DEFAULTS) as (keyof typeof DEFAULTS)[]).map((k) => (
                      <label key={k} className="stacked small">{t(LABELS[k])}
                        <input type="number" min={0} step="any" value={draft[k]} onChange={(e) => setDraft({ ...draft, [k]: Number(e.target.value) })} />
                      </label>
                    ))}
                    <button className="btn btn-primary">{t("roi.recalc")}</button>
                  </form>
                </Card>
              </div>
              <Card title={<>{t("roi.shadow")} <Badge tone={eff.shadow.enabled ? "warn" : "muted"}>{eff.shadow.enabled ? "ON" : "off"}</Badge></>}
                actions={<button type="button" className="btn btn-sm" onClick={() => p2e.setShadow(project.code, !eff.shadow.enabled).then(state.reload, (e) => alert(e.message))}>
                  {eff.shadow.enabled ? t("roi.off") : t("roi.on")}</button>}>
                <p>{t("roi.shadowText", { n: eff.shadow.would_update, b: eff.shadow.blocked_for_review })}</p>
              </Card>
              <Card title={t("roi.alertTable", { n: alerts.length })}>
                {alerts.length === 0 ? <p className="muted">{t("roi.allGood")}</p> : (
                  <table className="table compact">
                    <thead><tr><th>Activity</th><th>Why expected</th><th>Planned</th><th>Last report</th></tr></thead>
                    <tbody>{alerts.slice(0, 25).map((i) => (
                      <tr key={i.plan_node_code}><td><span className="mono">{i.plan_node_code}</span> {i.activity_name}</td>
                        <td><Badge tone={i.expectation.startsWith("past planned finish") ? "bad" : "warn"}>{i.expectation}</Badge></td>
                        <td className="small">{fmtDate(i.planned_start)} → {fmtDate(i.planned_finish)}</td>
                        <td>{i.last_reported ? fmtDate(i.last_reported) : <Badge tone="bad">never</Badge>}</td></tr>
                    ))}</tbody>
                  </table>
                )}
              </Card>
            </>
          );
        }}
      </Async>
    </>
  );
}
