import { Fragment, useState } from "react";
import type { SeasonalResult } from "@/lib/derive";

const HOURS = Array.from({ length: 24 }, (_, h) => h);
const pad = (h: number) => String(h).padStart(2, "0");

/**
 * §05 — the month × hour climatology. One cell per pair, fill keyed to the
 * median residual (green surplus, amber shortage), on the console's hairline
 * rhythm. Hover or focus a cell for the exact figure.
 */
export function SeasonalHeatGrid({ seasonal }: { seasonal: SeasonalResult }) {
  const { months, cells } = seasonal;
  const [active, setActive] = useState<{ m: number; h: number } | null>(null);

  const byKey = new Map(cells.map((c) => [`${c.month}-${c.hour}`, c]));
  const maxAbs = Math.max(...cells.map((c) => Math.abs(c.residual_mwh)), 1);

  const cellStyle = (residual: number) => {
    const mag = Math.min(1, Math.abs(residual) / maxAbs);
    if (residual <= 0 && mag < 0.02) return undefined;
    const rgb = residual > 0 ? "76,183,130" : "226,163,60";
    return { background: `rgba(${rgb},${(0.1 + 0.6 * mag).toFixed(3)})` };
  };

  const activeCell = active ? byKey.get(`${active.m}-${active.h}`) : null;

  return (
    <div className="heatwrap">
      <div className="heat-scroll">
        <div className="heat" role="grid" aria-label="Recurring surplus by month and hour">
          <div className="heat__corner" />
          {HOURS.map((h) => (
            <div className="heat__hcol" key={h}>
              {h % 3 === 0 ? pad(h) : ""}
            </div>
          ))}

          {months.map((m, mi) => (
            <Fragment key={m.month}>
              <div className="heat__row">{m.month}</div>
              {HOURS.map((h) => {
                const c = byKey.get(`${mi}-${h}`);
                const res = c?.residual_mwh ?? 0;
                const surplus = Math.round((c?.surplus_pct ?? 0) * 100);
                return (
                  <button
                    key={h}
                    type="button"
                    role="gridcell"
                    className="heat__cell"
                    style={cellStyle(res)}
                    aria-label={`${m.month} ${pad(h)}:00 — ${res > 0 ? "surplus" : "shortage"} ${Math.abs(res)} MW median, surplus in ${surplus} % of hours`}
                    onMouseEnter={() => setActive({ m: mi, h })}
                    onFocus={() => setActive({ m: mi, h })}
                  />
                );
              })}
            </Fragment>
          ))}
        </div>
      </div>

      <p className="heat__read" aria-live="polite">
        {activeCell
          ? `${months[activeCell.month].month} ${pad(activeCell.hour)}:00 · ${
              activeCell.residual_mwh > 0 ? "surplus" : "shortage"
            } ${Math.abs(activeCell.residual_mwh)} MW median · surplus in ${Math.round(
              activeCell.surplus_pct * 100
            )} % of hours`
          : "Hover or focus a cell for the recurring pattern."}
      </p>

      <div className="chart-legend">
        <span>
          <i className="sw" style={{ background: "rgba(76,183,130,.6)", border: 0, height: 8 }} /> recurring surplus
        </span>
        <span>
          <i className="sw" style={{ background: "rgba(226,163,60,.6)", border: 0, height: 8 }} /> recurring shortage
        </span>
      </div>
    </div>
  );
}
