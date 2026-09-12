export interface SectionDef {
  id: string;
  n: string;
  label: string;
}

/** The decision console's reading order. */
export const SECTIONS: SectionDef[] = [
  { id: "s-call", n: "01", label: "The call" },
  { id: "s-forecast", n: "02", label: "Forecast" },
  { id: "s-balance", n: "03", label: "Balance" },
  { id: "s-reliability", n: "04", label: "Reliability" },
  { id: "s-seasonal", n: "05", label: "Seasonal" },
  { id: "s-capacity", n: "06", label: "Demand & capacity" },
  { id: "s-investment", n: "07", label: "Investment" },
];
