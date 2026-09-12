# AGENTS.md

Project: **re-forecast** — React 19 + TypeScript + Vite 6 frontend.

## Commands

| Task | Command |
| --- | --- |
| Dev server | `npm run dev` |
| Typecheck | `npm run typecheck` |
| Lint | `npm run lint` |
| Format | `npm run format` |
| Test | `npm test` (watch: `npm run test:watch`) |
| Production build | `npm run build` |
| Full check | `npm run ci` |

Always run `npm run typecheck` and `npm run lint` before considering a change done.

## Conventions

- Path alias `@/` → `src/`.
- Styling is hand-written CSS with design tokens in `src/styles/tokens.css`; Tailwind is imported only for its reset.
- Pure domain logic lives in `src/lib/derive/` and must stay unit-tested (`src/lib/derive/derive.test.ts`).
- The dashboard run state lives in `src/hooks/useDashboard.ts` and is shared via `useDashboardContext`.
- Do not commit secrets. Configure the API via `.env` (see `.env.example`).
