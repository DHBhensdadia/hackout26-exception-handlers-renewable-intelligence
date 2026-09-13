import type { ReactNode } from "react";
import {
  Activity,
  ArrowLeftRight,
  CalendarRange,
  CircleDollarSign,
  ShieldCheck,
  Target,
  Zap,
  type LucideIcon,
} from "lucide-react";
import type { ForecastResponse } from "@/types";
import type { DerivedDashboard } from "@/hooks/useDashboard";
import { useDashboardContext } from "@/hooks/useDashboardContext";
import { ModuleEmpty, ModulePage } from "./ModulePage";

export interface ModuleDef {
  to: string;
  label: string;
  n: string;
  Icon: LucideIcon;
  title: string;
  meta: string;
  /** Body-bar title; defaults to `title` when absent. */
  bar?: (ctx: { tech: string; h: number }) => string;
}

/** Sidebar order == the decision chain. */
export const MODULES: ModuleDef[] = [
  { to: "/dashboard", label: "Overview", n: "01", Icon: Target, title: "The call", meta: "decision" },
  {
    to: "/dashboard/forecast",
    label: "Forecast",
    n: "02",
    Icon: Activity,
    title: "Forecast",
    meta: "measured · xgb-q · p10/p50/p90",
    bar: ({ tech, h }) => `${tech === "wind" ? "Wind" : "Solar"} forecast — next ${h} h`,
  },
  { to: "/dashboard/balance", label: "Balance", n: "03", Icon: ArrowLeftRight, title: "Balance", meta: "modelled · generation vs demand vs storage" },
  { to: "/dashboard/reliability", label: "Reliability", n: "04", Icon: ShieldCheck, title: "Reliability", meta: "modelled · risk-only" },
  { to: "/dashboard/seasonal", label: "Seasonal", n: "05", Icon: CalendarRange, title: "Seasonal", meta: "modelled · month × hour climatology" },
  { to: "/dashboard/demand", label: "Demand", n: "06", Icon: Zap, title: "Demand & capacity", meta: "modelled · regional demand band" },
  { to: "/dashboard/investment", label: "Investment", n: "07", Icon: CircleDollarSign, title: "Investment", meta: "scenario · not advice" },
];

export type Render = (v: { forecast: ForecastResponse; derived: DerivedDashboard }) => ReactNode;

/** Shared module chrome: resolves the run state and delegates to the panel. */
export function Module({ def, children }: { def: ModuleDef; children: Render }) {
  const { result, derived, loading, error, run } = useDashboardContext();
  return (
    <ModulePage def={def}>
      {result && derived ? children({ forecast: result, derived }) : <ModuleEmpty loading={loading} error={error} onRetry={run} />}
    </ModulePage>
  );
}
