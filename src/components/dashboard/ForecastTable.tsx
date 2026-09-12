import { useMemo, useState } from "react";
import type { ForecastResponse } from "@/types";
import type { BalanceResult } from "@/lib/derive";
import { hourLabel } from "@/lib/derive";
import { fmt } from "@/lib/format";

type SortKey = "priority" | "horizon_h" | "p10_mw" | "p50_mw" | "p90_mw" | "clearsky_mw" | "physics_mw";

const COLS: { key: SortKey; label: string; align?: "right" }[] = [
  { key: "horizon_h", label: "h" },
  { key: "p10_mw", label: "p10 (MW)", align: "right" },
  { key: "p50_mw", label: "p50 (MW)", align: "right" },
  { key: "p90_mw", label: "p90 (MW)", align: "right" },
  { key: "clearsky_mw", label: "clearsky", align: "right" },
  { key: "physics_mw", label: "physics", align: "right" },
];

/** §02 — per-hour points, ordered by decision priority by default. */
export function ForecastTable({ forecast, balance }: { forecast: ForecastResponse; balance: BalanceResult }) {
  const [sortKey, setSortKey] = useState<SortKey>("priority");
  const [dir, setDir] = useState<1 | -1>(1);

  const byTime = useMemo(
    () => new Map(balance.hours.map((h) => [h.valid_time_utc, h])),
    [balance]
  );

  const rows = useMemo(() => {
    const arr = [...forecast.points];
    if (sortKey === "priority") {
      arr.sort((a, b) => {
        const ha = byTime.get(a.valid_time_utc);
        const hb = byTime.get(b.valid_time_utc);
        if (!ha || !hb) return a.horizon_h - b.horizon_h;
        const ra = ha.unmet > 0 ? 0 : ha.state === "surplus" ? 1 : 2;
        const rb = hb.unmet > 0 ? 0 : hb.state === "surplus" ? 1 : 2;
        if (ra !== rb) return ra - rb;
        if (ra === 0) return hb.unmet - ha.unmet;
        if (ra === 1) return hb.curtailed - ha.curtailed;
        return ha.horizon_h - hb.horizon_h;
      });
    } else {
      arr.sort((a, b) => {
        const av = a[sortKey] as number;
        const bv = b[sortKey] as number;
        return av === bv ? 0 : av < bv ? -1 * dir : 1 * dir;
      });
    }
    return arr;
  }, [forecast, sortKey, dir, byTime]);

  const click = (k: SortKey) => {
    if (k === sortKey) setDir((d) => (d === 1 ? -1 : 1));
    else {
      setSortKey(k);
      setDir(1);
    }
  };

  return (
    <div className="ftable-wrap">
      <div className="ftable__bar">
        <span className="ftable__mode">
          {sortKey === "priority" ? "decision priority — deficits, then surplus, then the rest" : `sorted by ${sortKey}`}
        </span>
        {sortKey !== "priority" && (
          <button type="button" className="linkbtn" onClick={() => setSortKey("priority")}>
            reset to priority
          </button>
        )}
      </div>

      <div className="ftable__scroll">
        <table className="ftable">
          <thead>
            <tr>
              <th className="ftable__time">valid time (UTC)</th>
              <th>balance</th>
              {COLS.map((c) => (
                <th
                  key={c.key}
                  className={c.align === "right" ? "is-right" : undefined}
                  onClick={() => click(c.key)}
                  aria-sort={sortKey === c.key ? (dir === 1 ? "ascending" : "descending") : "none"}
                >
                  {c.label} {sortKey === c.key ? (dir === 1 ? "↑" : "↓") : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => {
              const h = byTime.get(p.valid_time_utc);
              const state = h?.unmet ? "bad" : h?.state === "surplus" ? "ok" : "";
              return (
                <tr key={p.valid_time_utc} className={h?.unmet ? "is-shortage" : undefined}>
                  <td>{hourLabel(p.valid_time_utc)}</td>
                  <td>
                    <span className={`tag${state ? ` tag--${state}` : ""}`}>
                      {h?.unmet ? `unmet ${fmt(h.unmet, 1)}` : (h?.state ?? "—")}
                    </span>
                  </td>
                  <td className="is-right">{p.horizon_h}</td>
                  <td className="is-right">{fmt(p.p10_mw, 2)}</td>
                  <td className="is-right ftable__p50">{fmt(p.p50_mw, 2)}</td>
                  <td className="is-right">{fmt(p.p90_mw, 2)}</td>
                  <td className="is-right is-amber">{fmt(p.clearsky_mw, 1)}</td>
                  <td className="is-right is-blue">{fmt(p.physics_mw, 1)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="panel-note">
        {rows.length} hourly points · defaults to the hours that need a decision first. Click a column to re-sort.
      </p>
    </div>
  );
}
