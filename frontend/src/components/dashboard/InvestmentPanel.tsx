import { useMemo, useState } from "react";
import type { DerivedDashboard } from "@/hooks/useDashboard";
import { investmentScenarios, type Allocation } from "@/lib/derive";

const allocClass: Record<Allocation["tech"], string> = {
  Solar: "alloc--solar",
  Wind: "alloc--wind",
  Storage: "alloc--storage",
};

/** §07 — Modules 5 & 7: investment scenarios against a budget (spec §11, §13, §27). */
export function InvestmentPanel({ derived }: { derived: DerivedDashboard }) {
  const [budget, setBudget] = useState(500);
  const scenarios = useMemo(
    () => investmentScenarios(budget, derived.site, derived.balance.demandMetPct),
    [budget, derived.site, derived.balance.demandMetPct]
  );
  const recommended = scenarios.find((s) => s.recommended) ?? scenarios[0];

  return (
    <>
      <div className="invest__controls">
        <label className="cp__field">
          <div className="cp__label">
            <span className="cp__label-t">Available budget</span>
            <span className="cp__hint">₹ crore · what-if</span>
          </div>
          <input
            className="cp__range"
            type="range"
            min={100}
            max={1000}
            step={50}
            value={budget}
            onChange={(e) => setBudget(Number(e.target.value))}
          />
          <div className="cp__ticks">
            <span>₹100 cr</span>
            <span className="cp__ticks-mid">₹{budget} cr</span>
            <span>₹1000 cr</span>
          </div>
        </label>
        <div className="invest__rec">
          <span className="tag tag--accent">recommended</span>
          <span className="invest__rec-name">
            Scenario {recommended.key} — {recommended.name}
          </span>
          <span className="invest__rec-note">
            {recommended.demand_met_pct}% demand met · {recommended.roi_pct}% ROI · {recommended.payback_yr} yr payback
          </span>
        </div>
      </div>

      <div className="scenario-list">
        {scenarios.map((s) => (
          <article key={s.key} className={`scenario${s.recommended ? " scenario--rec" : ""}`}>
            <div className="scenario__id">
              <header className="scenario__head">
                <span className="scenario__key">{s.key}</span>
                <h4 className="scenario__name">{s.name}</h4>
                {s.recommended && <span className="tag tag--accent">recommended</span>}
              </header>

              <div className="scenario__mix" aria-label="Budget allocation">
                {s.allocation.map((a) => (
                  <i
                    key={a.tech}
                    className={`alloc ${allocClass[a.tech]}`}
                    style={{ width: `${a.pct}%` }}
                    title={`${a.tech} · ₹${a.cr} cr`}
                  />
                ))}
              </div>
            </div>

            <dl className="scenario__stats">
              <div>
                <dt>solar</dt>
                <dd>{s.solar_mw} MW</dd>
              </div>
              <div>
                <dt>wind</dt>
                <dd>{s.wind_mw} MW</dd>
              </div>
              <div>
                <dt>storage</dt>
                <dd>{s.storage_mwh} MWh</dd>
              </div>
              <div>
                <dt>annual gen</dt>
                <dd>{s.annual_gen_gwh} GWh</dd>
              </div>
              <div>
                <dt>demand met</dt>
                <dd>{s.demand_met_pct}%</dd>
              </div>
              <div>
                <dt>ROI</dt>
                <dd>{s.roi_pct}%</dd>
              </div>
              <div>
                <dt>payback</dt>
                <dd>{s.payback_yr} yr</dd>
              </div>
              <div>
                <dt>risk</dt>
                <dd className={`risk risk--${s.risk.tone}`}>{s.risk.label}</dd>
              </div>
            </dl>
          </article>
        ))}
      </div>

      <p className="panel-note">
        Scenario comparison on a ₹{budget} cr budget — modelled costs and returns, not a guaranteed financial
        forecast. Storage is included in every scenario that carries it; siting and timing are out of scope here.
      </p>
    </>
  );
}
