import { ForecastPanel } from "@/components/charts/ForecastPanel";
import { ForecastTable } from "@/components/dashboard/ForecastTable";
import { MODULES, Module } from "./modules";

export default function ForecastModule() {
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
