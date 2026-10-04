import { useState } from "react";
import { p2e } from "../api/p2e";
import { EvidenceModal } from "../components/Evidence";
import { Async, Badge, Card, Empty, ErrorBox, PageTitle } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useApp } from "../state";
import { useT } from "../i18n";
import { fmtDateTime, fmtNum, humanize } from "../utils/format";
import { href, navigate, useRoute } from "../utils/route";

const ACTION_TONE: Record<string, "ai" | "warn" | "muted" | "info"> = { apply: "ai", override: "warn", undo: "muted", create_activity: "info" };

export function AuditPage() {
  const { project, live } = useApp();
  const { t } = useT();
  const { params } = useRoute();
  const f = { node: params.get("node") ?? "", action: params.get("action") ?? "" };
  const state = useApi(() => p2e.audit(project.code, { plan_node_code: f.node || undefined, action: f.action || undefined, limit: 1000 }), [project.code, f.node, f.action, live]);
  const [evidence, setEvidence] = useState<number | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const undo = async (id: number) => {
    setMsg(null);
    try {
      const e = await p2e.undo(project.code, id);
      setMsg({ ok: true, text: `Entry ${id} undone by compensating entry ${e.id}.` });
      state.reload();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  };
  return (
    <>
      <PageTitle title={t("audit.title")} subtitle={t("audit.sub")} />
      {msg && (msg.ok ? <div className="state state-ok">{msg.text}</div> : <ErrorBox error={msg.text} />)}
      <Card title="Schedule changes" actions={<>
        <input placeholder="Activity code" value={f.node} onChange={(e) => navigate("audit", { ...f, node: e.target.value })} aria-label="Activity code" />
        <select aria-label="Action" value={f.action} onChange={(e) => navigate("audit", { ...f, action: e.target.value })}>
          <option value="">All actions</option><option value="apply">apply</option><option value="override">override</option><option value="undo">undo</option><option value="create_activity">create activity</option>
        </select>
      </>}>
        <Async state={state} what="Loading the audit trail">
          {(page) => page.items.length === 0 ? <Empty>No schedule change recorded yet. Apply verified actuals from the Schedule page.</Empty> : (
            <div className="scroll tall">
              <table className="table compact sticky">
                <thead><tr><th>#</th><th>When</th><th>Action</th><th>Activity</th><th>Before → after</th><th>Actor · rule</th><th>Confidence</th><th>Source reports</th><th>Undo</th></tr></thead>
                <tbody>{[...page.items].reverse().map((e) => (
                  <tr key={e.id} className={e.undone_by ? "struck" : ""}>
                    <td className="mono">{e.id}</td>
                    <td className="small">{fmtDateTime(e.created_at)}</td>
                    <td><Badge tone={ACTION_TONE[e.action] ?? "muted"}>{humanize(e.action)}</Badge>{e.reverts_id && <span className="small muted"> reverts #{e.reverts_id}</span>}</td>
                    <td><a className="mono" href={href("schedule", { q: e.plan_node_code })}>{e.plan_node_code}</a></td>
                    <td className="small">{Object.entries(e.changes).map(([k, [a, b]]) => <div key={k}>{humanize(k)}: {String(a ?? "—")} → <strong>{String(b ?? "—")}</strong></div>)}
                      {e.warnings.map((w, i) => <div key={i} className="warn-text">{w}</div>)}</td>
                    <td className="small">{e.actor}<div className="muted">{humanize(e.rule)}</div></td>
                    <td>{fmtNum(e.confidence)}</td>
                    <td className="small">{e.evidence_event_ids.map((id) => <button type="button" key={id} className="linkish" onClick={() => setEvidence(id)}>#{id}</button>)}</td>
                    <td>{e.undone_by ? <Badge>undone by #{e.undone_by}</Badge> : (e.action === "apply" || e.action === "override") ? <button type="button" className="btn btn-sm" onClick={() => undo(e.id)}>Undo</button> : "—"}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </Async>
      </Card>
      {evidence !== null && <EvidenceModal eventId={evidence} onClose={() => setEvidence(null)} />}
    </>
  );
}
