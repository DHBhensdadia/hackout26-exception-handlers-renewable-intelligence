# Plan — vertical hero nav + reference-grade responsive hero console

## Part A — vertical nav in the hero (Image 1)

Target: `Forecast · Approach · Research` as a **vertical rail** inside the
cinematic hero, not a horizontal top row.

**Placement (architectural call).** The hero's middle is empty on tall
viewports; the wordmark owns the top-left and the tagline owns the bottom-left.
A **left-edge** rail, vertically centred under the wordmark column, turns that
dead area into deliberate structure while keeping the composition aligned.

```
.cine__ui
  .cine__top   → wordmark (top-left, unchanged)
  .cine__nav   → vertical rail, left edge, vertically centred   ← was horizontal
  .cine__foot  → tagline + Open Dashboard (bottom, unchanged)
```

`.cine__nav` moves out of `.cine__top` and becomes an absolutely positioned
child of `.cine__ui` (so it stays out of the flex flow):

```css
.cine__nav {
  position: absolute;
  left: clamp(20px, 3.4vw, 46px);
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  pointer-events: auto;
}
```

**Link treatment** — adapted from the reference's vertical nav
(`Refrence/.../Vunai/public/css/style.css`, `.nav__links a` at ≤900px:
full-width rows, generous padding, hairline separator, larger text), re-skinned
for the dark over-image hero:

- mono, uppercase, tracked; right-aligned;
- one hairline separator per row (`rgba(255,255,255,.18)`), none on the last;
- a leading rule (18px) that expands and turns accent on hover/focus; label
  goes pure white;
- an index (`01/02/03`) in faint mono, matching the console's `MODULES` rhythm;
- `focus-visible` reuses the hero's amber outline;
- `prefers-reduced-motion` drops the transitions.

**Responsive**

| Viewport | Behaviour |
|---|---|
| tall (≥ 700px height) | left rail, vertically centred |
| short (≤ 640px height) | rail pins below the wordmark (a centred rail would crowd the tagline) |
| ≤ 640px width, tall | stays vertical, tighter gap/type, left edge |
| all widths | always vertical (per request); no horizontal fallback |

Sources: `style.css` `.nav__links` (vertical link pattern, hover underline),
`cinematic.css` existing `.cine__nav` rules, `.cine__ui::before` top scrim.

## Part B — responsive hero console, sourced from Vunai (Image 2)

Bring `HeroConsole` in line with the reference's own responsive contract and
reuse its assets.

**1. Responsive contract — ported verbatim from `devices.css`**
- `@media (max-width: 980px)`: `.appwin { grid-template-columns: 1fr; max-width: 620px }`,
  `.appwin__side { display: none }`, `.macbar { height: 40px }` (devices.css L595, L1001).
- `@media (prefers-reduced-motion: reduce)`: already covered; keep.
- Width scaling like `.appwin--fixed` (devices.css L956): `width: min(1346px, 94vw)`
  so the window matches the reference at every size instead of a flat 1060px.

**2. Module markers — use the reference's icons, not emoji.** Replace the
emoji glyphs (`◎ ⇄ ◔ ◈`) with the reference's monochrome stroke icons from
`services-console.tsx` (`Ico.target / chat / spark / code / chart`) rendered at
the reference's `svg.ic` size (15px, `stroke-width: 2`, muted → bright when
active). This is the biggest visible fidelity gap.

**3. Keep modules reachable when the sidebar hides.** The reference hides the
sidebar ≤980 and, elsewhere, switches interactive consoles to a static/stacked
mode (`devices.js` `data-appwin` + `.is-static`). Apply the same idea cheaply:
at ≤980 the sidebar is replaced by a compact horizontal `role="tablist"` strip
styled with the reference's `.tabs__nav` (devices.css L259–266). No screen
content changes — the strip preserves the module context and the active state.

**4. Layout integrity**
- Content-sized height (no forced `min-height`) — keeps the dead-space fix.
- Stats 4-up ≥861, 2-up ≤860; timeline ticks thin ≤760; full-bleed + tighter
  padding ≤640 (already in place).
- Internal scroll only if a panel ever overflows (reference's
  `.appwin--fixed .appwin__screen.active { overflow-y: auto }`).

**5. Files**
- `src/components/HeroConsole.tsx` — new icon components (ported), optional tab
  strip, marker markup.
- `src/styles/global.css` — 1346px scaling, ≤980/≤640 contract, `.tabs__nav`
  strip styles, icon sizing.
- `src/pages/Landing.tsx` + `src/styles/cinematic.css` — vertical nav.
- `Refrence/` stays untouched.

## Part C — verification
- Playwright, hero nav: vertical at 1440×900, 914×1895, 430×844; horizontal only
  on `max-height ≤ 520`; no overlap with wordmark/foot/CTA; anchors resolve.
- Hero console at 1440/1100/980/860/760/430: sidebar → tab strip at ≤980; icons
  render (no emoji fallback); stats 4/2-up; ticks thin; window width
  `min(1346, 94vw)`; dead space ≤ 8px; no horizontal overflow.
- Dashboard suite (20 checks) + `typecheck` · `lint` · `test` · `build`.

## Open note
The reference hides its console sidebar ≤980 and does not replace it. Item B3
(tab strip) is a deliberate, small improvement so the module identity survives;
say the word if you'd rather have the strict reference behaviour (sidebar simply
hidden).
