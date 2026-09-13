import { BalancePanel } from "@/components/dashboard/BalancePanel";
import { MODULES, Module } from "./modules";

export default function BalanceModule() {
  return <Module def={MODULES[2]}>{({ forecast, derived }) => <BalancePanel forecast={forecast} derived={derived} />}</Module>;
}
