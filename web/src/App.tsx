import { useEffect, useMemo, useState, type ReactNode } from "react";
import { apiKey } from "./api/client";
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
import { RoiPage } from "./pages/ROI";
import { GuidePage, TermsPage, VideoPage } from "./pages/Help";
import { LandingPage, SignInPage, SignUpPage } from "./pages/Public";
import { Assistant } from "./components/Assistant";
import { LANGS, LangContext, loadLang, saveLang, useT, type Lang } from "./i18n";
import { SchedulePage } from "./pages/Schedule";
import { WatchPage } from "./pages/Watch";
import { AppContext } from "./state";
import { todayIso } from "./utils/format";
import { href, navigate, useRoute } from "./utils/route";

// labels are i18n keys (web/src/i18n.ts)
const NAV: { group: string; items: { page: string; label: string; icon: string }[] }[] = [
  { group: "nav.operate", items: [
    { page: "overview", label: "nav.overview", icon: "◎" },
    { page: "reports", label: "nav.reports", icon: "▤" },
    { page: "linking", label: "nav.linking", icon: "⇄" },
    { page: "agent", label: "nav.agent", icon: "✎" },
  ] },
  { group: "nav.plan", items: [
    { page: "schedule", label: "nav.schedule", icon: "▦" },
    { page: "watch", label: "nav.watch", icon: "◔" },
    { page: "audit", label: "nav.audit", icon: "☰" },
  ] },
  { group: "nav.intelligence", items: [
    { page: "analytics", label: "nav.analytics", icon: "▥" },
    { page: "roi", label: "nav.roi", icon: "₹" },
    { page: "memory", label: "nav.memory", icon: "❖" },
  ] },
  { group: "nav.present", items: [{ page: "demo", label: "nav.demo", icon: "▶" }] },
  { group: "nav.help", items: [
    { page: "guide", label: "nav.guide", icon: "?" },
    { page: "video", label: "nav.video", icon: "▷" },
    { page: "terms", label: "nav.terms", icon: "§" },
  ] },
];

const PAGES: Record<string, () => ReactNode> = {
  overview: () => <OverviewPage />, reports: () => <ReportsPage />, linking: () => <LinkingPage />, agent: () => <AgentPage />,
  schedule: () => <SchedulePage />, watch: () => <WatchPage />, audit: () => <AuditPage />, analytics: () => <AnalyticsPage />,
  memory: () => <MemoryPage />, demo: () => <DemoPage />, roi: () => <RoiPage />,
  guide: () => <GuidePage />, terms: () => <TermsPage />, video: () => <VideoPage />,
};

function LangPicker() {
  const { lang, setLang, t } = useT();
  return (
    <select className="lang-picker" value={lang} onChange={(e) => setLang(e.target.value as Lang)} aria-label={t("shell.language")}>
      {LANGS.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
    </select>
  );
}

export function App() {
  const [lang, setLangState] = useState<Lang>(loadLang);
  useEffect(() => saveLang(lang), [lang]);
  return <LangContext.Provider value={{ lang, setLang: setLangState }}><Shell /></LangContext.Provider>;
}

function loadAsOf(): string {
  try {
    return localStorage.getItem("p2e.asOf") || todayIso();
  } catch {
    return todayIso();
  }
}

function Shell() {
  const { t } = useT();
  const [signedIn, setSignedIn] = useState(() => !!apiKey.get());
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [projectCode, setProjectCode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asOf, setAsOfState] = useState(loadAsOf);
  const [theme, setTheme] = useState(() => (typeof localStorage !== "undefined" && localStorage.getItem("p2e.theme")) || "light");
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
  if (!signedIn) {
    const done = () => { setSignedIn(true); navigate("overview"); };
    if (route.page === "signin") return <SignInPage project={project} onDone={done} />;
    if (route.page === "signup") return <SignUpPage />;
    if (route.page === "terms") return <div className="content"><LangPicker /> <a href={href("welcome")}>←</a><TermsPage /></div>;
    return <LandingPage project={project} />;
  }

  const page = PAGES[route.page] ? route.page : "overview";
  return (
    <AppContext.Provider value={{ project, asOf, setAsOf, live, snapshot }}>
      <div className="shell">
        <aside className="sidebar">
          <div className="brand"><img src="/brand/logo.webp" alt="P2E Bridge" className="brand-logo" /><small>{t("shell.tagline")}</small></div>
          <nav aria-label="Main">
            {NAV.map((g) => (
              <div key={g.group} className="nav-group">
                <span className="nav-title">{t(g.group)}</span>
                {g.items.map((it) => (
                  <a key={it.page} href={href(it.page)} className={page === it.page ? "active" : ""} aria-current={page === it.page ? "page" : undefined}>
                    <span className="nav-icon" aria-hidden>{it.icon}</span>{t(it.label)}
                    {it.page === "linking" && snapshot?.pending_review ? <span className="nav-count">{snapshot.pending_review}</span> : null}
                  </a>
                ))}
              </div>
            ))}
          </nav>
          <p className="sidebar-foot">{t("shell.foot")}</p>
        </aside>
        <div className="main">
          <header className="topbar">
            <div className="topbar-project">
              <strong>{project.code}</strong><span className="muted">{project.name}</span>
            </div>
            <label className="asof">{t("shell.asof")}
              <input type="date" value={asOf} onChange={(e) => e.target.value && setAsOf(e.target.value)} />
            </label>
            <LangPicker />
            <Badge tone={connected ? "ok" : "muted"} title="Live updates from the backend event stream">{connected ? t("shell.live") : t("shell.offline")}</Badge>
            <button type="button" className="btn btn-sm" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label="Toggle colour theme">{theme === "dark" ? "☀" : "☾"}</button>
            <button type="button" className="btn btn-sm" onClick={() => { apiKey.clear(); setSignedIn(false); navigate("welcome"); }}>{t("shell.signout")}</button>
          </header>
          <main className="content" key={page}>{PAGES[page]()}</main>
        </div>
      </div>
      <Assistant />
    </AppContext.Provider>
  );
}
