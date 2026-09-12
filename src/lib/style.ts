import type { CSSProperties } from "react";

/**
 * Inline custom property consumed by the landing motion CSS
 * (`animation-delay: calc(var(--i) * 75ms)`). Merge with any extra styles.
 */
export function stagger(i: number, extra?: CSSProperties): CSSProperties {
  return { "--i": i, ...extra } as CSSProperties;
}
