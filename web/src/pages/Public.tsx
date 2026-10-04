// Signed-out pages: cinematic landing, sign in (with the evaluator demo account), sign up (request access).
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import Lenis from "lenis";
import { ApiError, apiKey } from "../api/client";
import { p2e, type Project } from "../api/p2e";
import { LANGS, useT, type Lang } from "../i18n";
import { humanize } from "../utils/format";
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

const FRAMES = 242;                                   // web/public/seq: landing-1..3 at 10 fps (scroll-scrubbed, Apple style)
const frameUrl = (i: number) => `/seq/f_${String(i + 1).padStart(3, "0")}.webp`;
const BEATS = [
  { k: "pub.ch1t", b: "pub.ch1b", at: 0.22 }, { k: "pub.ch2t", b: "pub.ch2b", at: 0.47 }, { k: "pub.ch3t", b: "pub.ch3b", at: 0.72 },
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

/** Draw frame i cover-fitted; falls back to the nearest frame already loaded. */
function draw(ctx: CanvasRenderingContext2D, imgs: HTMLImageElement[], i: number) {
  let img = imgs[i];
  for (let d = 1; (!img || !img.complete || !img.naturalWidth) && d < FRAMES; d++) img = imgs[i - d] ?? imgs[i + d];
  if (!img?.naturalWidth) return;
  const { width: w, height: h } = ctx.canvas, s = Math.max(w / img.naturalWidth, h / img.naturalHeight);
  ctx.drawImage(img, (w - img.naturalWidth * s) / 2, (h - img.naturalHeight * s) / 2, img.naturalWidth * s, img.naturalHeight * s);
}

export function LandingPage({ project }: { project: Project }) {
  const { t } = useT();
  const root = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);

  useLayoutEffect(() => {
    if (!root.current || !canvas.current) return;
    const lenis = new Lenis({ lerp: 0.085, smoothWheel: true });          // one smooth-scroll loop, synced with ScrollTrigger
    lenis.on("scroll", ScrollTrigger.update);
    const tick = (time: number) => lenis.raf(time * 1000);
    gsap.ticker.add(tick);
    gsap.ticker.lagSmoothing(0);

    const ctx2d = canvas.current.getContext("2d")!;
    const imgs: HTMLImageElement[] = [];
    const seq = { frame: 0 };
    const resize = () => {
      const c = canvas.current!, dpr = Math.min(window.devicePixelRatio || 1, 2);
      c.width = innerWidth * dpr; c.height = innerHeight * dpr;
      draw(ctx2d, imgs, Math.round(seq.frame));
    };
    for (let i = 0; i < FRAMES; i++) {                                     // first frame at once, the rest progressively
      const img = new Image();
      img.decoding = "async";
      img.src = frameUrl(i);
      if (i === 0) img.onload = () => draw(ctx2d, imgs, 0);
      imgs.push(img);
    }
    resize();
    addEventListener("resize", resize);

    const gctx = gsap.context(() => {
      const hero = { trigger: ".seq", start: "top top", end: "bottom bottom", scrub: 0.6 };
      gsap.to(seq, { frame: FRAMES - 1, ease: "none", scrollTrigger: hero, onUpdate: () => draw(ctx2d, imgs, Math.round(seq.frame)) });
      gsap.fromTo(".seq-canvas", { scale: 1.18 }, { scale: 1, ease: "none", scrollTrigger: hero });
      gsap.to(".seq-progress i", { scaleX: 1, ease: "none", scrollTrigger: hero });
      // intro: letters assemble, then the headline lifts away as the film starts
      gsap.from(".intro .display", { opacity: 0, y: 60, filter: "blur(18px)", duration: 1.4, ease: "expo.out" });
      gsap.from(".intro .lede, .intro .hero-cta, .intro .kicker", { opacity: 0, y: 30, duration: 1.2, stagger: 0.12, delay: 0.3, ease: "expo.out" });
      const tl = gsap.timeline({ scrollTrigger: hero });
      tl.to(".intro", { opacity: 0, y: -120, scale: 0.92, filter: "blur(10px)", duration: 0.12, ease: "power2.in" }, 0.02);
      gsap.utils.toArray<HTMLElement>(".beat").forEach((el, i) => {
        const at = BEATS[i].at;
        tl.fromTo(el, { opacity: 0, y: 80, filter: "blur(12px)" }, { opacity: 1, y: 0, filter: "blur(0px)", duration: 0.08, ease: "power2.out" }, at - 0.06)
          .to(el, { opacity: 0, y: -80, filter: "blur(12px)", duration: 0.08, ease: "power2.in" }, at + 0.14);
      });
      tl.fromTo(".seq-veil", { opacity: 0.25 }, { opacity: 0.75, duration: 0.2 }, 0.8);
      tl.set({}, {}, 1);                                                   // timeline spans the whole pinned scroll

      // statement: words light up as they cross the viewport (Apple text reveal)
      gsap.fromTo(".statement .w", { opacity: 0.12 }, { opacity: 1, stagger: 0.05, ease: "none",
        scrollTrigger: { trigger: ".statement", start: "top 75%", end: "bottom 45%", scrub: true } });

      // 3D product reveal: the dashboard tilts up out of the page while pinned
      const tilt = gsap.timeline({ scrollTrigger: { trigger: ".device-pin", start: "top top", end: "+=140%", scrub: 0.8, pin: true } });
      tilt.fromTo(".device", { rotateX: 58, scale: 0.72, y: 160 }, { rotateX: 0, scale: 1, y: 0, ease: "power2.out" })
        .fromTo(".device .kpi-tile", { opacity: 0, y: 30 }, { opacity: 1, y: 0, stagger: 0.05 }, 0.45)
        .fromTo(".device .mbar i", { scaleX: 0 }, { scaleX: 1, stagger: 0.04 }, 0.55)
        .fromTo(".device .kcard", { opacity: 0, x: -24 }, { opacity: 1, x: 0, stagger: 0.04 }, 0.6)
        .fromTo(".device-caption", { opacity: 0, y: 40 }, { opacity: 1, y: 0 }, 0.7);

      gsap.fromTo(".flow-line path", { strokeDashoffset: 1 }, { strokeDashoffset: 0, ease: "none",
        scrollTrigger: { trigger: ".flow", start: "top 75%", end: "bottom 55%", scrub: true } });
      gsap.from(".flow-step", { y: 40, opacity: 0, stagger: 0.12, duration: 0.9, ease: "expo.out", scrollTrigger: { trigger: ".flow", start: "top 72%" } });

      // agents: vertical scroll drives a horizontal track, cards turn in 3D as they pass
      const track = document.querySelector<HTMLElement>(".agents-track");
      if (track) {
        const dist = () => Math.max(0, track.scrollWidth - innerWidth + 64);
        gsap.to(track, { x: () => -dist(), ease: "none",
          scrollTrigger: { trigger: ".agents-pin", start: "top top", end: () => `+=${dist()}`, scrub: 0.8, pin: true, invalidateOnRefresh: true } });
        gsap.from(".agent-card", { rotateY: -35, opacity: 0, stagger: 0.08, duration: 1, ease: "expo.out", scrollTrigger: { trigger: ".agents-pin", start: "top 70%" } });
      }
      gsap.utils.toArray<HTMLElement>(".reveal").forEach((el) =>
        gsap.from(el, { y: 70, opacity: 0, duration: 1.1, ease: "expo.out", scrollTrigger: { trigger: el, start: "top 88%" } }));
      gsap.utils.toArray<HTMLElement>(".count").forEach((el) => {
        const end = Number(el.dataset.n), dec = Number(el.dataset.dec), obj = { v: 0 };
        gsap.to(obj, { v: end, duration: 1.8, ease: "power2.out", scrollTrigger: { trigger: el, start: "top 88%" },
          onUpdate: () => { el.textContent = obj.v.toFixed(dec); } });
      });
    }, root);
    return () => { gctx.revert(); gsap.ticker.remove(tick); lenis.destroy(); removeEventListener("resize", resize); };
  }, []);

  const go = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
  return (
    <div className="public landing" ref={root}>
      <PublicNav sections />
      <section className="seq" aria-label={t("pub.heroTitle")}>
        <div className="seq-stage">
          <canvas ref={canvas} className="seq-canvas" aria-hidden />
          <div className="seq-veil" aria-hidden />
          <div className="intro">
            <span className="kicker">SIH26122 · Oil India Limited · {project.code}</span>
            <h1 className="display">{t("pub.heroTitle")}</h1>
            <p className="lede">{t("pub.heroLede")}</p>
            <div className="hero-cta">
              <a className="btn btn-primary btn-lg" href={href("signin")}>{t("pub.tryDemo")}</a>
              <button type="button" className="btn btn-glass btn-lg" onClick={() => go("how")}>{t("pub.seeHow")}</button>
            </div>
            <span className="scroll-hint" aria-hidden>{t("pub.scroll")}</span>
          </div>
          {BEATS.map((b, i) => (
            <div key={b.k} className="beat"><span className="beat-n">0{i + 1}</span><h2>{t(b.k)}</h2><p>{t(b.b)}</p></div>
          ))}
          <div className="seq-progress" aria-hidden><i /></div>
        </div>
      </section>

      <section className="statement band">
        <p>{t("pub.statement").split(" ").map((w, i) => <span key={i} className="w">{w} </span>)}</p>
      </section>

      <section className="device-pin">
        <div className="device-stage">
          <div className="device" aria-hidden>
            <div className="device-bar"><i /><i /><i /><span>P2E Bridge · {project.code}</span></div>
            <div className="device-body">
              <div className="kpi-row">
                {[["261 / 433", "pub.p1"], ["0", "pub.p2"], ["48 / 48", "pub.p3"], ["5.3 s", "pub.p4"]].map(([v, k]) => (
                  <div key={k} className="kpi-tile"><b>{v}</b><span>{t(k)}</span></div>
                ))}
              </div>
              <div className="device-grid">
                <div className="mpanel"><h4>{t("an.progDisc")}</h4>
                  {([["civil", 82], ["piping", 64], ["electrical", 48], ["instrumentation", 57], ["static_eq", 71]] as const).map(([d, v]) => (
                    <div key={d} className="mbar"><span>{humanize(d)}</span><em><i style={{ width: `${v}%` }} /></em></div>
                  ))}
                </div>
                <div className="mpanel kanban">
                  {[["review", "LT-4011 loop check", "Line 1217 erection"], ["matched", "Line 1211 hydrotest", "P-101A grouting"], ["confirmed", "HT-SWBD-1 install", "Area 3 backfill"]].map(([col, ...cards]) => (
                    <div key={col} className="kcol"><h4>{humanize(col)}</h4>{cards.map((c) => <div key={c} className="kcard">{c}</div>)}</div>
                  ))}
                </div>
              </div>
            </div>
          </div>
          <div className="device-caption"><span className="kicker">{t("pub.deviceK")}</span><h2 className="display-2">{t("pub.deviceT")}</h2></div>
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

      <section id="agents" className="agents-pin band-tint">
        <div className="agents-head"><span className="kicker">{t("pub.agentsK")}</span><h2 className="display-2">{t("pub.agentsT")}</h2></div>
        <div className="agents-track">
          {AGENTS.map((a) => (
            <article key={a.icon} className="agent-card">
              <img src={`/brand/${a.icon}.webp`} alt="" width={88} height={88} loading="lazy" />
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
