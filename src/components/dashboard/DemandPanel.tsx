import type { RegionRecord } from "@/types";
import type { DemandResult } from "@/lib/derive";
import { hourLabel } from "@/lib/derive";
import { fact } from "@/lib/format";
import { Cell, CellGrid } from "../ui/CellGrid";
import { BandChart, type BandSeries } from "../charts/BandChart";
import { RegionPicker } from "./RegionPicker";

const hhmm = (iso: string) => {
  const d = new Date(iso);
  return `${String(d.getUTCHours()).padStart(2, "0")}:00`;
};
const nmaeTone = (v: number) => (v < 2.5 ? "ok" : v < 4 ? "warn" : "bad");
const covTone = (v: number) => (v >= 80 ? "ok" : v >= 70 ? "warn" : "bad");
const band = (points: { p10_mw: number; p50_mw: number; p90_mw: number }[]) =>
  points.map((p) => ({ p10: p.p10_mw, p50: p.p50_mw, p90: p.p90_mw }));

/**
 * §06 — Module 6: regional demand (spec §12). Demand is drawn with the same
 * band grammar as generation, mirrored in blue on one shared axis, and the
 * panel is explicit about where the model is weak.
 */
export function DemandPanel({
  demand,
  region,
  regions,
  regionId,
  onRegion,
  loading,
  error,
}: {
  demand: DemandResult | null;
  region: RegionRecord | null;
  regions: RegionRecord[];
  regionId: string;
  onRegion: (id: string) => void;
  loading: boolean;
  error: string | null;
}) {
  const series: BandSeries[] = demand
    ? [
        {
          label: "Regional renewables · p10–p90",
          color: "var(--accent-2)",
          fill: "rgba(94,106,210,.16)",
          points: band(demand.renewable_band),
        },
        {
          label: "Demand · p10–p90",
          color: "var(--c-blue)",
          fill: "rgba(78,167,252,.18)",
          points: band(demand.points),
        },
      ]
    : [];

  const max = demand ? Math.max(...demand.plan.years.map((y) => Math.max(y.demand, y.renewable)), 1) : 1;

  return (
    <>
      <div className="regional__bar">
        <RegionPicker regions={regions} value={regionId} onChange={onRegion} />
        {demand && <span className="tag tag--accent">POST /demand · not built</span>}
        {demand && (
          <span className="tag">
            {demand.source === "api" ? "api" : "modelled"} · {demand.model_version}
          </span>
        )}
      </div>

      {!demand ? (
        <div className="module__empty" role={error ? "alert" : "status"}>
          <span className="module__empty-k">{error ? "error" : loading ? "running" : "idle"}</span>
          <p>{error ?? (loading ? "Loading the regional demand model…" : "Select a region.")}</p>
        </div>
      ) : (
        <>
          <p className="regional__lead">
            Demand peaks {hhmm(demand.peak.valid_time_utc)} at {fact(demand.peak.p50_mw)} MW —{" "}
            {demand.peak_margin_mw >= 0
              ? `${fact(demand.peak_margin_mw)} MW below the ${fact(demand.headroom_mw)} MW dispatchable headroom`
              : `${fact(-demand.peak_margin_mw)} MW above the ${fact(demand.headroom_mw)} MW dispatchable headroom`}
            . Region {demand.region_id} · {demand.data_mode} run.
          </p>

          <BandChart
            series={series}
            height={280}
            ariaLabel={`Regional demand and renewable bands for ${demand.region_id}, next ${demand.points.length} hours`}
            reference={{ value: demand.headroom_mw, label: `headroom ${fact(demand.headroom_mw)} MW` }}
            xLabel={(i) => `${i}h`}
            tipTitle={(i) => hourLabel(demand.points[i].valid_time_utc)}
            tipRows={(i) => [
              ["renew p50", fact(demand.renewable_band[i].p50_mw), "amber"],
              ["demand p10", fact(demand.points[i].p10_mw), "blue"],
              ["demand p50", fact(demand.points[i].p50_mw), "blue"],
              ["demand p90", fact(demand.points[i].p90_mw), "blue"],
            ]}
          />

          <CellGrid columns={4}>
            <Cell k="Peak demand" v={`${fact(demand.peak.p50_mw)} MW`} note={`${hhmm(demand.peak.valid_time_utc)} · p50`} />
            <Cell
              k="Peak vs headroom"
              v={`${demand.peak_margin_mw >= 0 ? "−" : "+"}${fact(Math.abs(demand.peak_margin_mw))} MW`}
              note={demand.peak_margin_mw >= 0 ? "dispatchable margin at peak" : "peak outruns dispatchable headroom"}
              accent={demand.peak_margin_mw >= 0 ? "var(--c-green)" : "var(--c-red)"}
            />
            <Cell k="Mean demand" v={`${fact(demand.mean_mw)} MW`} note={`${demand.points.length} h horizon`} />
            <Cell k="Regional renewables" v={`${fact(demand.renewable_mw)} MW`} note="solar + wind installed" />
          </CellGrid>

          <div className="rtable">
            <div className="rtable__head">
              <span>Region</span>
              <span>Name</span>
              <span>nMAE</span>
              <span>Coverage</span>
              <span>Note</span>
            </div>
            {regions.map((r) => (
              <button
                key={r.region_id}
                type="button"
                className={r.region_id === regionId ? "rtable__row on" : "rtable__row"}
                onClick={() => onRegion(r.region_id)}
              >
                <span className="rtable__id">{r.region_id}</span>
                <span>{r.name}</span>
                <span className={`rtable__n rtable__n--${nmaeTone(r.nmae_pct)}`}>{r.nmae_pct} %</span>
                <span className={`rtable__n rtable__n--${covTone(r.coverage_pct)}`}>{r.coverage_pct} %</span>
                <span className={r.caveat ? "rtable__caveat" : "rtable__muted"}>
                  {r.caveat ?? (r.balance_available ? "balance available" : "forecast only")}
                </span>
              </button>
            ))}
          </div>

          <div className="cap">
            {demand.plan.years.map((y) => (
              <div className="cap__row" key={y.year}>
                <span className="cap__y">{y.year}</span>
                <div className="cap__track">
                  <i className="cap__fill" style={{ width: `${(y.demand / max) * 100}%` }} />
                  <i className="cap__cap" style={{ left: `${(y.renewable / max) * 100}%` }} />
                </div>
                <span className="cap__v">{fact(y.demand)} MW</span>
                <span className={`cap__g${y.gap > 0 ? " cap__g--gap" : ""}`}>
                  {y.gap > 0 ? `+${fact(y.gap)} MW gap` : `${fact(Math.abs(y.gap))} MW margin`}
                </span>
              </div>
            ))}
          </div>

          <p className="panel-note">
            {demand.plan.note} Demand is a regional model — the site figures in §01–§04 are independent of this panel.
          </p>
          {region?.caveat && <p className="panel-note panel-note--warn">{region.caveat}</p>}
        </>
      )}
    </>
  );
}
