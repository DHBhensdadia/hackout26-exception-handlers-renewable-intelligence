import { BalancePanel } from "@/components/dashboard/BalancePanel";
import { RegionalBalancePanel } from "@/components/dashboard/RegionalBalancePanel";
import { useDashboardContext } from "@/hooks/useDashboardContext";
import { MODULES, Module } from "./modules";

/**
 * Two balances, and the distinction matters.
 *
 * The regional one comes from the backend: real metered demand for the whole market region,
 * a coherent 200-scenario ensemble across every plant in it, surplus and shortage as
 * calibrated probabilities. It leads, because it is the platform's actual decision layer.
 *
 * The site one is derived in the browser against a modelled demand curve. It answers a
 * narrower question - what this single plant does against its own load shape - and is kept
 * for that, labelled so the two are not mistaken for each other.
 */
export default function BalanceModule() {
  const { site, form } = useDashboardContext();

  return (
    <Module def={MODULES[2]}>
      {({ forecast, derived }) => (
        <>
          <h3 className="panel-subhead">Regional balance — backend, calibrated probabilities</h3>
          {site ? <RegionalBalancePanel site={site} horizonH={form.horizon_h} /> : null}
          <h3 className="panel-subhead">Site balance — in-browser, single plant</h3>
          <BalancePanel forecast={forecast} derived={derived} />
        </>
      )}
    </Module>
  );
}
