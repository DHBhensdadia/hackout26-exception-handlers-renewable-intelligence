import { lazy, Suspense, StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import "./styles/tokens.css";
import "./styles/global.css";
import "./styles/dashboard.css";
import "./styles/cinematic.css";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { ScrollToTop } from "@/components/Shell";

// Route-level code splitting: the landing page is the first paint, so the
// dashboard bundle (shell + panels + charts) is only fetched on demand.
const Landing = lazy(() => import("@/pages/Landing"));
const DashboardLayout = lazy(() => import("@/pages/dashboard/DashboardLayout"));
const OverviewModule = lazy(() => import("@/pages/dashboard/OverviewModule"));
const ForecastModule = lazy(() => import("@/pages/dashboard/ForecastModule"));
const BalanceModule = lazy(() => import("@/pages/dashboard/BalanceModule"));
const ReliabilityModule = lazy(() => import("@/pages/dashboard/ReliabilityModule"));
const SeasonalModule = lazy(() => import("@/pages/dashboard/SeasonalModule"));
const DemandModule = lazy(() => import("@/pages/dashboard/DemandModule"));
const InvestmentModule = lazy(() => import("@/pages/dashboard/InvestmentModule"));
const NotFound = lazy(() => import("@/pages/NotFound"));

function RouteFallback() {
  return (
    <div className="route-fallback" role="status" aria-live="polite">
      <span className="route-fallback__k">loading</span>
      <span className="route-fallback__bar" aria-hidden="true" />
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <BrowserRouter>
        <ScrollToTop />
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/dashboard" element={<DashboardLayout />}>
              <Route index element={<OverviewModule />} />
              <Route path="forecast" element={<ForecastModule />} />
              <Route path="balance" element={<BalanceModule />} />
              <Route path="reliability" element={<ReliabilityModule />} />
              <Route path="seasonal" element={<SeasonalModule />} />
              <Route path="demand" element={<DemandModule />} />
              <Route path="investment" element={<InvestmentModule />} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Route>
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </ErrorBoundary>
  </StrictMode>
);
