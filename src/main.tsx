import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import "./styles/tokens.css";
import "./styles/global.css";
import "./styles/dashboard.css";
import Landing from "@/pages/Landing";
import Dashboard from "@/pages/Dashboard";
import { ScrollToTop } from "@/components/Shell";

// Simple client-only app. Deep-link paths fall back to the landing page so a
// refresh on /dashboard never 404s in static hosting.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <ScrollToTop />
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="*" element={<Landing />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>
);