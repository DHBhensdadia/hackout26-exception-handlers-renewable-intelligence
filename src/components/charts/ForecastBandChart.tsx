import { useId, useState } from "react";
import type { HourPoint } from "@/types";
import { useMeasure } from "@/hooks/useMeasure";

const fmtMw = (v: number) => (v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2));
const fmtTick = (v: number) => (Number.isInteger(v) ? v.toFixed(0) : v.toFixed(1));

/** Pretty print an hour label like 2026-09-12T14:00:00Z -> "12 Sep 14:00 UTC". */
export function hourLabel(iso: string) {
  const d = new Date(iso);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${d.getUTCDate()} ${d.toLocaleString("en", { month: "short" })} ${hh}:${mm} UTC`;
}

/** Round a value up to a clean axis maximum (1 / 1.2 / 1.5 / 2 / 2.5 / … × 10ⁿ). */
function niceMax(v: number) {
  if (!(v > 0)) return 1;
  const pow = 10 ** Math.floor(Math.log10(v));
  const steps = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];
  const n = v / pow;
  return (steps.find((s) => s >= n) ?? 10) * pow;
}

/**
 * The p10/p50/p90 forecast band chart, drawn in measured pixel coordinates so
 * strokes and labels stay true to size (no non-uniform viewBox stretching).
 * Includes value gridlines, an hourly x-axis, a capacity cap and hover readout.
 */
export function ForecastBandChart({
  points,
  capacity,
  height = 300,
}: {
  points: HourPoint[];
  capacity: number;
  height?: number;
}) {
  const n = points.length;
  const [ref, width] = useMeasure<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const gradId = useId().replace(/[:]/g, "");

  const padL = 46;
  const padR = 16;
  const padT = 16;
  const padB = 30;
  const innerW = Math.max(10, width - padL - padR);
  const innerH = Math.max(10, height - padT - padB);
  const last = Math.max(1, n - 1);

  const seriesMax = n
    ? Math.max(capacity, ...points.map((p) => Math.max(p.p90_mw, p.clearsky_mw, p.physics_mw)))
    : capacity;
  const maxV = niceMax(seriesMax * 1.08);

  const X = (i: number) => padL + (i / last) * innerW;
  const Y = (v: number) => padT + innerH * (1 - v / maxV);

  const path = (get: (p: HourPoint) => number, reverse = false) => {
    const order = Array.from({ length: n }, (_, i) => (reverse ? n - 1 - i : i));
    return order
      .map((i, k) => `${k === 0 ? "M" : "L"}${X(i).toFixed(1)} ${Y(get(points[i])).toFixed(1)}`)
      .join(" ");
  };

  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * maxV);

  const maxTicks = Math.max(2, Math.floor(innerW / 72));
  const step = Math.max(1, Math.ceil(last / Math.max(1, maxTicks - 1)));
  const xTicks: number[] = [];
  for (let i = 0; i < n; i += step) xTicks.push(i);
  if (xTicks.length && xTicks[xTicks.length - 1] !== n - 1) xTicks.push(n - 1);

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const i = Math.round(((e.clientX - rect.left - padL) / innerW) * last);
    setHover(Math.max(0, Math.min(n - 1, i)));
  };

  if (!n) return null;

  const tipLeft = hover === null ? 0 : Math.min(Math.max(X(hover), 95), Math.max(95, width - 95));

  return (
    <div className="fc-chart" ref={ref}>
      {width > 0 && (
        <svg
          className="fc-chart__svg"
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={`Forecast band chart — p10, p50, p90, clearsky and physics across ${n} hours`}
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
        >
          <defs>
            <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="rgba(94,106,210,0.32)" />
              <stop offset="100%" stopColor="rgba(94,106,210,0.03)" />
            </linearGradient>
          </defs>

          {/* horizontal grid + y labels */}
          {yTicks.map((v) => (
            <g key={v}>
              <line x1={padL} x2={width - padR} y1={Y(v)} y2={Y(v)} stroke="var(--hairline)" strokeWidth={1} />
              <text className="fc-axis" x={padL - 8} y={Y(v) + 3.5} textAnchor="end">
                {fmtTick(v)}
              </text>
            </g>
          ))}

          {/* vertical grid + x labels */}
          {xTicks.map((i) => (
            <g key={i}>
              <line
                x1={X(i)}
                x2={X(i)}
                y1={padT}
                y2={height - padB}
                stroke="var(--hairline)"
                strokeWidth={1}
                strokeDasharray="2 4"
              />
              <text
                className="fc-axis"
                x={X(i)}
                y={height - padB + 17}
                textAnchor={i === 0 ? "start" : i === n - 1 ? "end" : "middle"}
              >
                {i}h
              </text>
            </g>
          ))}

          {/* capacity cap */}
          <line
            x1={padL}
            x2={width - padR}
            y1={Y(capacity)}
            y2={Y(capacity)}
            stroke="var(--hairline-strong)"
            strokeWidth={1}
            strokeDasharray="3 4"
          />
          <text className="fc-axis fc-axis--cap" x={width - padR} y={Y(capacity) - 6} textAnchor="end">
            capacity {capacity} MW
          </text>

          {/* confidence band (p10..p90) */}
          <path d={`${path((p) => p.p90_mw)} ${path((p) => p.p10_mw, true)} Z`} fill={`url(#${gradId})`} />
          <path d={path((p) => p.p90_mw)} fill="none" stroke="var(--text-muted)" strokeWidth={1} strokeDasharray="2 3" opacity={0.75} />
          <path d={path((p) => p.p10_mw)} fill="none" stroke="var(--accent)" strokeWidth={1} opacity={0.5} />

          {/* clearsky + physics overlays */}
          <path d={path((p) => p.clearsky_mw)} fill="none" stroke="var(--c-amber)" strokeWidth={1.3} strokeDasharray="5 4" />
          <path d={path((p) => p.physics_mw)} fill="none" stroke="var(--c-blue)" strokeWidth={1.3} strokeDasharray="1.5 3" />

          {/* p50 median */}
          <path
            d={path((p) => p.p50_mw)}
            fill="none"
            stroke="var(--accent-2)"
            strokeWidth={2.2}
            strokeLinejoin="round"
            strokeLinecap="round"
          />

          {/* hover crosshair */}
          {hover !== null && (
            <g>
              <line x1={X(hover)} x2={X(hover)} y1={padT} y2={height - padB} stroke="rgba(255,255,255,0.3)" strokeWidth={1} />
              <circle cx={X(hover)} cy={Y(points[hover].p50_mw)} r={3.6} fill="var(--accent-2)" stroke="var(--bg-elevated)" strokeWidth={1.5} />
            </g>
          )}
        </svg>
      )}

      {hover !== null && width > 0 && (
        <div className="fc-tip" style={{ left: tipLeft }}>
          <div className="fc-tip__time">{hourLabel(points[hover].valid_time_utc)}</div>
          <dl className="fc-tip__grid">
            <dt>p10</dt>
            <dd>{fmtMw(points[hover].p10_mw)} MW</dd>
            <dt>p50</dt>
            <dd>{fmtMw(points[hover].p50_mw)} MW</dd>
            <dt>p90</dt>
            <dd>{fmtMw(points[hover].p90_mw)} MW</dd>
            <dt>clearsky</dt>
            <dd className="is-amber">{fmtMw(points[hover].clearsky_mw)} MW</dd>
            <dt>physics</dt>
            <dd className="is-blue">{fmtMw(points[hover].physics_mw)} MW</dd>
          </dl>
        </div>
      )}

      <div className="fc-chart__caption">
        <span>issued {hourLabel(points[0]?.valid_time_utc ?? "")}</span>
        <span>{n} h · hourly · UTC</span>
      </div>
    </div>
  );
}
