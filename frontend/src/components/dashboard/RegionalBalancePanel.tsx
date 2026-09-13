import { useEffect, useState } from "react";
import { isAbortError, regionalBalance } from "@/api/client";
import type { BalanceResponse, SiteRecord } from "@/types";
import { Cell, CellGrid } from "../ui/CellGrid";

/**
 * §03a — the regional balance, computed by the backend.
 *
 * This is the platform's actual decision layer, as opposed to the site-level panel below
 * it: real metered regional demand, a 200-scenario coherent ensemble across every plant in
 * the region, and surplus/shortage stated as calibrated probabilities rather than as a
 * comparison of two point forecasts.
 *
 * Two things are deliberately visible rather than hidden. The window is a replay of real
 * history, because the demand model needs load at the issue time and the market ingest
 * lags the calendar - so the panel says which window and says it is a replay. And because
 * it *is* history, the outcome is known, so the panel shows how often the band actually
 * contained it. A probability that is never checked against an outcome is decoration.
 */
interface Fetched {
  region: string;
  data: BalanceResponse | null;
  error: string | null;
}

export function RegionalBalancePanel({ site, horizonH }: { site: SiteRecord; horizonH: number }) {
  // Result and the region it belongs to are held together. Keeping them in separate pieces
  // of state forced a synchronous clear inside the effect on every region change, which
  // cascades renders; pairing them means a stale result is simply not the current region's
  // and can be ignored at render time instead.
  const [fetched, setFetched] = useState<Fetched | null>(null);
  const region = site.region;

  useEffect(() => {
    if (!region) return;
    const ctrl = new AbortController();
    let live = true;
    regionalBalance(region, horizonH, ctrl.signal)
      .then((d) => live && setFetched({ region, data: d, error: null }))
      .catch((e: unknown) => {
        if (!live || isAbortError(e)) return;
        setFetched({
          region,
          data: null,
          error: e instanceof Error ? e.message : "Balance unavailable.",
        });
      });
    return () => {
      live = false;
      ctrl.abort();
    };
  }, [region, horizonH]);

  // Derived rather than stored. A separate `loading` flag would have to be set
  // synchronously inside the effect, which cascades renders; "no result yet for the region
  // being shown" is the same information and needs no state at all.
  const current = fetched?.region === region ? fetched : null;
  const data = current?.data ?? null;
  const error = current?.error ?? null;
  const loading = Boolean(region) && current === null;

  if (!region) {
    return (
      <p className="module-note">
        {site.name} sits outside the NEM, so there is no regional demand series to balance it
        against. Pick an Australian site to see the regional balance.
      </p>
    );
  }
  if (loading && !data) return <p className="module-note">Loading regional balance for {region}…</p>;
  if (error) return <p className="module-note">Regional balance unavailable — {error}</p>;
  if (!data) return null;

  const points = data.points;
  const actualByTime = new Map(data.actual.map((a) => [a.valid_time_utc, a]));

  const surplusHours = points.filter((p) => p.p_surplus >= 0.5).length;
  const shortageHours = points.filter((p) => p.p_shortage >= 0.5).length;
  const surplusEnergy = points.reduce((a, p) => a + p.expected_surplus_mwh, 0);
  const shortageEnergy = points.reduce((a, p) => a + p.expected_shortage_mwh, 0);

  // The replay's one advantage over a live forecast: the answer is known.
  const checked = points.filter((p) => actualByTime.has(p.valid_time_utc));
  const inside = checked.filter((p) => {
    const a = actualByTime.get(p.valid_time_utc)!;
    return a.renewable_mw >= p.renewable_p10_mw && a.renewable_mw <= p.renewable_p90_mw;
  }).length;
  const coverage = checked.length ? Math.round((100 * inside) / checked.length) : null;

  const peakSurplus = points.reduce((b, p) => (p.p_surplus > (b?.p_surplus ?? -1) ? p : b), points[0]);

  return (
    <>
      <CellGrid columns={4}>
        <Cell
          k="Surplus hours"
          v={`${surplusHours} / ${points.length}`}
          note={`${Math.round(surplusEnergy).toLocaleString()} MWh expected`}
          accent="var(--c-green)"
        />
        <Cell
          k="Shortage hours"
          v={`${shortageHours} / ${points.length}`}
          note={`${Math.round(shortageEnergy).toLocaleString()} MWh expected`}
          accent={shortageHours > 0 ? "var(--c-red)" : undefined}
        />
        <Cell
          k="Dispatchable headroom"
          v={`${Math.round(data.dispatchable_headroom_mw).toLocaleString()} MW`}
          note="measured, not assumed"
        />
        <Cell
          k="Band held"
          v={coverage === null ? "—" : `${coverage}%`}
          note="actual inside p10–p90 · nominal 80%"
          accent={coverage !== null && coverage >= 70 && coverage <= 92 ? "var(--c-green)" : undefined}
        />
      </CellGrid>

      <div className="notes-grid">
        <div className="note-row">
          <span className="note-row__k">Region</span>
          <span className="note-row__v">
            {data.region} · {data.technologies.join(" + ")} · {data.n_scenarios} scenarios
          </span>
        </div>
        <div className="note-row">
          <span className="note-row__k">Window</span>
          <span className="note-row__v">
            {data.data_mode === "replay" ? "Replay · " : ""}
            {data.issue_time_utc.replace("T", " ").replace("Z", " UTC")} + {points.length} h
          </span>
        </div>
        {peakSurplus && peakSurplus.p_surplus > 0.01 && (
          <div className="note-row">
            <span className="note-row__k">Peak surplus risk</span>
            <span className="note-row__v">
              {Math.round(peakSurplus.p_surplus * 100)}% at{" "}
              {peakSurplus.valid_time_utc.slice(11, 16)} UTC ·{" "}
              {Math.round(peakSurplus.conditional_surplus_mw).toLocaleString()} MW if it occurs
            </span>
          </div>
        )}
      </div>

      {data.events.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Event</th>
              <th>From (UTC)</th>
              <th>Hours</th>
              <th>Peak probability</th>
              <th>Expected energy</th>
            </tr>
          </thead>
          <tbody>
            {data.events.map((e) => (
              <tr key={`${e.kind}-${e.from_utc}`}>
                <td style={{ color: e.kind === "surplus" ? "var(--c-green)" : "var(--c-red)" }}>
                  {e.kind}
                </td>
                <td>{e.from_utc.replace("T", " ").replace("Z", "")}</td>
                <td>{e.hours}</td>
                <td>{Math.round(e.peak_probability * 100)}%</td>
                <td>{Math.round(e.energy_mwh).toLocaleString()} MWh</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <p className="module-note">{data.data_note}</p>
    </>
  );
}
