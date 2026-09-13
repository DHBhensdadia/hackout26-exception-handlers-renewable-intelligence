import { useDashboardContext } from "@/hooks/useDashboardContext";
import { SeasonalPanel } from "@/components/dashboard/SeasonalPanel";
import { MODULES } from "./modules";
import { ModulePage } from "./ModulePage";

export default function SeasonalModule() {
  const { seasonal, regions, regionId, setRegionId } = useDashboardContext();
  return (
    <ModulePage def={MODULES[4]}>
      <SeasonalPanel seasonal={seasonal} regions={regions} regionId={regionId} onRegion={setRegionId} />
    </ModulePage>
  );
}
