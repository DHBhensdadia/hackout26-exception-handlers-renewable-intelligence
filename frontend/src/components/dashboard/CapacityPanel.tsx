import type { DerivedDashboard } from "@/hooks/useDashboard";
import { Cell, CellGrid } from "../ui/CellGrid";

/** §06 — Module 6: future demand & capacity planning (spec §12). */
export function CapacityPanel({ derived }: { derived: DerivedDashboard }) {
  const { years, growthPct, capacityGapMw, requiredStorageMwh, note } = derived.capacity;
  const max = Math.max(...years.map((y) => Math.max(y.demand, y.capacity)), 1);

  return (
    <>
      <CellGrid columns={4}>
        <Cell k="Demand growth" v={`${growthPct} %/yr`} note="population + industrial expansion" />
        <Cell
          k="Capacity gap"
          v={`${capacityGapMw} MW`}
          note="by end of horizon"
          accent={capacityGapMw > 0 ? "var(--c-amber)" : "var(--c-green)"}
        />
        <Cell k="Required storage" v={`${requiredStorageMwh} MWh`} note="2-day p90 surplus reserve" />
        <Cell k="Installed now" v={`${years[0].capacity} MW`} note="renewable capacity" />
      </CellGrid>

      <div className="cap">
        {years.map((y) => (
          <div className="cap__row" key={y.year}>
            <span className="cap__y">{y.year}</span>
            <div className="cap__track">
              <i className="cap__fill" style={{ width: `${(y.demand / max) * 100}%` }} />
              <i className="cap__cap" style={{ left: `${(y.capacity / max) * 100}%` }} />
            </div>
            <span className="cap__v">{y.demand} MW</span>
            <span className={`cap__g${y.gap > 0 ? " cap__g--gap" : ""}`}>
              {y.gap > 0 ? `+${y.gap} MW gap` : "covered"}
            </span>
          </div>
        ))}
      </div>

      <p className="panel-note">{note} Capacity is planned against the upper demand band, not the median.</p>
    </>
  );
}
