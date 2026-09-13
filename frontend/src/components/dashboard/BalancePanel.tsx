import type { ForecastResponse } from "@/types";
import type { DerivedDashboard } from "@/hooks/useDashboard";
import { hourLabel } from "@/lib/derive";
import { Cell, CellGrid } from "../ui/CellGrid";
import { BalanceChart } from "./BalanceChart";

/** §03 — Module 2: generation · demand · storage balance (spec §8, §14). */
export function BalancePanel({ forecast, derived }: { forecast: ForecastResponse; derived: DerivedDashboard }) {
  const { balance, storage } = derived;
  const n = balance.hours.length;

  return (
    <>
      <CellGrid columns={4}>
        <Cell
          k="Surplus hours"
          v={`${balance.surplusHours} / ${n}`}
          note={`${balance.surplusEnergy} MWh above demand`}
          accent="var(--c-green)"
        />
        <Cell
          k="Shortage hours"
          v={`${balance.shortageHours} / ${n}`}
          note={`${balance.shortageEnergy} MWh below demand`}
          accent="var(--c-red)"
        />
        <Cell k="Stored" v={`${balance.chargeEnergy} MWh`} note={`${balance.curtailEnergy} MWh curtailed beyond storage`} />
        <Cell
          k="Unmet demand"
          v={`${balance.unmetEnergy} MWh`}
          note="after storage discharge"
          accent={balance.unmetEnergy > 0.5 ? "var(--c-red)" : "var(--c-green)"}
        />
      </CellGrid>

      <BalanceChart hours={balance.hours} capacity={forecast.capacity_mw} storage={storage} />

      <div className="notes-grid">
        <div className="note-row">
          <span className="note-row__k">Worst deficit</span>
          <span className="note-row__v">
            {balance.worstShortage ? (
              <>
                {hourLabel(balance.worstShortage.valid_time_utc)} ·{" "}
                {Math.abs(balance.worstShortage.net).toFixed(1)} MW gap · {balance.worstShortage.unmet} MWh unmet after
                discharge
              </>
            ) : (
              "No deficit within the horizon."
            )}
          </span>
        </div>
        <div className="note-row">
          <span className="note-row__k">Storage sizing</span>
          <span className="note-row__v">
            {balance.curtailEnergy > 0.5
              ? `${balance.curtailEnergy} MWh would exceed the ${storage.capacity_mwh} MWh installed here. Sizing on p50 overflows half the time — p90 sets the honest requirement.`
              : `No curtailment inside the horizon — the ${storage.capacity_mwh} MWh installed absorbs every surplus hour. Sizing on p50 still under-provisions the wider p90 band; plan storage against p90.`}
          </span>
        </div>
        <div className="note-row">
          <span className="note-row__k">Recommended dispatch</span>
          <span className="note-row__v">
            {balance.verdict.action}. Charge windows: {balance.chargeEnergy} MWh; discharge covers{" "}
            {balance.shortageEnergy - balance.unmetEnergy > 0 ? (balance.shortageEnergy - balance.unmetEnergy).toFixed(1) : "0"}{" "}
            MWh of the deficit.
          </span>
        </div>
      </div>
    </>
  );
}
