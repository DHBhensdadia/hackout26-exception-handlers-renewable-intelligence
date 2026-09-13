import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { HeroTurbines, type HeroTurbine } from "@/components/HeroTurbines";
import { useScrollBehaviour } from "@/components/Shell";
import { SiteHeader } from "@/components/SiteNav";
import { SiteFooter } from "@/components/SiteFooter";
import { ScrollProgress } from "@/components/ScrollProgress";
import { CtaBand } from "@/components/CtaBand";
import { Reveal } from "@/components/Reveal";
import { HeroConsole } from "@/components/HeroConsole";
import { stagger } from "@/lib/style";
import "../styles/cinematic.css";

/**
 * Merged landing surface.
 *
 * The top of the page is the cinematic hero — a single photographic plate
 * used verbatim, with real 3D turbines composited in front of it. It then
 * dissolves through a gradient seam into the existing marketing page
 * (intro, console, principle, flow, horizons, modules, runway, CTA) so the
 * two designs read as one continuous, scrolled surface rather than two
 * stitched sites.
 *
 * Turbine positions are in plate coordinates (% of the photograph, not the
 * viewport) and live inside the transformed stage, so they stay locked to
 * the image at every aspect ratio and right through the camera move.
 */
const TURBINES: readonly HeroTurbine[] = [
  // Hero turbine: stands exactly where the photographed turbine was retouched
  // out of the plate, so the rotor turns on that turbine's own hub. Radius is
  // set so the model's tower lands on the original foundation pad.
  { x: 75.625, y: 50.469, r: 8.33, tower: 14.6, rev: 6.4, phase: 40, yaw: 22, tone: 1 },
  { x: 63.0, y: 53.0, r: 7.2, tower: 20, rev: 5.4, phase: 0, yaw: -22, tone: 1 },
  { x: 84.5, y: 57.0, r: 5.0, tower: 14, rev: 6.2, phase: 137, yaw: 14, tone: 0.78 },
  { x: 33.0, y: 52.0, r: 4.2, tower: 13, rev: 4.9, phase: 274, yaw: -8, tone: 0.55 },
];

const BANDS = [
  { cls: "cine__band--high", dur: "150s" },
  { cls: "cine__band--mid", dur: "104s" },
  { cls: "cine__band--low", dur: "72s" },
] as const;

const FLOW = [
  { n: "01", t: "Data", d: "Weather, historical generation, equipment, demand, economic and demographic signals." },
  { n: "02", t: "Forecast", d: "Solar and wind output 24–72 hours ahead, with calibrated quantile bands (p10/p50/p90)." },
  { n: "03", t: "Compare", d: "Forecast vs expected demand and storage headroom — surplus or shortage?" },
  { n: "04", t: "Optimize", d: "Charge storage, dispatch backup, curtail only when necessary." },
  { n: "05", t: "Plan", d: "Seasonal patterns and future demand growth become planning knowledge." },
  { n: "06", t: "Invest", d: "Long-term capacity, storage and budget allocation scenarios." },
  { n: "07", t: "Decide", d: "A decision-support dashboard surfaces the recommended call and its trade-offs." },
];

const HORIZONS = [
  {
    tag: "Short-term · 24–72 h",
    title: "How much will we generate — and what do we do with it?",
    body: "Power forecasting, demand-vs-generation comparison, surplus/shortage detection, storage dispatch, backup activation, curtailment recommendations.",
  },
  {
    tag: "Medium-term · Seasonal",
    title: "What recurs, and what should we prepare for?",
    body: "Seasonal generation patterns, repeated surplus/shortage periods, equipment failure patterns, preventive maintenance planning.",
  },
  {
    tag: "Long-term · Years",
    title: "Where should the next investment go?",
    body: "Electricity demand growth, renewable technology selection, generation and storage capacity planning, ROI and budget allocation.",
  },
];

const MODULES = [
  { id: "M01", name: "Renewable Power Forecasting", d: "Solar and wind generation for the next 24–72 hours from weather, geometry, physics priors and plant characteristics." },
  { id: "M02", name: "Generation · Demand · Storage Balance", d: "Compares forecast generation against demand and storage to flag potential surplus or shortage and recommend a response." },
  { id: "M03", name: "Seasonal Pattern Analysis", d: "Turns historical data into planning knowledge — recurring surpluses, low-generation windows, high-demand seasons." },
  { id: "M04", name: "Equipment Reliability & Failure", d: "Risk scoring and preventive-maintenance guidance — under which conditions equipment fails, and how much generation is at stake." },
  { id: "M05", name: "Long-Term Investment Analysis", d: "Evaluates solar, wind, storage and hybrid candidates on technical, financial and weather factors — as a scenario comparison." },
  { id: "M06", name: "Future Demand Forecasting", d: "Population, industrial expansion and consumption trends to show where electricity will be needed and by when." },
  { id: "M07", name: "Integrated Investment Optimization", d: "The module that ties the system together — generation + storage + location + timing under real constraints and budget." },
];

const PRINCIPLE = [
  {
    n: "01",
    t: "Predict power",
    d: "Hourly solar and wind generation for the next 24–72 hours, issued with calibrated uncertainty bands rather than a single guess.",
  },
  {
    n: "02",
    t: "Optimize its use",
    d: "Compare forecast generation against demand and storage — then recommend charging, discharging, backup or curtailment.",
  },
  {
    n: "03",
    t: "Understand future needs",
    d: "Turn recurring seasonal patterns, equipment reliability and demand growth into planning knowledge.",
  },
  {
    n: "04",
    t: "Invest efficiently",
    d: "Score solar, wind, storage and hybrid options against budget, risk and expected return.",
  },
];

const QUESTIONS = [
  {
    q: "What will we generate?",
    a: "Forecast solar and wind output for the next 24–72 hours with honest uncertainty.",
  },
  {
    q: "What should we do with that power?",
    a: "Surplus or shortage — charge storage, hold backup, or curtail only when necessary.",
  },
  {
    q: "What risks should we prepare for?",
    a: "Recurring seasonal patterns, equipment failure risk, low-generation windows.",
  },
  {
    q: "Where should we invest next?",
    a: "Future demand, generation potential, economics and storage constraints converge on a recommendation.",
  },
];

const PHASES = [
  {
    phase: "Phase 1",
    name: "Core MVP",
    scope: "now" as const,
    items: [
      "Historical generation ingestion",
      "Weather data ingestion",
      "24–72 h solar & wind forecast",
      "Surplus / shortage detection",
      "Basic decision dashboard",
    ],
  },
  {
    phase: "Phase 2",
    name: "Operational Intelligence",
    scope: "next" as const,
    items: [
      "Demand forecasting",
      "Storage-aware recommendations",
      "Seasonal pattern analysis",
      "Reliability & failure analysis",
    ],
  },
  {
    phase: "Phase 3",
    name: "Strategic Planning",
    scope: "next" as const,
    items: [
      "Population & industrial demand forecasting",
      "Renewable investment comparison",
      "ROI analysis",
      "Storage investment analysis",
      "Budget optimization",
      "What-if scenarios",
    ],
  },
];

function PhaseBlock({ p, i }: { p: (typeof PHASES)[number]; i: number }) {
  return (
    <article className="runway__phase" style={stagger(i)}>
      <div className="runway__meta">
        <span className="idx">{p.phase}</span>
        {p.scope === "now" && <span className="pill pill--ok">live</span>}
      </div>
      <h3 className="runway__name">{p.name}</h3>
      <ul className="runway__list">
        {p.items.map((it) => (
          <li key={it}>{it}</li>
        ))}
      </ul>
    </article>
  );
}

export default function Landing() {
  useScrollBehaviour();

  // The veil is a full-screen opaque layer. Once it has parted it is dropped
  // from the tree for good, so nothing can ever replay it into a white-out
  // and the compositor stops carrying it.
  const [veiled, setVeiled] = useState(
    () => !window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
  const [openQ, setOpenQ] = useState(0);

  // Keep the fixed marketing nav out of the cinematic hero; it drops in once
  // the hero has largely scrolled past, so the two never fight for the top.
  //
  // At the same time this drives the scroll transformation borrowed from the
  // DeepSeek harness hero: `--hp` runs 0 → 1 across the hero's height, and CSS
  // uses it to lift, blur and fade the hero into the section below (and to
  // parallax the plate). Reduced-motion keeps `--hp` pinned at 0.
  const heroRef = useRef<HTMLElement>(null);
  const lastHidden = useRef(true);
  const [navHidden, setNavHidden] = useState(true);
  useEffect(() => {
    const hero = heroRef.current;
    if (!hero) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0;
    const update = () => {
      const h = hero.offsetHeight || window.innerHeight || 1;
      const p = reduce ? 0 : Math.min(1, Math.max(0, window.scrollY / h));
      hero.style.setProperty("--hp", p.toFixed(4));
      const hidden = window.scrollY < h - 120;
      if (hidden !== lastHidden.current) {
        lastHidden.current = hidden;
        setNavHidden(hidden);
      }
    };
    const onScroll = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, []);

  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <ScrollProgress />
      <SiteHeader hidden={navHidden} />

      <main id="main-content">
        {/* ============ CINEMATIC HERO ============ */}
        <section className="cine" id="top" ref={heroRef}>
          <h1 className="sr-only">
            re-forecast — renewable energy intelligence platform
          </h1>

          <div className="cine__camera">
            <div className="cine__stage">
              <img
                className="cine__poster"
                src="/images/hero-sunrise.webp"
                alt="A wind farm and solar field at sunrise, seen from above the cloud layer across open scrub country."
                width={1920}
                height={1280}
                fetchPriority="high"
                decoding="async"
                draggable={false}
              />
              <HeroTurbines turbines={TURBINES} />
            </div>
          </div>

          <div className="cine__weather" aria-hidden="true">
            {veiled && (
              <div className="cine__veil" onAnimationEnd={() => setVeiled(false)} />
            )}
            {BANDS.map((b) => (
              <div
                key={b.cls}
                className={`cine__band ${b.cls}`}
                style={{ "--dur": b.dur } as React.CSSProperties}
              >
                <i />
                <i />
              </div>
            ))}
          </div>

          <div className="cine__haze" aria-hidden="true" />
          <div className="cine__scrim" aria-hidden="true" />

          {/* the seam: gradient from the plate into the marketing surface */}
          <div className="cine__blend" aria-hidden="true" />

          <div className="cine__ui">
            <div className="cine__top">
              <Link to="/" className="cine__mark">
                re-forecast
              </Link>
            </div>

            <nav className="cine__nav" aria-label="Explore the platform">
              <Link to="/dashboard/forecast">
                <span className="n">01</span>
                <span className="t">Forecast</span>
              </Link>
              <a href="#manifesto">
                <span className="n">02</span>
                <span className="t">Approach</span>
              </a>
              <a href="#modules">
                <span className="n">03</span>
                <span className="t">Research</span>
              </a>
            </nav>

            <div className="cine__foot">
              <p className="cine__note">Renewable energy intelligence</p>
              <Link to="/dashboard" className="cine__cta">
                Open Dashboard
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M4.5 12h14" />
                  <path d="M12.5 5.5 19 12l-6.5 6.5" />
                </svg>
              </Link>
            </div>
          </div>

          <a className="cine__scroll" href="#console" aria-label="Scroll to explore">
            <span className="cine__scroll-line" />
            <span className="cine__scroll-txt">Scroll</span>
          </a>
        </section>

        {/* ============ MERGED MARKETING PAGE ============ */}
        <div className="landing-merge">
          {/* ---------- HERO CONSOLE ---------- */}
          <section id="console" style={{ position: "relative", paddingBottom: "var(--section)" }}>
            <div className="wrap">
              <Reveal className="reveal--console" style={{ position: "relative" }}>
                <HeroConsole />
              </Reveal>
            </div>
          </section>

          {/* ---------- CORE PRINCIPLE ---------- */}
          <section className="section" id="manifesto">
            <div className="wrap">
              <Reveal className="reveal--stagger">
                <div className="principle">
                  <header className="principle__head">
                    <span className="eyebrow">The core principle</span>
                    <p className="principle__intro">
                      One connected chain, not four separate tools. The 24–72 hour
                      forecast is the intelligence layer every other decision consumes.
                    </p>
                  </header>
                  <ol className="principle__chain">
                    {PRINCIPLE.map((s, i) => (
                      <li key={s.n} className="principle__step" style={stagger(i)}>
                        <span className="principle__idx">{s.n}</span>
                        <h3 className="principle__title">{s.t}</h3>
                        <p className="principle__body">{s.d}</p>
                        {i < PRINCIPLE.length - 1 && (
                          <span className="principle__arrow" aria-hidden="true">
                            →
                          </span>
                        )}
                      </li>
                    ))}
                  </ol>
                </div>
              </Reveal>
            </div>
          </section>

          {/* ---------- PRODUCT FLOW ---------- */}
          <section className="section" id="flow">
            <div className="wrap">
              <Reveal className="shead">
                <div className="left">
                  <span className="eyebrow">The pipeline</span>
                  <h2 className="h2">From raw data to a decision you can act on.</h2>
                  <p className="lead">
                    One connected flow — forecasting is the core intelligence layer,
                    and every other module consumes its output.
                  </p>
                </div>
              </Reveal>
              <Reveal className="reveal--stagger">
                <div className="grid grid--7">
                  {FLOW.map((s, i) => (
                    <div key={s.n} className="card" style={stagger(i, { padding: "1.3rem 1.1rem", gap: ".7rem" })}>
                      <span className="idx">{s.n}</span>
                      <h3 style={{ fontSize: "1.05rem" }}>{s.t}</h3>
                      <p style={{ fontSize: ".85rem", lineHeight: 1.5 }}>{s.d}</p>
                    </div>
                  ))}
                </div>
              </Reveal>
            </div>
          </section>

          {/* ---------- HORIZONS ---------- */}
          <section className="section" id="horizons">
            <div className="wrap">
              <Reveal className="shead">
                <div className="left">
                  <span className="eyebrow">Three planning horizons</span>
                  <h2 className="h2">Short-term operations. Seasonal reliability. Long-term investment.</h2>
                </div>
              </Reveal>
              <Reveal className="reveal--stagger">
                <div className="grid grid--3">
                  {HORIZONS.map((h, i) => (
                    <div key={h.tag} className="card" style={stagger(i)}>
                      <span className="chip chip--solid" style={{ alignSelf: "flex-start" }}>{h.tag}</span>
                      <h3>{h.title}</h3>
                      <p>{h.body}</p>
                    </div>
                  ))}
                </div>
              </Reveal>
            </div>
          </section>

          {/* ---------- THE FOUR QUESTIONS ---------- */}
          <section className="section" id="questions">
            <div className="wrap">
              <Reveal className="shead">
                <div className="left">
                  <span className="eyebrow">What the platform answers</span>
                  <h2 className="h2">Four practical questions, one connected system.</h2>
                </div>
              </Reveal>
              <Reveal className="reveal--stagger">
                <div className="qa">
                  {QUESTIONS.map((item, i) => {
                    const open = openQ === i;
                    return (
                      <div key={item.q} className={open ? "qa__item qa__item--open" : "qa__item"} style={stagger(i)}>
                        <button
                          type="button"
                          className="qa__head"
                          aria-expanded={open}
                          onClick={() => setOpenQ(open ? -1 : i)}
                        >
                          <span className="qa__n">{String(i + 1).padStart(2, "0")}</span>
                          <span className="qa__q">{item.q}</span>
                          <span className="qa__plus" aria-hidden="true">
                            +
                          </span>
                        </button>
                        <div className="qa__body">
                          <div className="qa__inner">
                            <p>{item.a}</p>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </Reveal>
            </div>
          </section>

          {/* ---------- THE SEVEN MODULES ---------- */}
          <section className="section" id="modules" style={{ background: "var(--bg-elevated)", borderTop: "1px solid var(--hairline)", borderBottom: "1px solid var(--hairline)" }}>
            <div className="wrap">
              <Reveal className="shead">
                <div className="left">
                  <span className="eyebrow">Seven modules</span>
                  <h2 className="h2">Not independent features — an interdependent chain.</h2>
                  <p className="lead">
                    Forecast feeds balance. Forecast + equipment feeds reliability.
                    Forecast + demand feeds investment. All of it converges on a single
                    decision-support dashboard.
                  </p>
                </div>
              </Reveal>
              <Reveal className="reveal--stagger">
                <div className="grid grid--3 modules">
                  {MODULES.map((m, i) => (
                    <div
                      key={m.id}
                      className={i === MODULES.length - 1 ? "card card--wide" : "card"}
                      style={stagger(i)}
                    >
                      <span className="idx">{m.id}</span>
                      <h3>{m.name}</h3>
                      <p>{m.d}</p>
                    </div>
                  ))}
                </div>
              </Reveal>
            </div>
          </section>

          {/* ---------- MVP RUNWAY ---------- */}
          <section className="section" id="mvp">
            <div className="wrap">
              <Reveal className="shead">
                <div className="left">
                  <span className="eyebrow">Build runway</span>
                  <h2 className="h2">Three phases, one forecasting core.</h2>
                </div>
              </Reveal>
              <Reveal className="reveal--stagger">
                <div className="runway">
                  <div className="runway__scope runway__scope--now" style={stagger(0)}>
                    <span className="runway__dot runway__dot--now" />
                    Current scope
                  </div>
                  {PHASES.filter((p) => p.scope === "now").map((p, i) => (
                    <PhaseBlock key={p.phase} p={p} i={i + 1} />
                  ))}
                  <div className="runway__scope runway__scope--next" style={stagger(2)}>
                    <span className="runway__dot" />
                    Future scope
                  </div>
                  {PHASES.filter((p) => p.scope === "next").map((p, i) => (
                    <PhaseBlock key={p.phase} p={p} i={i + 3} />
                  ))}
                  <span className="runway__rule runway__rule--a" aria-hidden="true" />
                  <span className="runway__rule runway__rule--b" aria-hidden="true" />
                </div>
              </Reveal>
            </div>
          </section>

          {/* ---------- CTA ---------- */}
          <CtaBand />
        </div>
      </main>

      <SiteFooter />
    </>
  );
}