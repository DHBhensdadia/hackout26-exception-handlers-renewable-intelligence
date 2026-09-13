/**
 * Does the dashboard actually render?
 *
 * Everything else in this suite tests logic, and the build tests compilation. Neither
 * caught a null dereference on the first render that blanked the whole console: the
 * seasonal state and the selected region are both empty before anything loads, and an
 * over-eager optional chain made `undefined === undefined` true, then read `.data` off
 * null. Typecheck, lint, the production build and a crawl of every module in the dev graph
 * were all green while the page showed nothing.
 *
 * These mount the real components with nothing loaded, which is the exact state that broke.
 * The route tree mirrors `main.tsx`, which cannot be imported because it calls `createRoot`
 * at module scope.
 */

import { lazy, Suspense } from "react";
import { render, waitFor } from "@testing-library/react";
import { MemoryRouter, Navigate, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

// The console fetches on mount. An empty payload is the honest first-render state and is
// also the one that exposed the bug.
vi.stubGlobal(
  "fetch",
  vi.fn(
    async () =>
      new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } })
  )
);

const DashboardLayout = lazy(() => import("./DashboardLayout"));
const OverviewModule = lazy(() => import("./OverviewModule"));
const ForecastModule = lazy(() => import("./ForecastModule"));
const BalanceModule = lazy(() => import("./BalanceModule"));
const ReliabilityModule = lazy(() => import("./ReliabilityModule"));
const SeasonalModule = lazy(() => import("./SeasonalModule"));
const DemandModule = lazy(() => import("./DemandModule"));
const InvestmentModule = lazy(() => import("./InvestmentModule"));

function mount(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Suspense fallback={<span>loading</span>}>
        <Routes>
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
        </Routes>
      </Suspense>
    </MemoryRouter>
  );
}

/** Lazy routes resolve a tick after mount; a render that threw stays empty forever. */
async function rendered(path: string) {
  const view = mount(path);
  await waitFor(() => expect(view.container.textContent).not.toBe("loading"), { timeout: 5000 });
  return view;
}

const ROUTES = [
  "/dashboard",
  "/dashboard/forecast",
  "/dashboard/balance",
  "/dashboard/reliability",
  "/dashboard/seasonal",
  "/dashboard/demand",
  "/dashboard/investment",
];

describe("the console renders from cold", () => {
  for (const path of ROUTES) {
    it(`mounts ${path} with nothing loaded`, async () => {
      const { container, unmount } = await rendered(path);
      expect(container.firstChild, `${path} rendered nothing`).not.toBeNull();
      expect((container.textContent ?? "").trim().length).toBeGreaterThan(0);
      unmount();
    });
  }

  it("does not throw on the first render before any data arrives", async () => {
    const errors: unknown[] = [];
    const spy = vi.spyOn(console, "error").mockImplementation((...args) => errors.push(args));
    const { unmount } = await rendered("/dashboard");
    spy.mockRestore();
    unmount();

    const fatal = errors
      .map((e) => String(e))
      .filter((e) => /Cannot read propert|is not a function|undefined is not/.test(e));
    expect(fatal, `render threw: ${fatal[0]}`).toHaveLength(0);
  });
});
