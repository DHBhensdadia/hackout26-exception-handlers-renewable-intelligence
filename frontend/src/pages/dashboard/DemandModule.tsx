import { CapacityPanel } from "@/components/dashboard/CapacityPanel";
import { MODULES, Module } from "./modules";

export default function DemandModule() {
  return <Module def={MODULES[5]}>{({ derived }) => <CapacityPanel derived={derived} />}</Module>;
}
