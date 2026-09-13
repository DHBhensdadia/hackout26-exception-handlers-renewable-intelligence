import { useState } from "react";
import { useScrollBehaviour } from "../components/Shell";
import { SiteHeader } from "../components/SiteNav";
import { SiteFooter } from "../components/SiteFooter";
import { ScrollProgress } from "../components/ScrollProgress";
import { CtaBand } from "../components/CtaBand";
import { Reveal } from "../components/Reveal";
import { HeroConsole } from "../components/HeroConsole";
import { Button } from "../components/ui";
import { stagger } from "@/lib/style";

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
  const [openQ, setOpenQ] = useState(0);

  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <ScrollProgress />
      <SiteHeader />

      <main id="main-content">
      {/* ============ HERO ============ */}
      <section className="hero hero--app" id="top">
        <div className="hero__shader" />
        <div className="hero__glow" />

        <div className="wrap">
          <div className="hero__body">
            <span className="eyebrow reveal">Renewable Energy Intelligence Platform</span>
            <h1 className="display load s1">
              Forecast renewable power.
              <br />
              Decide <em className="accent-text">what to do</em> with it.
            </h1>
            <p className="lead hero__sub load s2">
              An AI-driven decision-support platform that forecasts solar and wind
              generation 24–72 hours ahead, then uses that forecast — with demand,
              storage, equipment and economic data — to recommend operational actions
              and long-term renewable investment.
            </p>
            <div className="hero__actions load s3">
              <Button to="/dashboard">Launch dashboard</Button>
            </div>
          </div>

          {/* Spec strip of core capability numbers */}
          <div className="specstrip reveal reveal--stagger d2">
            <div className="cell" style={stagger(0)}>
              <span className="eyebrow">Forecast horizon</span>
              <div className="num"><em>24–72</em> h</div>
              <div className="lbl">Three days ahead, issued hourly</div>
              <p className="body">
                Hourly solar and wind output for the next three days, reissued as
                each new weather run lands — long enough to schedule storage and
                backup, short enough to stay accurate.
              </p>
              <ul className="meta">
                <li>Hourly resolution</li>
                <li>72 h look-ahead</li>
                <li>Uncertainty bands</li>
              </ul>
            </div>
            <div className="cell" style={stagger(1)}>
              <span className="eyebrow">Technologies modelled</span>
              <div className="num"><em>solar</em> + <em>wind</em></div>
              <div className="lbl">Site-calibrated, technology-specific models</div>
              <p className="body">
                Separate solar and wind models, calibrated per site against
                geometry, installed capacity and equipment characteristics —
                driven by weather, physics priors and historical generation.
              </p>
              <ul className="meta">
                <li>Physics-informed priors</li>
                <li>Site-calibrated</li>
                <li>Weather-driven</li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* ============ HERO CONSOLE ============ */}
      <section style={{ position: "relative", paddingBottom: "var(--section)" }}>
        <div className="wrap">
          <Reveal className="reveal--console" style={{ position: "relative" }}>
            <HeroConsole />
          </Reveal>
        </div>
      </section>

      {/* ============ CORE PRINCIPLE ============ */}
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

      {/* ============ PRODUCT FLOW ============ */}
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

      {/* ============ HORIZONS ============ */}
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

      {/* ============ THE FOUR QUESTIONS ============ */}
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

      {/* ============ THE SEVEN MODULES ============ */}
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

      {/* ============ MVP RUNWAY ============ */}
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

      {/* ============ CTA ============ */}
      <CtaBand />
      </main>

      <SiteFooter />
    </>
  );
}