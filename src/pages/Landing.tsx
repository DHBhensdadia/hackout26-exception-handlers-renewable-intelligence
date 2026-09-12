import { Link } from "react-router-dom";
import { useScrollBehaviour } from "../components/Shell";
import { SiteHeader } from "../components/SiteNav";
import { SiteFooter } from "../components/SiteFooter";
import { CtaBand } from "../components/CtaBand";
import { Reveal } from "../components/Reveal";
import { HeroConsole } from "../components/HeroConsole";
import { Button, ArrowIcon } from "../components/ui";

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

const SCENARIO = [
  { n: "01", t: "Weather + history + equipment ingested", d: "Open-Meteo NWP and historical plant output for the region." },
  { n: "02", t: "Forecast the next 72 hours", d: "The core model predicts solar + wind output hourly." },
  { n: "03", t: "High solar in afternoon detected", d: "Generation exceeds demand during several peak hours." },
  { n: "04", t: "Platform flags surplus", d: "Available battery capacity is checked against the surplus window." },
  { n: "05", t: "Charge storage, quantify curtailment", d: "Recommended dispatch, plus the residual over-generation that would be curtailed." },
  { n: "06", t: "Same surplus recurs each summer", d: "Seasonal analysis turns a one-off flag into a systematic pattern." },
  { n: "07", t: "Industrial demand growing", d: "Demand forecasting shows load will grow over the next five years." },
  { n: "08", t: "Scenarios evaluated against ₹500 cr", d: "Solar, wind, storage and hybrid options scored on ROI, risk and capacity adequacy." },
  { n: "09", t: "Dashboard presents the strategy", d: "Best generation + storage allocation, with trade-offs explained." },
];

const PHASES = [
  { tag: "Phase 1 · Core MVP", l: "Historical generation · weather ingestion · 24–72 h solar/wind forecast · surplus/shortage detection · basic dashboard", on: true },
  { tag: "Phase 2 · Operational Intelligence", l: "Demand forecasting · storage-aware recommendations · seasonal pattern analysis · reliability/failure analysis" },
  { tag: "Phase 3 · Strategic Planning", l: "Population/industrial demand forecasting · investment comparison · ROI analysis · storage analysis · budget optimization · what-if scenarios" },
];

const STACK = [
  "React", "TypeScript", "Vite", "Tailwind CSS",
  "Python 3.12", "FastAPI", "Pydantic",
  "Pandas", "NumPy", "XGBoost",
  "PostgreSQL", "Redis", "Celery",
  "Google OR-Tools", "Open-Meteo", "Docker",
];

export default function Landing() {
  useScrollBehaviour();

  return (
    <>
      <SiteHeader />

      {/* ============ HERO ============ */}
      <section className="hero hero--app" id="top">
        <div className="hero__shader" />
        <div className="hero__glow" />
        <div className="hero__word" aria-hidden="true">re-forecast</div>

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
              <Button to="#approach" variant="ghost">
                Explore the platform
              </Button>
            </div>
          </div>

          {/* Spec strip of core capability numbers */}
          <div className="specstrip reveal d2">
            <div className="cell">
              <div className="num"><em>24–72</em> h</div>
              <div className="lbl">forecast horizon</div>
            </div>
            <div className="cell">
              <div className="num"><em>solar</em> + <em>wind</em></div>
              <div className="lbl">technologies modelled</div>
            </div>
            <div className="cell">
              <div className="num"><em>p10 · p50 · p90</em></div>
              <div className="lbl">calibrated quantile bands</div>
            </div>
            <div className="cell">
              <div className="num"><em>6</em> models</div>
              <div className="lbl">2 tech × 3 quantiles (xgb-q)</div>
            </div>
          </div>
        </div>
      </section>

      {/* ============ HERO CONSOLE ============ */}
      <section style={{ position: "relative", paddingBottom: "var(--section)" }}>
        <div className="wrap">
          <Reveal className="load s4" style={{ position: "relative" }}>
            <HeroConsole />
          </Reveal>
          <div style={{ display: "flex", justifyContent: "center", marginTop: "2.2rem" }}>
            <span className="reveal d1" style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: ".78rem", letterSpacing: ".04em" }}>
              Live dashboard → <Link to="/dashboard" className="linkarrow">open the forecast console <ArrowIcon /></Link>
            </span>
          </div>
        </div>
      </section>

      {/* ============ MANIFESTO ============ */}
      <section className="section" id="manifesto">
        <div className="wrap">
          <div className="manifesto reveal">
            <span className="manifesto__rule" />
            <p className="manifesto__line">
              Predict power &nbsp;<em>→</em>&nbsp; optimize its use &nbsp;<em>→</em>&nbsp;
              understand future needs &nbsp;<em>→</em>&nbsp; invest efficiently.
            </p>
            <span className="manifesto__rule" />
          </div>
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
          <Reveal>
            <div className="grid grid--7" style={{ gridTemplateColumns: "repeat(7, 1fr)" }}>
              {FLOW.map((s) => (
                <div key={s.n} className="card" style={{ padding: "1.3rem 1.1rem", gap: ".7rem" }}>
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
          <Reveal>
            <div className="grid grid--3">
              {HORIZONS.map((h) => (
                <div key={h.tag} className="card">
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
          <Reveal>
            <div className="steps">
              {[
                ["What will we generate?", "Forecast solar and wind output for the next 24–72 hours with honest uncertainty."],
                ["What should we do with that power?", "Surplus or shortage — charge storage, hold backup, or curtail only when necessary."],
                ["What risks should we prepare for?", "Recurring seasonal patterns, equipment failure risk, low-generation windows."],
                ["Where should we invest next?", "Future demand, generation potential, economics and storage constraints converge on a recommendation."],
              ].map(([q, a]) => (
                <div key={q} className="step">
                  <span className="n">0{q ? "" : ""}</span>
                  <div>
                    <h3>{q}</h3>
                    <p>{a}</p>
                  </div>
                </div>
              ))}
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
          <Reveal>
            <div className="grid grid--3">
              {MODULES.map((m) => (
                <div key={m.id} className="card">
                  <span className="idx">{m.id}</span>
                  <h3>{m.name}</h3>
                  <p>{m.d}</p>
                </div>
              ))}
            </div>
          </Reveal>
        </div>
      </section>

      {/* ============ APPROACH / PRINCIPLE ============ */}
      <section className="section" id="approach">
        <div className="wrap">
          <div className="feature-row">
            <div className="feature-row__text">
              <Reveal>
                <span className="eyebrow">Uncertainty, not guarantees</span>
                <h2 className="h2">The forecast is never a single number.</h2>
                <p className="lead">
                  A single MW value hides the only thing that determines action. The
                  model returns three quantiles — p10, p50, p90 — so a decision-maker
                  sees both the median and how wide the outcome could be.
                </p>
                <ul className="ticklist" style={{ marginTop: "1rem" }}>
                  <li><strong>p10 — pessimistic:</strong> truth above this 90% of the time. Shortage risk, backup scheduling.</li>
                  <li><strong>p50 — median:</strong> the forecast. Expected generation.</li>
                  <li><strong>p90 — optimistic:</strong> truth below this 90% of the time. Surplus risk, storage sizing.</li>
                </ul>
              </Reveal>
            </div>
            <div className="feature-row__media">
              <Reveal>
                <div className="code-card" style={{ boxShadow: "var(--shadow-md)" }}>
                  <div className="code-card__bar">
                    <span className="code-card__file">POST /forecast · response</span>
                  </div>
                  <div className="code-card__body">
                    <pre>{`{
  "site_id": "GJ-SOLAR-CHARANKA",
  "tech": "solar",
  "issue_time_utc": "2026-09-12T00:00:00Z",
  "capacity_mw": 50.0,
  "model_version": "xgb-q-0.1.0",
  "weather_source": "openmeteo:icon_seamless",
  "location_is_estimated": false,
  "points": [
    { "valid_time_utc": "2026-09-12T01:00:00Z",
      "horizon_h": 1,
      "p10_mw": 7.17, "p50_mw": 18.56,
      "p90_mw": 27.71,
      "clearsky_mw": 44.64,
      "physics_mw": 25.67 }
  ]
}`}</pre>
                  </div>
                </div>
              </Reveal>
            </div>
          </div>
        </div>
      </section>

      {/* ============ END-TO-END SCENARIO ============ */}
      <section className="section" id="scenario">
        <div className="wrap">
          <Reveal className="shead">
            <div className="left">
              <span className="eyebrow">End-to-end scenario</span>
              <h2 className="h2">A ₹500 crore budget, one connected decision.</h2>
              <p className="lead">
                A region with solar and wind, limited storage, rising industrial
                demand, and a future investment budget — the platform walks the whole
                question from a 72-hour forecast to a long-term allocation.
              </p>
            </div>
          </Reveal>
          <Reveal>
            <div className="steps">
              {SCENARIO.map((s) => (
                <div key={s.n} className="step">
                  <span className="n">{s.n}</span>
                  <div>
                    <h3>{s.t}</h3>
                    <p>{s.d}</p>
                  </div>
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
          <Reveal>
            <div className="steps">
              {PHASES.map((p) => (
                <div key={p.tag} className="step">
                  <span className="n">{p.tag.split("·")[1]?.trim() ?? p.tag}</span>
                  <div>
                    <h3 style={{ display: "flex", alignItems: "center", gap: ".6rem" }}>
                      {p.on && <span className="pill pill--ok">live</span>} {p.tag}
                    </h3>
                    <p>{p.l}</p>
                  </div>
                </div>
              ))}
            </div>
          </Reveal>
        </div>
      </section>

      {/* ============ TECH STACK ============ */}
      <section className="section" id="stack">
        <div className="wrap">
          <Reveal className="shead">
            <div className="left">
              <span className="eyebrow">Technology stack</span>
              <h2 className="h2">Built to grow from one plant to state-level planning.</h2>
            </div>
          </Reveal>
          <Reveal>
            <div style={{ display: "flex", flexWrap: "wrap", gap: ".6rem" }}>
              {STACK.map((t) => (
                <span key={t} className="chip">{t}</span>
              ))}
            </div>
          </Reveal>
        </div>
      </section>

      {/* ============ CTA ============ */}
      <CtaBand />

      <SiteFooter />
    </>
  );
}