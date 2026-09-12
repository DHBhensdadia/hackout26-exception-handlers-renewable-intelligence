import { InvestmentPanel } from "@/components/dashboard/InvestmentPanel";
import { MODULES, Module } from "./modules";

export default function InvestmentModule() {
  return <Module def={MODULES[6]}>{({ derived }) => <InvestmentPanel derived={derived} />}</Module>;
}
