import { useDashboardContext } from "@/hooks/useDashboardContext";
import { DemandPanel } from "@/components/dashboard/DemandPanel";
import { MODULES } from "./modules";
import { ModulePage } from "./ModulePage";

export default function DemandModule() {
  const { demand, demandLoading, demandError, regions, region, regionId, setRegionId } = useDashboardContext();
  return (
    <ModulePage def={MODULES[5]}>
      <DemandPanel
        demand={demand}
        region={region}
        regions={regions}
        regionId={regionId}
        onRegion={setRegionId}
        loading={demandLoading}
        error={demandError}
      />
    </ModulePage>
  );
}
