import { useMemo, useState } from "react";
import type { ForecastResponse } from "@/types";
import { hourLabel } from "@/components/charts/ForecastBandChart";
import { fmt } from "@/lib/format";

/**
 * Per-hour forecast table — mirrors the /forecast response points array.
 * Sortable by any column, with a band indicator.
 */
export function ForecastTable({ forecast }: { forecast: ForecastResponse }) {
  const [sortKey, setSortKey] = useState<"horizon_h" | "p10_mw" | "p50_mw" | "p90_mw" | "clearsky_mw" | "physics_mw">("horizon_h");
  const [dir, setDir] = useState<1 | -1>(1);

  const rows = useMemo(() => {
    const arr = [...forecast.points];
    arr.sort((a, b) => {
      const av = a[sortKey] as number;
      const bv = b[sortKey] as number;
      return av === bv ? 0 : av < bv ? -1 * dir : 1 * dir;
    });
    return arr;
  }, [forecast, sortKey, dir]);

  const cols: { key: typeof sortKey; label: string; align?: "right" }[] = [
    { key: "horizon_h", label: "H" },
    { key: "p10_mw", label: "p10 (MW)", align: "right" },
    { key: "p50_mw", label: "p50 (MW)", align: "right" },
    { key: "p90_mw", label: "p90 (MW)", align: "right" },
    { key: "clearsky_mw", label: "clearsky", align: "right" },
    { key: "physics_mw", label: "physics", align: "right" },
  ];

  const clickCol = (k: typeof sortKey) => {
    if (k === sortKey) setDir((d) => (d === 1 ? -1 : 1));
    else {
      setSortKey(k);
      setDir(1);
    }
  };

  const max = Math.max(...forecast.points.map((p) => p.p90_mw), 1);

  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: ".8rem", fontFamily: "var(--font-mono)" }}>
        <thead>
          <tr>
            <th style={{ textAlign: "left", padding: ".5rem .6rem", borderBottom: "1px solid var(--hairline-strong)", color: "var(--text-muted)", fontSize: ".66rem", textTransform: "uppercase", letterSpacing: ".07em" }}>
              valid time (UTC)
            </th>
            {cols.map((c) => (
              <th
                key={c.key}
                onClick={() => clickCol(c.key)}
                style={{
                  textAlign: c.align === "right" ? "right" : "left",
                  padding: ".5rem .6rem",
                  borderBottom: "1px solid var(--hairline-strong)",
                  color: sortKey === c.key ? "var(--text)" : "var(--text-muted)",
                  fontSize: ".66rem",
                  textTransform: "uppercase",
                  letterSpacing: ".07em",
                  cursor: "pointer",
                  whiteSpace: "nowrap",
                  userSelect: "none",
                }}
                title="Sort"
              >
                {c.label} {sortKey === c.key ? (dir === 1 ? "↑" : "↓") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.valid_time_utc} style={{ transition: "background .15s" }}>
              <td style={{ padding: ".42rem .6rem", borderBottom: "1px solid var(--hairline)", color: "var(--text-secondary)", whiteSpace: "nowrap" }}>
                {hourLabel(p.valid_time_utc)}
              </td>
              <td style={{ padding: ".42rem .6rem", borderBottom: "1px solid var(--hairline)", textAlign: "right", color: "var(--text-secondary)" }}>
                {fmt(p.p10_mw, 2)}
              </td>
              <td style={{ padding: ".42rem .6rem", borderBottom: "1px solid var(--hairline)", textAlign: "right", color: "var(--text)", fontWeight: 600 }}>
                {fmt(p.p50_mw, 2)}
              </td>
              <td style={{ padding: ".42rem .6rem", borderBottom: "1px solid var(--hairline)", textAlign: "right", color: "var(--text-secondary)" }}>
                {fmt(p.p90_mw, 2)}
              </td>
              <td style={{ padding: ".42rem .6rem", borderBottom: "1px solid var(--hairline)", textAlign: "right", color: "var(--c-amber)" }}>
                {fmt(p.clearsky_mw, 1)}
              </td>
              <td style={{ padding: ".42rem .6rem", borderBottom: "1px solid var(--hairline)", textAlign: "right", color: "var(--c-blue)" }}>
                {fmt(p.physics_mw, 1)}
                <span
                  style={{
                    display: "inline-block",
                    width: p.p90_mw / max * 40,
                    height: 4,
                    borderRadius: 2,
                    background: "var(--c-blue)",
                    marginLeft: 8,
                    verticalAlign: "middle",
                    opacity: 0.5,
                  }}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}