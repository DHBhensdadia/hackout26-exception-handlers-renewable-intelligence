import type { BalanceHour, StorageModel } from "@/lib/derive";
import { useMeasure } from "@/hooks/useMeasure";

const fmtTick = (v: number) => (Number.isInteger(v) ? v.toFixed(0) : v.toFixed(1));

/** §03 chart — generation band vs expected demand, with a storage SoC strip. */
export function BalanceChart({
  hours,
  capacity,
  storage,
  height = 250,
}: {
  hours: BalanceHour[];
  capacity: number;
  storage: StorageModel;
  height?: number;
}) {
  const n = hours.length;
  const [ref, width] = useMeasure<HTMLDivElement>();

  const padL = 46;
  const padR = 14;
  const padT = 14;
  const socH = 16;
  const padB = socH + 24;
  const innerW = Math.max(10, width - padL - padR);
  const plotH = Math.max(20, height - padT - padB);
  const last = Math.max(1, n - 1);

  const maxV = Math.max(capacity, ...hours.map((h) => Math.max(h.gen_p90, h.demand)), 1) * 1.05;
  const X = (i: number) => padL + (i / last) * innerW;
  const Y = (v: number) => padT + plotH * (1 - v / maxV);

  const line = (get: (h: BalanceHour) => number) =>
    hours.map((h, i) => `${i ? "L" : "M"}${X(i).toFixed(1)} ${Y(get(h)).toFixed(1)}`).join(" ");

  const band = [
    ...hours.map((h, i) => `${i ? "L" : "M"}${X(i).toFixed(1)} ${Y(h.gen_p90).toFixed(1)}`),
    ...hours
      .slice()
      .reverse()
      .map((h, k) => `L${X(n - 1 - k).toFixed(1)} ${Y(h.gen_p10).toFixed(1)}`),
    "Z",
  ].join(" ");

  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * maxV);
  const maxTicks = Math.max(2, Math.floor(innerW / 72));
  const step = Math.max(1, Math.ceil(last / Math.max(1, maxTicks - 1)));
  const xTicks: number[] = [];
  for (let i = 0; i < n; i += step) xTicks.push(i);
  if (xTicks.length && xTicks[xTicks.length - 1] !== n - 1) xTicks.push(n - 1);

  const barW = (innerW / Math.max(1, last)) * 0.62;
  const socBottom = padT + plotH + 6 + socH;

  if (!n) return null;

  return (
    <div className="bchart" ref={ref}>
      {width > 0 && (
        <svg
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label="Forecast generation versus expected demand, with storage state of charge below"
        >
          {/* surplus / shortage column tints */}
          {hours.map((h, i) => (
            <rect
              key={`t${h.i}`}
              x={X(i) - barW / 2}
              y={padT}
              width={barW}
              height={plotH}
              fill={h.state === "surplus" ? "rgba(76,183,130,.06)" : "rgba(235,94,87,.07)"}
            />
          ))}

          {/* y grid + labels */}
          {yTicks.map((v) => (
            <g key={v}>
              <line x1={padL} x2={width - padR} y1={Y(v)} y2={Y(v)} stroke="var(--hairline)" strokeWidth={1} />
              <text className="fc-axis" x={padL - 8} y={Y(v) + 3.5} textAnchor="end">
                {fmtTick(v)}
              </text>
            </g>
          ))}

          {/* x grid + labels */}
          {xTicks.map((i) => (
            <g key={i}>
              <line
                x1={X(i)}
                x2={X(i)}
                y1={padT}
                y2={padT + plotH}
                stroke="var(--hairline)"
                strokeWidth={1}
                strokeDasharray="2 4"
              />
              <text
                className="fc-axis"
                x={X(i)}
                y={socBottom + 13}
                textAnchor={i === 0 ? "start" : i === n - 1 ? "end" : "middle"}
              >
                {hours[i].horizon_h}h
              </text>
            </g>
          ))}

          {/* generation band + p50 */}
          <path d={band} fill="rgba(94,106,210,.16)" />
          <path d={line((h) => h.gen_p50)} fill="none" stroke="var(--accent-2)" strokeWidth={2} strokeLinejoin="round" />

          {/* expected demand */}
          <path d={line((h) => h.demand)} fill="none" stroke="var(--text-secondary)" strokeWidth={1.4} strokeDasharray="5 4" />

          {/* storage SoC strip */}
          {hours.map((h, i) => {
            const frac = Math.max(0, Math.min(1, h.soc_mwh / Math.max(1, storage.capacity_mwh)));
            const top = padT + plotH + 6 + socH - frac * socH;
            return (
              <rect
                key={`s${h.i}`}
                x={X(i) - barW / 2}
                y={top}
                width={barW}
                height={frac * socH}
                fill="rgba(76,183,130,.5)"
              />
            );
          })}
          <line
            x1={padL}
            x2={width - padR}
            y1={socBottom}
            y2={socBottom}
            stroke="var(--hairline)"
            strokeWidth={1}
          />
        </svg>
      )}

      <div className="chart-legend">
        <span>
          <i className="sw sw--line" style={{ color: "var(--accent-2)" }} /> generation p50 (band p10–p90)
        </span>
        <span>
          <i className="sw sw--dash" style={{ color: "var(--text-secondary)" }} /> expected demand
        </span>
        <span>
          <i className="sw" style={{ background: "rgba(76,183,130,.5)", border: 0, height: 8 }} /> storage state of charge
        </span>
      </div>
    </div>
  );
}
