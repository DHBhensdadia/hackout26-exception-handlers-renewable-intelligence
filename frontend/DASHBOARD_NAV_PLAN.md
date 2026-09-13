# Dashboard Navigation — implementation plan

Goal: give `/dashboard` the sidebar navigation shown in the reference (app
switcher on top, `MODULES` label, icon nav with an active row), without
abandoning the console's ruled design system.

## 1. Feasibility — yes

The app already uses `react-router-dom` v7 and has `lucide-react` installed but
unused. Routing is flat (`/`, `/dashboard`), and the dashboard is one long scroll
in `src/pages/Dashboard.tsx` with a sticky `RunRail` that mixes provenance,
run controls, and a scroll-spy § index. Converting to a **layout route with
child module routes** is a first-class React Router v7 pattern
(`layout(...)` / nested `children` + `<Outlet/>`) and needs no new dependency.

## 2. Research findings (React Router v7)

- Nested routes render children through a parent's `<Outlet/>`; the parent path
  is prepended to child paths. An `index` route handles the bare path
  (reactrouter.com, "Configure Nested Routes and Render with Outlet").
- `NavLink` supplies active styling and, since v6, sets `aria-current="page"`
  automatically on the active link — the correct accessibility primitive for a
  module nav.
- A layout route is the documented way to scope a sidebar to a set of routes
  (address-book tutorial). Unknown `/dashboard/*` should redirect to the index.

## 3. Architecture

```
/dashboard                 DashboardLayout  (provider + sidebar + <Outlet/> + drawer)
  ├─ index                 Overview   (The call)
  ├─ forecast              Forecast
  ├─ balance               Balance
  ├─ reliability           Reliability
  ├─ seasonal              Seasonal
  ├─ demand                Demand & capacity
  ├─ investment            Investment
  └─ *                     -> Navigate to /dashboard
```

**Why routes over scroll-spy:** the reference is an app shell that swaps the
content pane. Route-per-module gives deep links, back/forward, and only renders
the active module, while the layout keeps run state alive across navigation.

**State:** lift `useDashboard()` into a `DashboardProvider` at the layout so a
run survives module changes (today it lives in the page and would unmount).
Expose it via `useDashboardContext()`.

**Run controls:** the sidebar targets navigation only, so the input form moves
into a right-hand **drawer** (native `<dialog>` → built-in focus trap, Esc,
`::backdrop`) opened from the sidebar footer. The single `Run forecast` button
stays in the sidebar footer; request JSON preview joins the drawer.

## 4. Information architecture

| §  | Route        | Sidebar label | Icon (lucide)      |
|----|--------------|---------------|--------------------|
| 01 | `/dashboard` | Overview      | `Target`           |
| 02 | `/dashboard/forecast`    | Forecast    | `Activity`         |
| 03 | `/dashboard/balance`     | Balance     | `ArrowLeftRight`   |
| 04 | `/dashboard/reliability` | Reliability | `ShieldCheck`      |
| 05 | `/dashboard/seasonal`    | Seasonal    | `CalendarRange`    |
| 06 | `/dashboard/demand`      | Demand      | `Zap`              |
| 07 | `/dashboard/investment`  | Investment  | `CircleDollarSign` |

Labels are shortened for the rail ("Demand" for "Demand & capacity"); the page
header keeps the full §-numbered title.

## 5. Design system

Keep the ruled console language (hairlines, mono metadata, squared frames). The
one deliberate borrowing from the reference is the **active nav row**: a filled
`surface-2` row with `8px` radius and an accent icon — nav rows are interactive
controls, so a small radius is in keeping with the existing "radius only on
controls" rule. Page bodies still use the dashed `Section` header.

## 6. Accessibility

- `<nav aria-label="Modules">`; `NavLink` active links carry `aria-current="page"`.
- Console switcher is a labelled disclosure (`aria-haspopup="menu"`,
  `aria-expanded`) with `role="menu"` items.
- Drawer is a native `<dialog>` opened with `showModal()`: focus is trapped,
  `Escape` closes, and the page behind is inert automatically.
- Mobile sidebar: `aria-expanded` hamburger, labelled scrim button, `Escape`
  closes, body scroll-while-open is prevented.
- One `<h1>` per module via a `titleAs` option on `Section`.

## 7. Responsive

- ≥1080px: two-column grid `248px | 1fr`, sidebar sticky full height.
- <1080px: sidebar becomes a fixed off-canvas panel (translateX) with scrim; a
  slim sticky top bar appears with hamburger, "console" title, run button.

## 8. Files

New:
- `src/hooks/useDashboardContext.tsx` — provider + `useDashboardContext`.
- `src/pages/dashboard/DashboardLayout.tsx` — shell, mobile bar, drawer mount.
- `src/pages/dashboard/Sidebar.tsx` — switcher, module nav, run footer.
- `src/pages/dashboard/ControlsDrawer.tsx` — `<dialog>` wrapping `ControlsPanel`.
- `src/pages/dashboard/modules.tsx` — `MODULES` defs + 7 module components.
- `src/pages/dashboard/ModulePage.tsx` — header + empty/loading state.

Changed:
- `src/main.tsx` — nested `/dashboard` routes.
- `src/components/dashboard/Section.tsx` — optional `titleAs`.
- `src/styles/dashboard.css` — replace `.console*`/`.rail*` shell with
  `.shell*` / `.sidebar*` / `.drawer*`; keep `.rail__json` for the drawer.

Removed:
- `src/pages/Dashboard.tsx`, `src/components/dashboard/RunRail.tsx`,
  `src/components/dashboard/sections.ts`, `src/hooks/useActiveSection.ts`.

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Run state resets on module change | provider at layout, above `<Outlet/>` |
| Deep-linking `/dashboard/forecast` on static host | existing SPA fallback (`*` → Landing → client redirect) + nested `*` → index |
| Drawer/backdrop click closing too eagerly | close only when `event.target === dialog` |
| Icon name drift in lucide | typecheck is the gate; swap names if missing |
| Mobile scroll bleed under open nav | toggle `overflow:hidden` on `documentElement` while open |

## 10. Verification

- `npm run typecheck` + `npm run build`.
- Playwright: sidebar has 7 module links; clicking each changes the URL and
  renders exactly one module; `aria-current` on the active link; drawer opens,
  traps focus, closes on Esc; mobile off-canvas opens/closes; no console errors;
  no horizontal overflow at 1440 / 390.
