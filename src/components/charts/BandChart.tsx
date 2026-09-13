import { useId, useState } from "react";
import { useMeasure } from "@/hooks/useMeasure";

/** One p10–p90 band with its p50 line. */
export interface BandSeries {
  label: string;
  /** p50 stroke. */
  color: string;
  /** p10–p90 area fill. */
  fill: string;
  /** Optional p90 edge stroke (defaults to `color` at low opacity). */
  edge?: string;
  points: { p10: number; p50: number; p90: number }[];
}

export interface BandReference {
  value: number;
  label: string;
  color?: string;
}

const fmtTick = (v: number) => (Number.isInteger(v) ? v.toFixed(0) : v.toFixed(1));

/** Round a value up to a clean axis maximum (1 / 1.2 / 1.5 / 2 / 2.5 / … × 10ⁿ). */
function niceMax(v: number) {
  if (!(v > 0)) return 1;
  const pow = 10 ** Math.floor(Math.log10(v));
  const steps = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];
  const n = v / pow;
  return (steps.find((s) => s >= n) ?? 10) * pow;
}

/**
 * The shared band grammar: one or more p10–p90 bands with p50 lines on a single
 * measured-pixel axis, an optional reference rule, and a hover readout.
 * Drawn in real pixel coordinates, like ForecastBandChart — no viewBox stretch.
 */
export function BandChart({
  series,
  height = 260,
  reference = null,
  xLabel = (i) => `${i}h`,
  tipTitle,
  tipRows,
  ariaLabel,
  unit = "MW",
}: {
  series: BandSeries[];
  height?: number;
  reference?: BandReference | null;
  xLabel?: (i: number) => string;
  tipTitle?: (i: number) => string;
  tipRows?: (i: number) => [string, string, string?][];
  ariaLabel: string;
  unit?: string;
}) {
  const first = series[0];
  const n = first?.points.length ?? 0;
  const [ref, width] = useMeasure<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const gradId = useId().replace(/[:]/g, "");

  const padL = 52;
  const padR = 16;
  const padT = 18;
  const padB = 30;
  const innerW = Math.max(10, width - padL - padR);
  const innerH = Math.max(10, height - padT - padB);
  const last = Math.max(1, n - 1);

  const seriesMax = Math.max(
    1,
    ...series.flatMap((s) => s.points.map((p) => p.p90)),
    reference?.value ?? 0
  );
  const maxV = niceMax(seriesMax * 1.06);

  const X = (i: number) => padL + (i / last) * innerW;
  const Y = (v: number) => padT + innerH * (1 - v / maxV);

  const line = (get: (i: number) => number, reverse = false) => {
    const order = Array.from({ length: n }, (_, i) => (reverse ? n - 1 - i : i));
    return order.map((i, k) => `${k === 0 ? "M" : "L"}${X(i).toFixed(1)} ${Y(get(i)).toFixed(1)}`).join(" ");
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

  const tipLeft = hover === null ? 0 : Math.min(Math.max(X(hover), 105), Math.max(105, width - 105));
  const rows = hover !== null ? tipRows?.(hover) ?? [] : [];

  return (
    <div className="fc-chart" ref={ref}>
      {width > 0 && (
        <svg
          className="fc-chart__svg"
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={ariaLabel}
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
        >
          <defs>
            {series.map((s, si) => (
              <linearGradient id={`${gradId}-${si}`} key={s.label} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={s.fill} />
                <stop offset="100%" stopColor="rgba(0,0,0,0)" />
              </linearGradient>
            ))}
          </defs>

          {yTicks.map((v) => (
            <g key={v}>
              <line x1={padL} x2={width - padR} y1={Y(v)} y2={Y(v)} stroke="var(--hairline)" strokeWidth={1} />
              <text className="fc-axis" x={padL - 8} y={Y(v) + 3.5} textAnchor="end">
                {fmtTick(v)}
              </text>
            </g>
          ))}

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
                {xLabel(i)}
              </text>
            </g>
          ))}

          {reference && (
            <g>
              <line
                x1={padL}
                x2={width - padR}
                y1={Y(reference.value)}
                y2={Y(reference.value)}
                stroke={reference.color ?? "var(--c-red)"}
                strokeWidth={1}
                strokeDasharray="3 4"
              />
              <text className="fc-axis fc-axis--cap" x={width - padR} y={Y(reference.value) - 6} textAnchor="end">
                {reference.label}
              </text>
            </g>
          )}

          {series.map((s, si) => (
            <g key={s.label}>
              <path
                d={`${line((i) => s.points[i].p90)} ${line((i) => s.points[i].p10, true)} Z`}
                fill={`url(#${gradId}-${si})`}
              />
              <path
                d={line((i) => s.points[i].p90)}
                fill="none"
                stroke={s.edge ?? s.color}
                strokeWidth={1}
                strokeDasharray="2 3"
                opacity={0.7}
              />
              <path d={line((i) => s.points[i].p50)} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" />
            </g>
          ))}

          {hover !== null && (
            <line x1={X(hover)} x2={X(hover)} y1={padT} y2={height - padB} stroke="rgba(255,255,255,0.3)" strokeWidth={1} />
          )}
        </svg>
      )}

      {hover !== null && width > 0 && (
        <div className="fc-tip" style={{ left: tipLeft }}>
          <div className="fc-tip__time">{tipTitle?.(hover) ?? xLabel(hover)}</div>
          <dl className="fc-tip__grid">
            {rows.map(([k, v, tone]) => (
              <div key={k} style={{ display: "contents" }}>
                <dt>{k}</dt>
                <dd className={tone ? `is-${tone}` : undefined}>
                  {v} {unit}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      <div className="chart-legend">
        {series.map((s) => (
          <span key={s.label}>
            <i className="sw sw--line" style={{ color: s.color }} /> {s.label}
          </span>
        ))}
        {reference && (
          <span>
            <i className="sw sw--dot" style={{ color: reference.color ?? "var(--c-red)" }} /> {reference.label}
          </span>
        )}
      </div>
    </div>
  );
}
