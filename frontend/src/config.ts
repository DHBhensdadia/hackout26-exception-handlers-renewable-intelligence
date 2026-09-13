/**
 * Runtime configuration.
 *
 * `VITE_USE_MOCK` controls whether dashboard data comes from the deterministic
 * in-app mock or the real FastAPI backend. Set it to "false" (e.g. in
 * `.env.production`) to talk to `VITE_API_BASE_URL`. Unset keeps the demo
 * self-contained.
 */
export const config = {
  USE_MOCK: import.meta.env.VITE_USE_MOCK !== "false",
  API_BASE_URL: (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/+$/, ""),
  HORIZON_MIN: 1,
  HORIZON_MAX: 72,
  HORIZON_DEFAULT: 72,
};
