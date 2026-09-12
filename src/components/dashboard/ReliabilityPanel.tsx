import type { ForecastResponse } from "@/types";
import type { DerivedDashboard } from "@/hooks/useDashboard";
import { Cell, CellGrid } from "../ui/CellGrid";

const toneColor = (tone: "ok" | "warn" | "bad") =>
  tone === "bad" ? "var(--c-red)" : tone === "warn" ? "var(--c-amber)" : "var(--c-green)";

/** §04 — Module 4: equipment reliability & failure risk (spec §10). */
export function ReliabilityPanel({ forecast, derived }: { forecast: ForecastResponse; derived: DerivedDashboard }) {
  const r = derived.reliability;
  const start = r.maintenanceWindow ? r.maintenanceWindow.start.replace(" UTC", "") : "—";

  return (
    <>
      <CellGrid columns={4}>
        <Cell k="Risk index" v={r.risk.toFixed(2)} note={`${r.band} band`} accent={toneColor(r.tone)} />
        <Cell k="Generation at risk" v={`≈${r.expectedLossMwh} MWh`} note="over this horizon" />
        <Cell k="Maintenance slot" v={start} note={r.maintenanceWindow?.label ?? "horizon too short"} />
        <Cell k="Horizon scored" v={`${forecast.points.length} h`} note="risk evaluated hourly" />
      </CellGrid>

      <div className="rows">
        {r.drivers.map((d) => (
          <div className="row" key={d.label}>
            <span className="row__k">{d.label}</span>
            <span className="row__v">{d.value}</span>
            <span className="row__n">{d.note}</span>
          </div>
        ))}
      </div>

      <p className="panel-note">{r.note}</p>
    </>
  );
}
