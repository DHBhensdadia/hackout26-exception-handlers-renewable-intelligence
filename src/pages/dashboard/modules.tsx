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
import { DecisionCallout } from "@/components/dashboard/DecisionCallout";
import { ForecastPanel } from "@/components/charts/ForecastPanel";
import { ForecastTable } from "@/components/dashboard/ForecastTable";
import { BalancePanel } from "@/components/dashboard/BalancePanel";
import { ReliabilityPanel } from "@/components/dashboard/ReliabilityPanel";
import { SeasonalPanel } from "@/components/dashboard/SeasonalPanel";
import { CapacityPanel } from "@/components/dashboard/CapacityPanel";
import { InvestmentPanel } from "@/components/dashboard/InvestmentPanel";
import { ModuleEmpty, ModulePage } from "./ModulePage";

export interface ModuleDef {
  to: string;
  label: string;
  n: string;
  Icon: LucideIcon;
  title: string;
  meta: string;
}

/** Sidebar order == the decision chain. */
export const MODULES: ModuleDef[] = [
  { to: "/dashboard", label: "Overview", n: "01", Icon: Target, title: "The call", meta: "decision" },
  { to: "/dashboard/forecast", label: "Forecast", n: "02", Icon: Activity, title: "Forecast", meta: "measured · xgb-q · p10/p50/p90" },
  { to: "/dashboard/balance", label: "Balance", n: "03", Icon: ArrowLeftRight, title: "Balance", meta: "modelled · generation vs demand vs storage" },
  { to: "/dashboard/reliability", label: "Reliability", n: "04", Icon: ShieldCheck, title: "Reliability", meta: "modelled · risk-only" },
  { to: "/dashboard/seasonal", label: "Seasonal", n: "05", Icon: CalendarRange, title: "Seasonal", meta: "modelled · recurring pattern" },
  { to: "/dashboard/demand", label: "Demand", n: "06", Icon: Zap, title: "Demand & capacity", meta: "modelled · planning" },
  { to: "/dashboard/investment", label: "Investment", n: "07", Icon: CircleDollarSign, title: "Investment", meta: "scenario · not advice" },
];

type Render = (v: { forecast: ForecastResponse; derived: DerivedDashboard }) => ReactNode;

function Module({ def, children }: { def: ModuleDef; children: Render }) {
  const { result, derived, loading, error } = useDashboardContext();
  return (
    <ModulePage def={def}>
      {result && derived ? children({ forecast: result, derived }) : <ModuleEmpty loading={loading} error={error} />}
    </ModulePage>
  );
}

export function OverviewModule() {
  return (
    <Module def={MODULES[0]}>
      {({ forecast, derived }) => <DecisionCallout forecast={forecast} derived={derived} />}
    </Module>
  );
}

export function ForecastModule() {
  return (
    <Module def={MODULES[1]}>
      {({ forecast, derived }) => (
        <>
          <ForecastPanel forecast={forecast} />
          <ForecastTable forecast={forecast} balance={derived.balance} />
        </>
      )}
    </Module>
  );
}

export function BalanceModule() {
  return <Module def={MODULES[2]}>{({ forecast, derived }) => <BalancePanel forecast={forecast} derived={derived} />}</Module>;
}

export function ReliabilityModule() {
  return <Module def={MODULES[3]}>{({ forecast, derived }) => <ReliabilityPanel forecast={forecast} derived={derived} />}</Module>;
}

export function SeasonalModule() {
  return <Module def={MODULES[4]}>{({ derived }) => <SeasonalPanel derived={derived} />}</Module>;
}

export function DemandModule() {
  return <Module def={MODULES[5]}>{({ derived }) => <CapacityPanel derived={derived} />}</Module>;
}

export function InvestmentModule() {
  return <Module def={MODULES[6]}>{({ derived }) => <InvestmentPanel derived={derived} />}</Module>;
}
