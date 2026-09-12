import { useId, useState } from "react";
import type { HourPoint } from "@/types";

const fmt = (v: number) => {
  if (v >= 1000) return v.toFixed(0);
  if (v >= 100) return v.toFixed(1);
  return v.toFixed(2);
};

/** Pretty print an hour label like 2026-09-12T14:00:00Z -> "12 Sep 14:00". */
export function hourLabel(iso: string) {
  const d = new Date(iso);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${d.getUTCDate()} ${d.toLocaleString("en", { month: "short" })} ${hh}:${mm} UTC`;
}

/** X-axis tick labels — every `step` hours, starting at 0. */
function xTicks(n: number, step: number) {
  const out: number[] = [];
  for (let i = 0; i < n; i += step) out.push(i);
  if (out[out.length - 1] !== n - 1) out.push(n - 1);
  return out;
}

/**
 * The p10/p50/p90 forecast band chart. Draws a shaded confidence band,
 * the median line, clearsky/physics overlays, and a capacity cap.
 */
export function ForecastBandChart({
  points,
  capacity,
  height = 280,
}: {
  points: HourPoint[];
  capacity: number;
  height?: number;
}) {
  const n = points.length;
  const W = 100; // normalized width units 0..100
  const padL = 6;
  const padR = 2;
  const padT = 14;
  const padB = 26;
  const innerW = W - padL - padR;
  const innerH = height - padT - padB;
  const x = (i: number) => padL + (i / (n - 1)) * innerW;
  const maxV = Math.max(capacity, ...points.map((p) => Math.max(p.p50_mw, p.clearsky_mw)));
  const scale = capacity / maxV;
  const yY = (v: number) => padT + innerH * (1 - (v / maxV) * scale);

  const ticks = xTicks(n, Math.max(1, Math.round(n / 12)));

  const [hover, setHover] = useState<number | null>(null);

  // Paths
  const line = (get: (p: HourPoint) => number) =>
    points.map((p, i) => (i === 0 ? "M" : "L") + x(i).toFixed(2) + " " + yY(get(p)).toFixed(2)).join(" ");

  const lineRev = (get: (p: HourPoint) => number) =>
    points
      .slice()
      .reverse()
      .map((p, i) => "L" + x(n - 1 - i).toFixed(2) + " " + yY(get(p)).toFixed(2))
      .join(" ");

  const gradId = useId().replace(/:/g, "");

  return (
    <div style={{ position: "relative", width: "100%" }}>
      <svg
        viewBox={`0 0 ${W} ${height}`}
        preserveAspectRatio="none"
        style={{ width: "100%", height, display: "block" }}
        role="img"
        aria-label={`Forecast band chart — p10, p50, p90, clearsky and physics across ${n} hours`}
      >
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="rgba(94,106,210,0.30)" />
            <stop offset="100%" stopColor="rgba(94,106,210,0.04)" />
          </linearGradient>
        </defs>

        {/* capacity cap */}
        <line x1={padL} y1={yY(capacity)} x2={W - padR} y2={yY(capacity)} stroke="var(--hairline-strong)" strokeDasharray="2 4" strokeWidth={0.5} />
        <text x={padL} y={yY(capacity) - 2} fontSize={3.4} fill="var(--text-muted)" fontFamily="var(--font-mono)">
          cap {capacity} MW
        </text>

        {/* grid */}
        {ticks.map((t) => (
          <line key={t} x1={x(t)} y1={padT} x2={x(t)} y2={height - padB} stroke="var(--hairline)" strokeWidth={0.5} />
        ))}

        {/* shaded confidence band (p10..p90) */}
        <path d={`${line((p) => p.p90_mw)} ${lineRev((p) => p.p10_mw)} Z`} fill={`url(#${gradId})`} />
        {/* p10 lower */}
        <path d={line((p) => p.p10_mw)} fill="none" stroke="rgba(94,106,210,0.6)" strokeWidth={0.5} />
        {/* p90 upper */}
        <path d={line((p) => p.p90_mw)} fill="none" stroke="var(--text-muted)" strokeWidth={0.4} strokeDasharray="0.5 2" />

        {/* clearsky + physics overlays */}
        <path d={line((p) => p.clearsky_mw)} fill="none" stroke="var(--c-amber)" strokeWidth={0.7} strokeDasharray="3 2" />
        <path d={line((p) => p.physics_mw)} fill="none" stroke="var(--c-blue)" strokeWidth={0.5} strokeDasharray="1 2" />

        {/* p50 median */}
        <path d={line((p) => p.p50_mw)} fill="none" stroke="var(--accent-2)" strokeWidth={1.1} />

        {/* hover crosshair */}
        {hover !== null && (
          <g>
            <line x1={x(hover)} y1={padT} x2={x(hover)} y2={height - padB} stroke="rgba(255,255,255,0.25)" strokeWidth={0.5} />
            <circle cx={x(hover)} cy={yY(points[hover].p50_mw)} r={2.2} fill="var(--accent-2)" stroke="#fff" strokeWidth={0.4} />
          </g>
        )}

        {/* x labels */}
        {ticks.map((t) => (
          <text key={t} x={x(t)} y={height - 10} fontSize={3.4} fill="var(--text-muted)" textAnchor="middle" fontFamily="var(--font-mono)">
            {t}h
          </text>
        ))}
        <text x={padL} y={height - 2} fontSize={3.2} fill="var(--text-muted)" fontFamily="var(--font-mono)">
          issued {hourLabel(points[0]?.valid_time_utc ?? "")} UTC
        </text>

        {/* invisible hover bars */}
        {points.map((p, i) => (
          <rect
            key={p.valid_time_utc}
            x={i === 0 ? padL : x(i) - innerW / (n - 1) / 2}
            y={padT}
            width={innerW / (n - 1)}
            height={innerH}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
          />
        ))}
      </svg>

      {hover !== null && (
        <div
          style={{
            position: "absolute",
            top: padT + 2,
            left: `${((x(hover) / W) * 100).toFixed(2)}%`,
            transform: "translateX(-50%)",
            background: "var(--bg-elevated)",
            border: "1px solid var(--hairline-strong)",
            borderRadius: 8,
            padding: "8px 10px",
            fontSize: 12,
            lineHeight: 1.6,
            pointerEvents: "none",
            zIndex: 5,
            boxShadow: "var(--shadow-md)",
            minWidth: 150,
          }}
        >
          <div style={{ color: "var(--text)", fontWeight: 600 }}>
            {hourLabel(points[hover].valid_time_utc)}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "auto auto", gap: "0 14px", color: "var(--text-secondary)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
            <span>p10</span><b style={{ color: "var(--text)" }}>{fmt(points[hover].p10_mw)} MW</b>
            <span>p50</span><b style={{ color: "var(--text)" }}>{fmt(points[hover].p50_mw)} MW</b>
            <span>p90</span><b style={{ color: "var(--text)" }}>{fmt(points[hover].p90_mw)} MW</b>
            <span>clearsky</span><b style={{ color: "var(--c-amber)" }}>{fmt(points[hover].clearsky_mw)} MW</b>
            <span>physics</span><b style={{ color: "var(--c-blue)" }}>{fmt(points[hover].physics_mw)} MW</b>
          </div>
        </div>
      )}
    </div>
  );
}