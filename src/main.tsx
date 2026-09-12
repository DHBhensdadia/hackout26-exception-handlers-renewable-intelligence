import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import "./styles/tokens.css";
import "./styles/global.css";
import "./styles/dashboard.css";
import Landing from "@/pages/Landing";
import DashboardLayout from "@/pages/dashboard/DashboardLayout";
import {
  BalanceModule,
  DemandModule,
  ForecastModule,
  InvestmentModule,
  OverviewModule,
  ReliabilityModule,
  SeasonalModule,
} from "@/pages/dashboard/modules";
import { ScrollToTop } from "@/components/Shell";

// Simple client-only app. Deep-link paths fall back to the landing page so a
// refresh on /dashboard never 404s in static hosting.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <ScrollToTop />
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
        <Route path="*" element={<Landing />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>
);
