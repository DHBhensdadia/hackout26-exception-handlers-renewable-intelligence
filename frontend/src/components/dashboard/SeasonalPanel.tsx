import type { RegionRecord } from "@/types";
import type { SeasonalResult } from "@/lib/derive";
import { fact } from "@/lib/format";
import { Cell, CellGrid } from "../ui/CellGrid";
import { RegionPicker } from "./RegionPicker";
import { SeasonalHeatGrid } from "./SeasonalHeatGrid";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const pad = (h: number) => String(h).padStart(2, "0");

/**
 * §05 — Module 3: seasonal pattern analysis (spec §9). The recurring
 * month × hour surplus, computed for real from the regional climatology, and
 * the storage it would take to absorb it (spec §18's bridge).
 */
export function SeasonalPanel({
  seasonal,
  regions,
  regionId,
  onRegion,
}: {
  seasonal: SeasonalResult | null;
  regions: RegionRecord[];
  regionId: string;
  onRegion: (id: string) => void;
}) {
  if (!seasonal) return null;
  const { peak, months } = seasonal;

  return (
    <>
      <div className="regional__bar">
        <RegionPicker regions={regions} value={regionId} onChange={onRegion} />
        <span className="tag tag--accent">GET /seasonal · cut</span>
        <span className="tag">modelled · {seasonal.window_years}-y window</span>
      </div>

      <p className="regional__lead">{seasonal.headline}</p>

      <CellGrid columns={4}>
        <Cell
          k="Peak window"
          v={`${MONTHS[peak.month]} ${pad(peak.hour)}:00`}
          note={`+${fact(peak.residual_mwh)} MW median`}
          accent="var(--c-green)"
        />
        <Cell
          k="Recurring surplus"
          v={`${fact(seasonal.recurring_surplus_hours)} h/yr`}
          note={`${fact(seasonal.recurring_surplus_mwh)} MWh/yr`}
        />
        <Cell
          k="Storage to absorb"
          v={`${fact(seasonal.storage_to_absorb_mwh)} MWh`}
          note="shift each day's surplus into its deficit"
        />
        <Cell k="Climatology window" v={`${seasonal.window_years} years`} note={seasonal.source} />
      </CellGrid>

      <SeasonalHeatGrid seasonal={seasonal} />

      <div className="notes-grid">
        <div className="note-row">
          <span className="note-row__k">How to read it</span>
          <span className="note-row__v">
            One cell per month × hour pair, median residual across {seasonal.window_years} years. Green recurs in
            surplus, amber in shortage. Storage is sized on the month that needs it most, and bounded by that month's
            deficit — you only build storage for energy the region can use.
          </span>
        </div>
        <div className="note-row">
          <span className="note-row__k">Month means</span>
          <span className="note-row__v">
            {months.map((m) => `${m.month} ${m.residual > 0 ? "+" : ""}${m.residual}`).join("  ·  ")} MW
          </span>
        </div>
        <div className="note-row">
          <span className="note-row__k">Source gap</span>
          <span className="note-row__v">
            <code>GET /seasonal/&#123;region&#125;</code> is cut, so this grid is computed in the client from a
            deterministic three-year climatology. A served version would read the AEMO history already on disk.
          </span>
        </div>
      </div>
    </>
  );
}
