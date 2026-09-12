export const config = {
  USE_MOCK: true,
  API_BASE_URL: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000",
  HORIZON_MIN: 1,
  HORIZON_MAX: 72,
  HORIZON_DEFAULT: 72,
};