import type { ForecastResponse } from "@/types";
import { ForecastBandChart } from "./ForecastBandChart";

const LEGEND = [
  { key: "p50", label: "p50 median · expected generation", cls: "sw--line", color: "var(--accent-2)" },
  { key: "band", label: "p10 / p90 band · shortage ↔ surplus", cls: "sw--band" },
  { key: "clearsky", label: "clearsky · curtailment ceiling", cls: "sw--dash", color: "var(--c-amber)" },
  { key: "physics", label: "physics · pre-ML baseline", cls: "sw--dot", color: "var(--c-blue)" },
  { key: "cap", label: "capacity cap", cls: "sw--dash", color: "var(--hairline-strong)" },
];

/** Forecast panel — window-style frame around the band chart, with a legend. */
export function ForecastPanel({ forecast }: { forecast: ForecastResponse }) {
  const tech = forecast.tech === "solar" ? "Solar" : "Wind";
  const issue = new Date(forecast.issue_time_utc).toUTCString();

  return (
    <section className="panel2 fc">
      <header className="panel2__head">
        <div>
          <h3 className="panel2__title">{tech} forecast</h3>
          <div className="panel2__sub">
            {forecast.points.length} h horizon · {forecast.capacity_mw} MW capacity
          </div>
        </div>
        <span className="panel2__meta">issued {issue}</span>
      </header>

      <div className="fc__legend">
        {LEGEND.map((l) => (
          <span key={l.key} className="fc__key">
            <i className={`sw ${l.cls}`} style={l.color ? { color: l.color } : undefined} />
            {l.label}
          </span>
        ))}
      </div>

      <div className="panel2__body">
        <ForecastBandChart points={forecast.points} capacity={forecast.capacity_mw} />
      </div>
    </section>
  );
}
