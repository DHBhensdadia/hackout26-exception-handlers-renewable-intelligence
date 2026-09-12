import { SeasonalPanel } from "@/components/dashboard/SeasonalPanel";
import { MODULES, Module } from "./modules";

export default function SeasonalModule() {
  return <Module def={MODULES[4]}>{({ derived }) => <SeasonalPanel derived={derived} />}</Module>;
}
