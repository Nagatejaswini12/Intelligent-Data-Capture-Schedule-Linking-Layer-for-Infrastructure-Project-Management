import { useMemo, useState } from "react";
import { p2e, type ApplyOut, type DatasetRow, type TreeNode } from "../api/p2e";
import { Async, Badge, Card, Empty, ErrorBox, Modal, PageTitle } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useApp } from "../state";
import { useT, T } from "../i18n";
import { fmtDate, fmtNum, humanize, statusTone, variance } from "../utils/format";
import { href, navigate, useRoute } from "../utils/route";

function descendants(n: TreeNode, out = new Set<string>()): Set<string> {
  out.add(n.code);
  n.children.forEach((c) => descendants(c, out));
  return out;
}

function find(n: TreeNode, code: string): TreeNode | null {
  if (n.code === code) return n;
  for (const c of n.children) {
    const f = find(c, code);
    if (f) return f;
  }
  return null;
}

export function SchedulePage() {
  const { project, asOf, live } = useApp();
  const { t } = useT();
  const c = project.code;
  const { params } = useRoute();
  const filter = { discipline: params.get("discipline") ?? "", area: params.get("area") ?? "", status: params.get("status") ?? "",
    late: params.get("late") ?? "", q: params.get("q") ?? "", wbs: params.get("wbs") ?? "", conflict: params.get("conflict") ?? "" };
  const set = (k: string, v: string) => navigate("schedule", { ...filter, [k]: v });
  const state = useApi(async () => {
    const [data, tree, conflicts] = await Promise.all([p2e.dataset(c, asOf), p2e.hierarchy(c), p2e.links(c, { conflict: true, limit: 1000 })]);
    return { rows: data.items, tree, conflictCodes: new Set(conflicts.items.map((l) => l.conflict?.plan_node_code).filter(Boolean) as string[]) };
  }, [c, asOf, live]);
  const [apply, setApply] = useState(false);

  return (
    <>
      <PageTitle title={t("schedule.title")} subtitle={t("schedule.sub", { asOf })}
        actions={<>
          <button type="button" className="btn btn-primary" onClick={() => setApply(true)}>{T("sc.apply")}…</button>
          <button type="button" className="btn" onClick={() => p2e.exportCsv(c).catch((e) => alert(e.message))}>{T("sc.exportCsv")}</button>
          <button type="button" className="btn" onClick={() => p2e.exportXml(c, asOf).catch((e) => alert(e.message))}>{T("sc.exportXml")}</button>
        </>} />
      <Async state={state} what={T("sc.loading")}>
        {({ rows, tree, conflictCodes }) => (
          <div className="split split-tree">
            <Card title="WBS">
              <ul className="tree"><TreeItem node={tree} selected={filter.wbs} onPick={(code) => set("wbs", code === filter.wbs ? "" : code)} depth={0} /></ul>
            </Card>
            <ScheduleTable rows={rows} tree={tree} filter={filter} set={set} conflictCodes={conflictCodes} />
          </div>
        )}
      </Async>
      {apply && <ApplyDialog onClose={() => setApply(false)} />}
    </>
  );
}

function TreeItem({ node, selected, onPick, depth }: { node: TreeNode; selected: string; onPick: (c: string) => void; depth: number }) {
  const [open, setOpen] = useState(depth < 2);
  const kids = node.children.filter((k) => k.node_type !== "activity");
  return (
    <li>
      <div className={`tree-row ${selected === node.code ? "selected" : ""}`}>
        {kids.length > 0 ? <button type="button" className="tree-toggle" onClick={() => setOpen(!open)} aria-label={open ? T("sc.collapse") : T("sc.expand")}>{open ? "▾" : "▸"}</button> : <span className="tree-toggle" />}
        <button type="button" className="tree-label" onClick={() => onPick(node.code)} title={node.code}>L{node.level} {node.name}</button>
      </div>
      {open && kids.length > 0 && <ul>{kids.map((k) => <TreeItem key={k.code} node={k} selected={selected} onPick={onPick} depth={depth + 1} />)}</ul>}
    </li>
  );
}

function ScheduleTable({ rows, tree, filter, set, conflictCodes }: { rows: DatasetRow[]; tree: TreeNode; filter: Record<string, string>; set: (k: string, v: string) => void; conflictCodes: Set<string> }) {
  const { asOf } = useApp();
  const under = useMemo(() => (filter.wbs ? descendants(find(tree, filter.wbs) ?? tree) : null), [tree, filter.wbs]);
  const disciplines = [...new Set(rows.map((r) => r.discipline ?? ""))].filter(Boolean).sort();
  const areas = [...new Set(rows.map((r) => r.area ?? ""))].filter(Boolean).sort();
  const q = filter.q.toLowerCase();
  const shown = rows.filter((r) => (!under || under.has(r.code))
    && (!filter.discipline || r.discipline === filter.discipline) && (!filter.area || r.area === filter.area)
    && (!filter.status || r.status === filter.status)
    && (!filter.late || (r.start_variance_days ?? 0) > 0 || (r.finish_variance_days ?? 0) > 0 || (r.status === "not_started" && r.planned_start < asOf))
    && (!filter.conflict || conflictCodes.has(r.code))
    && (!q || r.code.toLowerCase().includes(q) || r.name.toLowerCase().includes(q)));
  return (
    <Card title={T("sc.activities", { n: shown.length, total: rows.length })} actions={<>
      <input placeholder={T("sc.search")} value={filter.q} onChange={(e) => set("q", e.target.value)} aria-label={T("sc.search")} />
      <select aria-label={T("f.discipline")} value={filter.discipline} onChange={(e) => set("discipline", e.target.value)}><option value="">{T("common.allDisc")}</option>{disciplines.map((d) => <option key={d} value={d}>{humanize(d)}</option>)}</select>
      <select aria-label={T("f.area")} value={filter.area} onChange={(e) => set("area", e.target.value)}><option value="">{T("common.allAreas")}</option>{areas.map((a) => <option key={a}>{a}</option>)}</select>
      <select aria-label={T("f.status")} value={filter.status} onChange={(e) => set("status", e.target.value)}><option value="">{T("sc.anyStatus")}</option>{["completed", "in_progress", "not_started"].map((s) => <option key={s} value={s}>{humanize(s)}</option>)}</select>
      <label className="check"><input type="checkbox" checked={!!filter.late} onChange={(e) => set("late", e.target.checked ? "1" : "")} />{T("sc.late")}</label>
      <label className="check"><input type="checkbox" checked={!!filter.conflict} onChange={(e) => set("conflict", e.target.checked ? "1" : "")} />{T("sc.conflict")}</label>
    </>}>
      {shown.length === 0 ? <Empty>{T("sc.noMatch")}</Empty> : (
        <div className="scroll tall">
          <table className="table compact sticky">
            <thead><tr><th>{T("f.activity")}</th><th>{T("sc.planned")}</th><th>{T("sc.actual")}</th><th>%</th><th>{T("f.status")}</th><th>{T("sc.startVar")}</th><th>{T("sc.finishVar")}</th><th>{T("sc.reports")}</th><th>{T("an.tDelays")}</th></tr></thead>
            <tbody>{shown.map((r) => (
              <tr key={r.code}>
                <td><span className="mono">{r.code}</span>{conflictCodes.has(r.code) && <Badge tone="bad">{T("sc.conflict")}</Badge>}<div className="small muted">{r.name}</div></td>
                <td className="small">{fmtDate(r.planned_start)} → {fmtDate(r.planned_finish)}</td>
                <td className="small">{fmtDate(r.actual_start)} → {fmtDate(r.actual_finish)}</td>
                <td>{r.percent_complete != null ? `${fmtNum(r.percent_complete, 1)}%` : "—"}</td>
                <td><Badge tone={statusTone(r.status)}>{humanize(r.status)}</Badge></td>
                <td className={(r.start_variance_days ?? 0) > 0 ? "warn-text" : ""}>{variance(r.start_variance_days)}</td>
                <td className={(r.finish_variance_days ?? 0) > 0 ? "warn-text" : ""}>{variance(r.finish_variance_days)}</td>
                <td>{r.reports ? <a href={href("linking", { decision: "", node: r.code })} title={`last ${fmtDate(r.last_reported)}`}>{r.reports} · {r.sources} src</a> : "—"}</td>
                <td className="small">{r.delay_categories || "—"}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function ApplyDialog({ onClose }: { onClose: () => void }) {
  const { project, asOf } = useApp();
  const [preview, setPreview] = useState<ApplyOut | null>(null);
  const [done, setDone] = useState<ApplyOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const go = async (dry: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const r = await p2e.apply(project.code, asOf, dry);
      dry ? setPreview(r) : setDone(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const r = done ?? preview;
  return (
    <Modal title={T("sc.applyTitle", { asOf })} onClose={onClose}>
      <p className="muted">{T("sc.applyHint")}</p>
      {!preview && !done && <button type="button" className="btn btn-primary" disabled={busy} onClick={() => go(true)}>{busy ? "Checking…" : "Preview (dry run)"}</button>}
      {error && <ErrorBox error={error} />}
      {r && (
        <>
          <p>{done ? <Badge tone="ok">{T("sc.applied")}</Badge> : <Badge tone="info">{T("sc.preview")}</Badge>} {T("sc.applySummary", { n: done ? done.applied.length : r.would_apply.length, b: r.blocked.length, u: r.unchanged })}</p>
          <div className="scroll">
            <table className="table compact">
              <thead><tr><th>{T("f.activity")}</th><th>{T("sc.changes")}</th></tr></thead>
              <tbody>{(done ? done.applied.map((e) => ({ code: e.plan_node_code, changes: e.changes })) : r.would_apply.map((p) => ({ code: p.plan_node_code, changes: p.changes }))).map((x) => (
                <tr key={x.code}><td className="mono">{x.code}</td><td className="small">{Object.entries(x.changes).map(([f, [a, b]]) => `${humanize(f)}: ${a ?? "—"} → ${b}`).join(" · ")}</td></tr>
              ))}</tbody>
            </table>
          </div>
          {!done && <button type="button" className="btn btn-primary" disabled={busy || r.would_apply.length === 0} onClick={() => go(false)}>Apply {r.would_apply.length} activities</button>}
          {done && <p><a href="#/audit">{T("nav.audit")} →</a> · <a href="#/linking?tab=blocked">{T("lk.tabBlocked")} →</a></p>}
        </>
      )}
      {r && r.would_apply.length === 0 && !done && <Empty>{T("sc.nothing")}</Empty>}
    </Modal>
  );
}
