import type { ReactNode } from "react";

/**
 * Ruled cell grid — 1px hairlines separate the cells (no rounded cards).
 * The cell count collapses 4 → 2 on small screens; use `.cells--wide` spans
 * on individual cells for emphasis.
 */
export function CellGrid({
  columns = 4,
  tone = "base",
  className,
  children,
}: {
  columns?: number;
  tone?: "base" | "elevated";
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={`cells cells--${tone}${className ? ` ${className}` : ""}`}
      style={{ "--cells-n": columns } as React.CSSProperties}
    >
      {children}
    </div>
  );
}

export function Cell({
  k,
  v,
  note,
  accent,
  span,
}: {
  k: ReactNode;
  v: ReactNode;
  note?: ReactNode;
  accent?: string;
  span?: number;
}) {
  return (
    <div className="cell" style={span ? { gridColumn: `span ${span}` } : undefined}>
      <div className="cell__k">{k}</div>
      <div className="cell__v" style={accent ? { color: accent } : undefined}>
        {v}
      </div>
      {note && <div className="cell__n">{note}</div>}
    </div>
  );
}
