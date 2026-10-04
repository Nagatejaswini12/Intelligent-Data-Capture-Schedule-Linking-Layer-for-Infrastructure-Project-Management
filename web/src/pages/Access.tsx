import { useState } from "react";
import { p2e } from "../api/p2e";
import { Async, Badge, Card, Empty, ErrorBox, Kpi, PageTitle } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { T, useT } from "../i18n";
import { fmtDateTime, humanize } from "../utils/format";

const TONE = { pending: "warn", approved: "ok", rejected: "bad" } as const;

// Admin: review sign-up requests (POST /access-requests from the public sign-up page). Non-admins get the API's 403.
export function AccessPage() {
  const { t } = useT();
  const state = useApi(() => p2e.accessRequests(), []);
  const [filter, setFilter] = useState<"" | "pending" | "approved" | "rejected">("pending");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const decide = async (id: number, status: "approved" | "rejected") => {
    setMsg(null);
    try {
      await p2e.decideAccess(id, status);
      setMsg({ ok: true, text: T("ac.done", { id, status: humanize(status) }) });
      state.reload();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  };
  return (
    <>
      <PageTitle title={t("ac.title")} subtitle={t("ac.sub")} />
      {msg && (msg.ok ? <div className="state state-ok">{msg.text}</div> : <ErrorBox error={msg.text} />)}
      <Async state={state} what={T("ac.loading")}>
        {(rows) => {
          const count = (s: string) => rows.filter((r) => r.status === s).length;
          const shown = filter ? rows.filter((r) => r.status === filter) : rows;
          return (
            <>
              <div className="kpis">
                {(["pending", "approved", "rejected"] as const).map((s) => (
                  <Kpi key={s} label={humanize(s)} value={count(s)} tone={TONE[s]} onClick={() => setFilter(s)} />
                ))}
              </div>
              <Card title={t("ac.title")} actions={
                <select aria-label={T("ac.status")} value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)}>
                  <option value="">{T("ac.all")}</option>
                  {(["pending", "approved", "rejected"] as const).map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
                </select>
              }>
                {shown.length === 0 ? <Empty>{T("ac.none")}</Empty> : (
                  <div className="scroll">
                    <table className="table compact">
                      <thead><tr><th>#</th><th>{T("ac.who")}</th><th>{T("ac.org")}</th><th>{T("ac.role")}</th><th>{T("ac.reason")}</th><th>{T("ac.when")}</th><th>{T("ac.status")}</th><th /></tr></thead>
                      <tbody>{shown.map((r) => (
                        <tr key={r.id}>
                          <td className="mono">{r.id}</td>
                          <td>{r.name}<div className="small muted"><a href={`mailto:${r.email}`}>{r.email}</a></div></td>
                          <td>{r.organisation}</td>
                          <td>{humanize(r.role_requested)}</td>
                          <td className="small">{r.reason || "—"}</td>
                          <td className="small">{fmtDateTime(r.created_at)}</td>
                          <td><Badge tone={TONE[r.status]}>{humanize(r.status)}</Badge></td>
                          <td className="nowrap">{r.status !== "approved" && <button type="button" className="btn btn-sm btn-primary" onClick={() => decide(r.id, "approved")}>{T("ac.approve")}</button>}
                            {" "}{r.status !== "rejected" && <button type="button" className="btn btn-sm" onClick={() => decide(r.id, "rejected")}>{T("ac.reject")}</button>}</td>
                        </tr>
                      ))}</tbody>
                    </table>
                  </div>
                )}
              </Card>
            </>
          );
        }}
      </Async>
    </>
  );
}
