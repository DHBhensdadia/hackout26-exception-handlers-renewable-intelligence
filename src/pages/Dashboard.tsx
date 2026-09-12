import { SiteHeader } from "../components/SiteNav";
import { SiteFooter } from "../components/SiteFooter";
import { useDashboard } from "@/hooks/useDashboard";
import { RunRail } from "@/components/dashboard/RunRail";
import { Section } from "@/components/dashboard/Section";
import { SECTIONS } from "@/components/dashboard/sections";
import { DecisionCallout } from "@/components/dashboard/DecisionCallout";
import { ForecastPanel } from "@/components/charts/ForecastPanel";
import { ForecastTable } from "@/components/dashboard/ForecastTable";
import { BalancePanel } from "@/components/dashboard/BalancePanel";
import { ReliabilityPanel } from "@/components/dashboard/ReliabilityPanel";
import { SeasonalPanel } from "@/components/dashboard/SeasonalPanel";
import { CapacityPanel } from "@/components/dashboard/CapacityPanel";
import { InvestmentPanel } from "@/components/dashboard/InvestmentPanel";

const [S_CALL, S_FORECAST, S_BALANCE, S_RELIABILITY, S_SEASONAL, S_CAPACITY, S_INVESTMENT] = SECTIONS;

export default function Dashboard() {
  const { sites, form, patch, run, result, loading, error, derived, jsonPreview } = useDashboard();

  return (
    <>
      <SiteHeader />
      <div className="console">
        <div className="wrap">
          <header className="console__head">
            <div>
              <span className="eyebrow">Decision support</span>
              <h1 className="h2" style={{ marginTop: ".5rem" }}>
                Forecast explorer
              </h1>
            </div>
            <span className="console__status">
              {result
                ? `${result.site_id} · ${result.tech} · ${result.points.length} h`
                : loading
                  ? "running…"
                  : "idle"}
            </span>
          </header>

          {error && <div className="console__error">{error}</div>}

          <div className="console__grid">
            <RunRail
              sites={sites}
              form={form}
              patch={patch}
              run={run}
              loading={loading}
              result={result}
              site={derived?.site ?? null}
              jsonPreview={jsonPreview}
            />

            <main className="console__main">
              {derived && result ? (
                <>
                  <Section id={S_CALL.id} index={S_CALL.n} title="The call" meta={`${result.tech} · ${result.points.length} h`}>
                    <DecisionCallout forecast={result} derived={derived} />
                  </Section>

                  <Section id={S_FORECAST.id} index={S_FORECAST.n} title="Forecast" meta="measured · xgb-q · p10/p50/p90">
                    <ForecastPanel forecast={result} />
                    <ForecastTable forecast={result} balance={derived.balance} />
                  </Section>

                  <Section id={S_BALANCE.id} index={S_BALANCE.n} title="Balance" meta="modelled · generation vs demand vs storage">
                    <BalancePanel forecast={result} derived={derived} />
                  </Section>

                  <Section id={S_RELIABILITY.id} index={S_RELIABILITY.n} title="Reliability" meta="modelled · risk-only">
                    <ReliabilityPanel forecast={result} derived={derived} />
                  </Section>

                  <Section id={S_SEASONAL.id} index={S_SEASONAL.n} title="Seasonal" meta="modelled · recurring pattern">
                    <SeasonalPanel derived={derived} />
                  </Section>

                  <Section id={S_CAPACITY.id} index={S_CAPACITY.n} title="Demand & capacity" meta="modelled · planning">
                    <CapacityPanel derived={derived} />
                  </Section>

                  <Section id={S_INVESTMENT.id} index={S_INVESTMENT.n} title="Investment" meta="scenario · not advice">
                    <InvestmentPanel derived={derived} />
                  </Section>
                </>
              ) : (
                <div className="console__placeholder">
                  {loading ? "Running quantile forecast models…" : "Configure inputs and run a forecast."}
                </div>
              )}
            </main>
          </div>
        </div>
      </div>
      <SiteFooter />
    </>
  );
}
