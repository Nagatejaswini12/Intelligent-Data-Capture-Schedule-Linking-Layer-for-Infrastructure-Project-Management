import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError, apiKey } from "./api/client";
import { p2e, type Project } from "./api/p2e";
import { Badge, ErrorBox, Loading } from "./components/ui";
import { useStream } from "./hooks/useStream";
import { AgentPage } from "./pages/Agent";
import { AnalyticsPage } from "./pages/Analytics";
import { AuditPage } from "./pages/Audit";
import { DemoPage } from "./pages/Demo";
import { LinkingPage } from "./pages/Linking";
import { MemoryPage } from "./pages/Memory";
import { OverviewPage } from "./pages/Overview";
import { ReportsPage } from "./pages/Reports";
import { SchedulePage } from "./pages/Schedule";
import { WatchPage } from "./pages/Watch";
import { AppContext } from "./state";
import { todayIso } from "./utils/format";
import { href, useRoute } from "./utils/route";

const NAV: { group: string; items: { page: string; label: string; icon: string }[] }[] = [
  { group: "Operate", items: [
    { page: "overview", label: "Overview", icon: "◎" },
    { page: "reports", label: "Field Reports", icon: "▤" },
    { page: "linking", label: "Activity Linking", icon: "⇄" },
    { page: "agent", label: "Time Agent", icon: "✎" },
  ] },
  { group: "Plan", items: [
    { page: "schedule", label: "Schedule", icon: "▦" },
    { page: "watch", label: "Silent Activity Watch", icon: "◔" },
    { page: "audit", label: "Audit Trail", icon: "☰" },
  ] },
  { group: "Intelligence", items: [
    { page: "analytics", label: "Analytics", icon: "▥" },
    { page: "memory", label: "Project Memory", icon: "❖" },
  ] },
  { group: "Present", items: [{ page: "demo", label: "Demo Flow", icon: "▶" }] },
];

const PAGES: Record<string, () => ReactNode> = {
  overview: () => <OverviewPage />, reports: () => <ReportsPage />, linking: () => <LinkingPage />, agent: () => <AgentPage />,
  schedule: () => <SchedulePage />, watch: () => <WatchPage />, audit: () => <AuditPage />, analytics: () => <AnalyticsPage />,
  memory: () => <MemoryPage />, demo: () => <DemoPage />,
};

function loadAsOf(): string {
  try {
    return localStorage.getItem("p2e.asOf") || todayIso();
  } catch {
    return todayIso();
  }
}

export function App() {
  const [signedIn, setSignedIn] = useState(() => !!apiKey.get());
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [projectCode, setProjectCode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asOf, setAsOfState] = useState(loadAsOf);
  const [theme, setTheme] = useState(() => (typeof localStorage !== "undefined" && localStorage.getItem("p2e.theme")) || "dark");
  const route = useRoute();

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("p2e.theme", theme); } catch { /* ignore */ }
  }, [theme]);

  useEffect(() => {
    p2e.projects().then((ps) => { setProjects(ps); setProjectCode((c) => c ?? ps[0]?.code ?? null); }, (e: Error) => setError(e.message));
  }, []);

  const project = projects?.find((p) => p.code === projectCode) ?? null;
  const { snapshot, connected } = useStream(project?.code ?? null, signedIn);
  const live = useMemo(() => (snapshot ? JSON.stringify(snapshot) : ""), [snapshot]);

  const setAsOf = (d: string) => {
    setAsOfState(d);
    try { localStorage.setItem("p2e.asOf", d); } catch { /* ignore */ }
  };

  if (error) return <div className="center"><ErrorBox error={error} onRetry={() => window.location.reload()} /></div>;
  if (!projects) return <div className="center"><Loading what="Connecting to the P2E Bridge API" /></div>;
  if (!project) return <div className="center"><ErrorBox error="No project imported yet. Run scripts/phase1/init_database.py." /></div>;
  if (!signedIn) return <SignIn project={project} onDone={() => setSignedIn(true)} />;

  const page = PAGES[route.page] ? route.page : "overview";
  return (
    <AppContext.Provider value={{ project, asOf, setAsOf, live, snapshot }}>
      <div className="shell">
        <aside className="sidebar">
          <div className="brand"><span className="brand-mark">P2E</span><span><strong>Bridge</strong><small>Project control · SIH26122</small></span></div>
          <nav aria-label="Main">
            {NAV.map((g) => (
              <div key={g.group} className="nav-group">
                <span className="nav-title">{g.group}</span>
                {g.items.map((it) => (
                  <a key={it.page} href={href(it.page)} className={page === it.page ? "active" : ""} aria-current={page === it.page ? "page" : undefined}>
                    <span className="nav-icon" aria-hidden>{it.icon}</span>{it.label}
                    {it.page === "linking" && snapshot?.pending_review ? <span className="nav-count">{snapshot.pending_review}</span> : null}
                  </a>
                ))}
              </div>
            ))}
          </nav>
          <p className="sidebar-foot">Field execution → AI understanding → schedule linking → human validation → verified progress → project intelligence</p>
        </aside>
        <div className="main">
          <header className="topbar">
            <div className="topbar-project">
              <strong>{project.code}</strong><span className="muted">{project.name}</span>
            </div>
            <label className="asof">As of
              <input type="date" value={asOf} onChange={(e) => e.target.value && setAsOf(e.target.value)} />
            </label>
            <Badge tone={connected ? "ok" : "muted"} title="Live updates from the backend event stream">{connected ? "● live" : "○ offline"}</Badge>
            <button type="button" className="btn btn-sm" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label="Toggle colour theme">{theme === "dark" ? "☀" : "☾"}</button>
            <button type="button" className="btn btn-sm" onClick={() => { apiKey.clear(); setSignedIn(false); }}>Sign out</button>
          </header>
          <main className="content" key={page}>{PAGES[page]()}</main>
        </div>
      </div>
    </AppContext.Provider>
  );
}

function SignIn({ project, onDone }: { project: Project; onDone: () => void }) {
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true);
    setError(null);
    apiKey.set(key.trim());
    try {
      await p2e.documents(project.code, { limit: 1 });       // a protected call: proves the key works
      onDone();
    } catch (e) {
      apiKey.clear();
      setError(e instanceof ApiError && e.status === 503 ? "The server has no API keys configured (set P2E_API_KEYS)." : (e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="center">
      <form className="card signin" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <div className="brand"><span className="brand-mark">P2E</span><span><strong>Bridge</strong><small>{project.code} · {project.name}</small></span></div>
        <p className="muted">Sign in with your role API key (supervisor, planner or admin). It is kept only in this browser tab.</p>
        <label className="stacked">API key<input type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} required minLength={16} autoFocus /></label>
        {error && <ErrorBox error={error} />}
        <button className="btn btn-primary" disabled={busy || key.trim().length < 16}>{busy ? "Checking…" : "Sign in"}</button>
      </form>
    </div>
  );
}
