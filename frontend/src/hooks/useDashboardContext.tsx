import { createContext, useContext, type ReactNode } from "react";
import { useDashboard } from "./useDashboard";

type DashboardValue = ReturnType<typeof useDashboard>;

const DashboardContext = createContext<DashboardValue | null>(null);

/**
 * Keeps a forecast run alive across module route changes by holding the
 * orchestration hook above the layout's <Outlet/>.
 */
export function DashboardProvider({ children }: { children: ReactNode }) {
  const value = useDashboard();
  return <DashboardContext.Provider value={value}>{children}</DashboardContext.Provider>;
}

export function useDashboardContext() {
  const value = useContext(DashboardContext);
  if (!value) throw new Error("useDashboardContext must be used within DashboardProvider");
  return value;
}
