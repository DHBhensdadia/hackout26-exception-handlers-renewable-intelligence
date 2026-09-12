import { useId } from "react";

type Orientation = "horizontal" | "vertical";

interface DashedLineProps {
  orientation?: Orientation;
  /** Anchor edge inside a positioned parent. */
  edge?: "top" | "bottom" | "left" | "right";
  className?: string;
}

/**
 * Fine dashed hairline drawn with an SVG pattern (2px dash / 4px gap) so the
 * dash rhythm matches across the whole grid, regardless of element length.
 */
export function DashedLine({ orientation = "horizontal", edge, className }: DashedLineProps) {
  const uid = useId().replace(/[:]/g, "");
  const cls = ["dl", `dl--${orientation}`, edge ? `dl--${edge}` : "", className ?? ""].filter(Boolean).join(" ");

  if (orientation === "horizontal") {
    const pid = `dl-h-${uid}`;
    return (
      <svg className={cls} width="100%" height="1" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <pattern id={pid} x="0" y="0" width="6" height="1" patternUnits="userSpaceOnUse">
          <line x1="0" y1="0.5" x2="2" y2="0.5" stroke="currentColor" strokeWidth="1" />
        </pattern>
        <rect width="100%" height="1" fill={`url(#${pid})`} />
      </svg>
    );
  }

  const pid = `dl-v-${uid}`;
  return (
    <svg className={cls} width="1" height="100%" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <pattern id={pid} x="0" y="0" width="1" height="6" patternUnits="userSpaceOnUse">
        <line x1="0.5" y1="0" x2="0.5" y2="2" stroke="currentColor" strokeWidth="1" />
      </pattern>
      <rect width="1" height="100%" fill={`url(#${pid})`} />
    </svg>
  );
}
