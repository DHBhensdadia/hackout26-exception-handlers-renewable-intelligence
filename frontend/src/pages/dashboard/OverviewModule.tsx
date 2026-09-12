import { DecisionCallout } from "@/components/dashboard/DecisionCallout";
import { MODULES, Module } from "./modules";

export default function OverviewModule() {
  return (
    <Module def={MODULES[0]}>
      {({ forecast, derived }) => <DecisionCallout forecast={forecast} derived={derived} />}
    </Module>
  );
}
