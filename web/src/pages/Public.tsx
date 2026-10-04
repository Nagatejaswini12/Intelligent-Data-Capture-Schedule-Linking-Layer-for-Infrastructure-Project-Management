// Signed-out pages: cinematic landing, sign in (with the evaluator demo account), sign up (request access).
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { ApiError, apiKey } from "../api/client";
import { p2e, type Project } from "../api/p2e";
import { LANGS, useT, type Lang } from "../i18n";
import { href } from "../utils/route";

gsap.registerPlugin(ScrollTrigger);
const still = () => typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;
const scrollTo = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: still() ? "auto" : "smooth" });

/** Stacked background videos that crossfade; `active` drives them from outside, otherwise they play in turn. */
function VideoBackdrop({ names, active, className = "" }: { names: string[]; active?: number; className?: string }) {
  const [own, setOwn] = useState(0);
  const idx = active ?? own;
  const refs = useRef<(HTMLVideoElement | null)[]>([]);
  const reduce = still();
  useEffect(() => {
    if (reduce) return;
    refs.current.forEach((v, i) => {
      if (!v) return;
      if (i === idx) v.play().catch(() => { /* autoplay blocked: poster stays */ }); else v.pause();
    });
  }, [idx, reduce]);
  return (
    <div className={`video-backdrop ${className}`} aria-hidden>
      {names.map((n, i) => reduce
        ? <img key={n} src={`/media/${n}.jpg`} alt="" className={i === idx ? "on" : ""} />
        : <video key={n} ref={(el) => { refs.current[i] = el; }} src={`/media/${n}.mp4`} poster={`/media/${n}.jpg`} muted playsInline
            preload={i === 0 ? "auto" : "metadata"} className={i === idx ? "on" : ""} loop={names.length === 1 || active !== undefined}
            onEnded={() => setOwn((x) => (x + 1) % names.length)} />)}
      <div className="video-veil" />
    </div>
  );
}

function PublicNav({ sections = false }: { sections?: boolean }) {
  const { t, lang, setLang } = useT();
  return (
    <header className="pub-nav">
      <a href={href("welcome")} className="pub-logo"><img src="/brand/logo.webp" alt="P2E Bridge" /></a>
      {sections && (
        <nav className="pub-links" aria-label="Sections">
          {[["how", "pub.navHow"], ["agents", "pub.navAgents"], ["proof", "pub.navProof"], ["official", "pub.navOfficial"]].map(([id, k]) => (
            <button key={id} type="button" onClick={() => scrollTo(id)}>{t(k)}</button>
          ))}
        </nav>
      )}
      <div className="pub-actions">
        <select className="lang-picker" value={lang} onChange={(e) => setLang(e.target.value as Lang)} aria-label={t("shell.language")}>
          {LANGS.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
        </select>
        <a className="btn btn-ghost" href={href("signin")}>{t("signin.go")}</a>
        <a className="btn btn-primary" href={href("signup")}>{t("pub.request")}</a>
      </div>
    </header>
  );
}

const CHAPTERS = [
  { video: "landing-1", title: "pub.ch1t", body: "pub.ch1b" },
  { video: "landing-2", title: "pub.ch2t", body: "pub.ch2b" },
  { video: "landing-3", title: "pub.ch3t", body: "pub.ch3b" },
];
const STEPS = ["pub.s1", "pub.s2", "pub.s3", "pub.s4", "pub.s5"];
const AGENTS = [
  { icon: "agent-time", title: "nav.agent", body: "pub.aTime" }, { icon: "agent-linker", title: "pub.aLinkerT", body: "pub.aLinker" },
  { icon: "agent-watch", title: "nav.watch", body: "pub.aWatch" }, { icon: "agent-memory", title: "nav.memory", body: "pub.aMemory" },
  { icon: "chatbot", title: "as.open", body: "pub.aAsk" }, { icon: "voice", title: "pub.aVoiceT", body: "pub.aVoice" },
];
// measured on the synthetic project (README "Results")
const PROOF = [
  { n: 261, dec: 0, suffix: " / 433", label: "pub.p1" }, { n: 0, dec: 0, suffix: "", label: "pub.p2" },
  { n: 48, dec: 0, suffix: " / 48", label: "pub.p3" }, { n: 5.3, dec: 1, suffix: " s", label: "pub.p4" },
  { n: 0, dec: 0, suffix: "", label: "pub.p5" },
];
const OFFICIAL = [["BHASHINI", "pub.offBhashini"], ["AIKosh", "pub.offAikosh"], ["Oil India Limited", "pub.offOil"]];

export function LandingPage({ project }: { project: Project }) {
  const { t } = useT();
  const root = useRef<HTMLDivElement>(null);
  const [chapter, setChapter] = useState(0);

  useLayoutEffect(() => {
    if (still() || !root.current) return;
    const ctx = gsap.context(() => {
      const pin = { trigger: ".hero-pin", start: "top top", end: "bottom bottom", scrub: true };
      ScrollTrigger.create({ ...pin, onUpdate: (st) => setChapter(Math.min(2, Math.floor(st.progress * 3))) });
      gsap.to(".hero-rail-fill", { scaleY: 1, ease: "none", scrollTrigger: pin });
      gsap.to(".hero-copy", { yPercent: -18, opacity: 0.15, ease: "none", scrollTrigger: { ...pin, end: "35% top" } });
      gsap.from(".hero-copy > *", { y: 40, opacity: 0, duration: 1.1, ease: "power3.out", stagger: 0.12 });
      gsap.utils.toArray<HTMLElement>(".reveal").forEach((el) =>
        gsap.from(el, { y: 56, opacity: 0, duration: 1, ease: "power3.out", scrollTrigger: { trigger: el, start: "top 86%" } }));
      gsap.fromTo(".flow-line path", { strokeDashoffset: 1 }, { strokeDashoffset: 0, ease: "none",
        scrollTrigger: { trigger: ".flow", start: "top 75%", end: "bottom 55%", scrub: true } });
      gsap.from(".flow-step", { y: 30, opacity: 0, stagger: 0.14, duration: 0.8, ease: "power2.out", scrollTrigger: { trigger: ".flow", start: "top 72%" } });
      gsap.from(".agent-card", { y: 50, opacity: 0, stagger: 0.08, duration: 0.9, ease: "power3.out", scrollTrigger: { trigger: ".agents", start: "top 78%" } });
      gsap.utils.toArray<HTMLElement>(".count").forEach((el) => {
        const end = Number(el.dataset.n), dec = Number(el.dataset.dec), obj = { v: 0 };
        gsap.to(obj, { v: end, duration: 1.6, ease: "power2.out", scrollTrigger: { trigger: el, start: "top 88%" },
          onUpdate: () => { el.textContent = obj.v.toFixed(dec); } });
      });
    }, root);
    return () => ctx.revert();
  }, []);

  return (
    <div className="public landing" ref={root}>
      <PublicNav sections />
      <section className="hero-pin">
        <div className="hero-stage">
          <VideoBackdrop names={CHAPTERS.map((c) => c.video)} active={chapter} className="hero-video" />
          <div className="hero-copy">
            <span className="kicker">SIH26122 · Oil India Limited · {project.code}</span>
            <h1 className="display">{t("pub.heroTitle")}</h1>
            <p className="lede">{t("pub.heroLede")}</p>
            <div className="hero-cta">
              <a className="btn btn-primary btn-lg" href={href("signin")}>{t("pub.tryDemo")}</a>
              <button type="button" className="btn btn-glass btn-lg" onClick={() => scrollTo("how")}>{t("pub.seeHow")}</button>
            </div>
          </div>
          <ol className="hero-chapters" aria-label={t("pub.navHow")}>
            {CHAPTERS.map((c, i) => (
              <li key={c.video} className={i === chapter ? "on" : ""}>
                <span className="chapter-n">0{i + 1}</span>
                <div><strong>{t(c.title)}</strong><p>{t(c.body)}</p></div>
              </li>
            ))}
          </ol>
          <div className="hero-rail" aria-hidden><div className="hero-rail-fill" /></div>
        </div>
      </section>

      <section id="how" className="band">
        <div className="band-head reveal"><span className="kicker">{t("pub.howK")}</span><h2 className="display-2">{t("pub.howT")}</h2></div>
        <div className="flow">
          <svg className="flow-line" viewBox="0 0 1000 4" preserveAspectRatio="none" aria-hidden><path d="M0 2 H1000" pathLength={1} /></svg>
          {STEPS.map((s, i) => (
            <div key={s} className="flow-step"><span className="flow-dot">{i + 1}</span><strong>{t(`${s}t`)}</strong><p>{t(`${s}b`)}</p></div>
          ))}
        </div>
      </section>

      <section id="agents" className="band band-tint">
        <div className="band-head reveal"><span className="kicker">{t("pub.agentsK")}</span><h2 className="display-2">{t("pub.agentsT")}</h2></div>
        <div className="agents">
          {AGENTS.map((a) => (
            <article key={a.icon} className="agent-card">
              <img src={`/brand/${a.icon}.webp`} alt="" width={64} height={64} loading="lazy" />
              <h3>{t(a.title)}</h3><p>{t(a.body)}</p>
            </article>
          ))}
        </div>
      </section>

      <section id="proof" className="band">
        <div className="band-head reveal"><span className="kicker">{t("pub.proofK")}</span><h2 className="display-2">{t("pub.proofT")}</h2></div>
        <div className="proof">
          {PROOF.map((p) => (
            <div key={p.label} className="proof-item reveal">
              <span className="proof-n"><span className="count" data-n={p.n} data-dec={p.dec}>{p.n.toFixed(p.dec)}</span>{p.suffix}</span>
              <span className="proof-label">{t(p.label)}</span>
            </div>
          ))}
        </div>
        <p className="muted small center-text">{t("pub.synthetic")}</p>
      </section>

      <section id="official" className="band band-tint">
        <div className="band-head reveal"><span className="kicker">{t("pub.offK")}</span><h2 className="display-2">{t("pub.offT")}</h2></div>
        <div className="official">
          {OFFICIAL.map(([n, k]) => <div key={n} className="official-item reveal"><strong>{n}</strong><p>{t(k)}</p></div>)}
        </div>
      </section>

      <section className="closing">
        <VideoBackdrop names={["landing-3"]} />
        <div className="closing-copy reveal">
          <h2 className="display-2">{t("pub.closeT")}</h2>
          <div className="hero-cta">
            <a className="btn btn-primary btn-lg" href={href("signin")}>{t("pub.tryDemo")}</a>
            <a className="btn btn-glass btn-lg" href={href("signup")}>{t("pub.request")}</a>
          </div>
        </div>
      </section>
      <footer className="pub-foot">
        <img src="/brand/logo-mark.webp" alt="" width={24} height={24} /> P2E Bridge · SIH26122 · <a href={href("terms")}>{t("nav.terms")}</a>
      </footer>
    </div>
  );
}

function AuthShell({ videos, children }: { videos: string[]; children: ReactNode }) {
  return (
    <div className="public auth">
      <VideoBackdrop names={videos} />
      <PublicNav />
      <main className="auth-main">{children}</main>
    </div>
  );
}

export function SignInPage({ project, onDone }: { project: Project; onDone: () => void }) {
  const { t } = useT();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [demo, setDemo] = useState<{ username: string; password: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { p2e.demoAccount().then(setDemo, () => setDemo(null)); }, []);   // 404 outside demo deployments
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      apiKey.set((await p2e.login({ username: username.trim(), password })).token);
      onDone();
    } catch (e) {
      setError(e instanceof ApiError && e.status === 401 ? t("auth.wrong") : (e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <AuthShell videos={["signin-1", "signin-2"]}>
      <form className="auth-card" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <h1>{t("auth.welcome")}</h1>
        <p className="muted">{project.code} · {project.name}</p>
        <label className="stacked">{t("auth.username")}
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" placeholder="planner · supervisor · admin" required autoFocus />
        </label>
        <label className="stacked">{t("auth.password")}
          <span className="pw">
            <input type={show ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
            <button type="button" className="pw-toggle" onClick={() => setShow(!show)}>{show ? t("auth.hide") : t("auth.show")}</button>
          </span>
        </label>
        {demo && (
          <div className="demo-box">
            <div><strong>{t("auth.demoT")}</strong><span>{t("auth.demoB", { u: demo.username })}</span></div>
            <button type="button" className="btn btn-sm" onClick={() => { setUsername(demo.username); setPassword(demo.password); }}>{t("auth.fillDemo")}</button>
          </div>
        )}
        {error && <p className="auth-error" role="alert">{error}</p>}
        <button className="btn btn-primary btn-lg" disabled={busy || !username.trim() || !password}>{busy ? t("signin.checking") : t("signin.go")}</button>
        <p className="small muted">{t("auth.noAccount")} <a href={href("signup")}>{t("pub.request")}</a></p>
        <p className="small muted"><a href={href("terms")}>{t("signin.terms")}</a></p>
      </form>
    </AuthShell>
  );
}

export function SignUpPage() {
  const { t } = useT();
  const [form, setForm] = useState({ name: "", email: "", organisation: "", role_requested: "supervisor", reason: "" });
  const [done, setDone] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const field = (k: keyof typeof form) => ({ value: form[k], onChange: (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value }) });
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      setDone((await p2e.requestAccess(form)).id);
    } catch (e) {
      setError(e instanceof ApiError && e.status === 422 ? t("auth.invalid") : (e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <AuthShell videos={["signup-1", "signup-2"]}>
      {done !== null ? (
        <div className="auth-card" role="status">
          <img src="/brand/logo-mark.webp" alt="" width={56} height={56} />
          <h1>{t("auth.sentT")}</h1>
          <p>{t("auth.sentB", { id: done })}</p>
          <a className="btn btn-primary btn-lg" href={href("signin")}>{t("signin.go")}</a>
        </div>
      ) : (
        <form className="auth-card" onSubmit={(e) => { e.preventDefault(); submit(); }}>
          <h1>{t("pub.request")}</h1>
          <p className="muted">{t("auth.reqLede")}</p>
          <label className="stacked">{t("auth.name")}<input {...field("name")} required minLength={2} autoComplete="name" /></label>
          <label className="stacked">{t("auth.email")}<input type="email" {...field("email")} required autoComplete="email" /></label>
          <label className="stacked">{t("auth.org")}<input {...field("organisation")} required minLength={2} autoComplete="organization" /></label>
          <label className="stacked">{t("auth.role")}
            <select {...field("role_requested")}>
              <option value="supervisor">Supervisor</option><option value="planner">Planner</option><option value="admin">Admin</option>
            </select>
          </label>
          <label className="stacked">{t("auth.reason")}<textarea {...field("reason")} rows={3} maxLength={1000} /></label>
          {error && <p className="auth-error" role="alert">{error}</p>}
          <button className="btn btn-primary btn-lg" disabled={busy}>{busy ? t("signin.checking") : t("auth.send")}</button>
          <p className="small muted">{t("auth.haveAccount")} <a href={href("signin")}>{t("signin.go")}</a></p>
        </form>
      )}
    </AuthShell>
  );
}
