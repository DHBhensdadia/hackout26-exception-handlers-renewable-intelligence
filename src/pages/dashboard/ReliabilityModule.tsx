import { ReliabilityPanel } from "@/components/dashboard/ReliabilityPanel";
import { MODULES, Module } from "./modules";

export default function ReliabilityModule() {
  return <Module def={MODULES[3]}>{({ forecast, derived }) => <ReliabilityPanel forecast={forecast} derived={derived} />}</Module>;
}
