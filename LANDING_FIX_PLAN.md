# Plan — landing fixes (hero nav, hero console responsive, dead space)

## 0. Diagnosis (measured on the current working tree)

| Where | Finding |
|---|---|
| Hero (Image 1) | The in-base nav (`.cine__nav`) is already implemented in the working tree — 3 links at 1440 / 914 / 760 / 430 px. On the deployed branch it is absent, which reads as "nothing here". Legibility over the bright upper sky is weak. |
| Hero console (Images 2–3) | `console.css` (added for the dashboard) leaks into the landing: `.appwin`, `.appwin__side`, `.appwin__content`, `.appwin__bar`, `.chip`, `svg.ic` are **global**. That gives the hero mock `min-height: min(900px, 100vh-…)` → measured **851 px tall for 319 px of content** (the dead space in Image 3), and forces the sidebar visible below 980 px, which the landing's own media query hides. |
| Hero console responsive | Global rules only cover `≤980` (hide side, 620 px) and `≤640` (2-up stats, hide title). Between 641–980 the 4 stats stay 4-up in a 620 px window; the axis is one long `<span>` of 13 labels that cannot reflow; the chart is fixed 120 px. |

Root cause: two different components share the `.appwin*` namespace, and the newer
dashboard sheet is unscoped.

---

## 1. Hero — in-base nav (Image 1)

- Keep `.cine__top` + `.cine__nav` (Forecast → `/dashboard/forecast`,
  Approach → `#manifesto`, Research → `#modules`); Dashboard intentionally absent.
- Add a soft top scrim to `.cine__ui` (gradient from `rgba(8,12,16,.55)` to
  transparent, ~140px) so the white nav always reads over the bright sky,
  matching the existing bottom scrim.
- Confirm at 430 px the row wraps cleanly under the wordmark with no overlap.

## 2. Stop the leak — scope `console.css` to `.console-page`

- Wrap every rule in `console.css` under `.console-page` (native CSS nesting, one
  wrapper) so dashboard chrome can never touch the landing mock again. `@media`
  blocks move to top level with `.console-page`-prefixed selectors to stay
  portable.
- Delete the now-redundant `.console-page …` neutraliser block at the end of the
  file (superseded by the wrapper).
- Result: the landing hero console returns to its own `global.css` sizing
  (`max-width: 1060px`, `min-height: 470px`), and the dashboard is unchanged.

## 3. Hero console — responsive + no dead space (Images 2, 3)

Component: `src/components/HeroConsole.tsx` + its rules in `global.css`
(`.appwin` block, L1711–1943).

**Dead space**
- `min-height: 470px` → `auto`; `align-content: start` on the grid so the last
  row never stretches. The window height becomes content height (macbar + bar +
  stats + timeline + chips).

**Match the reference timeline**
- Replace the 16-column `.appwin__chart` bar field + one-line `.appwin__axis`
  with the dashed horizon rail used on the dashboard (`.hline`): a dashed rule
  with ticks at `now, +6h … +72h`, surplus/shortage segments derived from the
  existing `BARS` mock, and a "now" marker. Static values, no new data source.

**Responsive**
- `≥1080`: sidebar 208 px + content, 4-up stats.
- `981–1080`: 4-up stats, sidebar stays, chart/timeline shrinks.
- `≤980`: sidebar hidden (restore the landing's own rule), stats 2-up, window
  `max-width: 620px`.
- `≤640`: full-bleed, stats 2-up with tighter padding, every other timeline tick
  hidden, chips wrap to two rows, macbar title truncates with ellipsis instead of
  disappearing.
- Timeline ticks: individual elements (not one span) so they can reflow/hide.

**Motion** — keep `reveal--console` (stat/segment/pill rise-in) and the reduced-
motion overrides intact; retarget the selectors that referenced `.appwin__bar-*`.

## 4. Files

- `src/pages/Landing.tsx` / `src/styles/cinematic.css` — top scrim (small).
- `src/styles/console.css` — wrap in `.console-page`.
- `src/components/HeroConsole.tsx` + `src/styles/global.css` — timeline markup,
  sizing, responsive rules, reveal retarget.

## 5. Verification

- Playwright, landing at 1440 / 1100 / 980 / 760 / 430: no horizontal overflow;
  hero console height ≈ content height (dead space ≤ 40 px); sidebar hidden
  ≤980; stats 2-up ≤980; timeline ticks reduce ≤640; chips wrap.
- Dashboard regression: the 20-check console suite stays green (routing, drawer,
  metrics, timeline readout, mobile off-canvas).
- `typecheck`, `lint`, `test`, `build`.

## 6. Open question

Image 1: I read "nothing here" as the missing in-base nav on the deployed
branch (already in the working tree). If instead you meant the empty middle of
the hero, say so and I will add content there rather than only the top scrim.
