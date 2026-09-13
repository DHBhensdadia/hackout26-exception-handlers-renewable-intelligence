import type { ForecastResponse } from "@/types";
import type { DerivedDashboard } from "@/hooks/useDashboard";
import { Cell, CellGrid } from "../ui/CellGrid";

/**
 * §04 — Module 4: operating conditions, and the gap where a reliability model would be.
 *
 * The panel previously led with a "Risk index" and "Generation at risk", both derived from
 * a hash of the site id. They are gone. What is shown instead is what can honestly be read
 * off the forecast — how hard the plant is being driven and when it is quietest — plus a
 * plain statement of why there is no risk score, because an absence explained reads as
 * rigour and an absence papered over reads as a number.
 */
export function ReliabilityPanel({
  forecast,
  derived,
}: {
  forecast: ForecastResponse;
  derived: DerivedDashboard;
}) {
  const r = derived.reliability;

  return (
    <>
      <CellGrid columns={4}>
        {r.signals.map((s) => (
          <Cell key={s.label} k={s.label} v={s.value} note={s.note} />
        ))}
        <Cell
          k="Quietest window"
          v={r.maintenanceWindow ? r.maintenanceWindow.start : "—"}
          note={
            r.maintenanceWindow
              ? `${r.windowLossMwh} MWh forgone over 4 h`
              : "horizon too short"
          }
          accent="var(--c-blue)"
        />
      </CellGrid>

      <div className="notes-grid">
        <div className="note-row">
          <span className="note-row__k">Horizon</span>
          <span className="note-row__v">
            {forecast.points.length} h · conditions read from the forecast series
          </span>
        </div>
        <div className="note-row">
          <span className="note-row__k">Maintenance</span>
          <span className="note-row__v">
            {r.maintenanceWindow
              ? `${r.maintenanceWindow.start} to ${r.maintenanceWindow.end} — ${r.maintenanceWindow.label}`
              : "No window inside this horizon."}
          </span>
        </div>
      </div>

      <p className="module-note">{r.unavailable}</p>
    </>
  );
}
