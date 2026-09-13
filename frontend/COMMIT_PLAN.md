# Plan — commit the landing, console and regional work

Scope: everything uncommitted on `feat/renewable-forecast-frontend` (HEAD
`3c9d741`). Goal: land it as a series of small, professional, individually
meaningful commits on the same branch, then push without merging.

## 1. Working agreement

- **Conventional Commits**, imperative subjects ≤72 chars, no emoji, no
  "comprehensive/robust/seamless" filler. The body says **why**, not what the
  diff already shows.
- **Atomic commits** — one concern each. Where a concern spans files, they land
  together: tests travel with the model they cover, styles travel with the
  markup that uses them.
- **Bisectable** — every commit builds and passes tests. The one cross-cutting
  model swap is split into a seasonal step and a demand step so each is
  independently revertable.
- **Hunk-level staging** for files that serve several commits
  (`dashboard.css`, `useDashboard.ts`, `derive/index.ts`, `derive.test.ts`,
  `modules.tsx`) using `git add -p`. Never `git add -A` / `git add .`.
- **`Refrence/` is never staged.** It stays untracked and is not gitignored.
  A guard runs before every commit:
  `git diff --cached --name-only | rg -q '^Refrence/' && exit 1`.
- **Checkpoint first**: `git bundle create /tmp/rf-verify/pre-commit.bundle --all`
  and a working-tree tar of `src`, so the whole series is reversible with
  `git reset --soft 3c9d741`.

## 2. Commit sequence (13 commits)

| # | Commit | Files / hunks |
|---|---|---|
| 1 | `chore(lint): exclude the reference folder from lint runs` | `eslint.config.js` |
| 2 | `docs: record the landing and console redesign plans` | `CONSOLE_PLAN.md`, `HERO_PLAN.md`, `LANDING_FIX_PLAN.md` |
| 3 | `docs: record the seasonal and demand implementation plan` | `SEASONAL_DEMAND_PLAN.md` |
| 3b | `docs: add the commit and push plan` | `COMMIT_PLAN.md` |
| 4 | `feat(landing): turn the hero links into a vertical rail` | `Landing.tsx`, `cinematic.css` |
| 5 | `feat(landing): rebuild the hero console on the reference timeline and icons` | `HeroConsole.tsx`, `global.css` |
| 6 | `feat(console): adopt the app-window shell for the dashboard` | `console.css`, `main.tsx`, `DashboardLayout.tsx`, `Sidebar.tsx`, `ConsoleSummary.tsx`, `modules.tsx` (bar hunk), `dashboard.css` (shell-removal hunks) |
| 7 | `refactor(console): drop the ruled section header` | `ModulePage.tsx`, delete `Section.tsx`, `dashboard.css` (dsection hunk) |
| 8 | `feat(types): add regional demand and seasonal contracts` | `types.ts` |
| 9 | `feat(derive): add the regional climatology and demand models` | `history.ts`, `demand.ts`, `index.ts` (additive hunks) |
| 10 | `feat(api): expose the regional registry and demand band` | `mock.ts`, `client.ts` |
| 11 | `feat(charts): add a shared band primitive` | `BandChart.tsx` |
| 12a | `refactor(model): compute the seasonal pattern from the climatology` | `seasonal.ts`, `useDashboard.ts` (seasonal + region hunks), `SeasonalHeatGrid.tsx`, `SeasonalPanel.tsx`, `SeasonalModule.tsx`, `index.ts` (hunk), `derive.test.ts` (seasonal hunks), `dashboard.css` (seasonal hunks) |
| 12b | `refactor(model): replace the synthetic demand curve` | `useDashboard.ts` (demand hunks), delete `capacity.ts`, delete `CapacityPanel.tsx`, `DemandPanel.tsx`, `RegionPicker.tsx`, `DemandModule.tsx`, `index.ts` (hunk), `derive.test.ts` (demand hunks), `dashboard.css` (regional hunks), `modules.tsx` (meta hunk) |

### Why 12 is two commits, not one

`seasonal.ts` and `capacity.ts` are both consumed by `useDashboard`, the panel
that renders each, and the test file. Swapping both at once is one commit only
if you accept a large blast radius. Splitting at the model boundary keeps each
step green and revertable:

- **12a** removes `seasonalPattern`, adds the grid, and leaves `capacityModel`
  in place (still wired to `derived.capacity`) — nothing else changes.
- **12b** removes `capacityModel`, adds the demand state, and deletes the panel
  it fed.

### Proposed messages (subject + body)

```
1  chore(lint): exclude the reference folder from lint runs
   Refrence/ is untracked reference material, not project source. ESLint was
   walking it and reporting ~190 problems that have nothing to do with this
   codebase.

2  docs: record the landing and console redesign plans
   Captures the decisions behind the vertical hero rail, the hero console's
   responsive contract and the dashboard shell.

3  docs: record the seasonal and demand implementation plan
   Contract-first plan for dropping the hashed seasonal and demand models.

3b docs: add the commit and push plan
   Staging order, per-commit verification and the push procedure for this
   series.

4  feat(landing): turn the hero links into a vertical rail
   The site navbar only drops in after the hero, so these three links are the
   only navigation at the top of the page. A left-edge rail uses the empty
   middle band and keeps the wordmark and tagline untouched.

5  feat(landing): rebuild the hero console on the reference timeline and icons
   Replaces the emoji markers with the reference's stroke icons and the bar
   field with the dashed horizon rail, then ports the reference's 980/640
   responsive contract. The window sizes to its content so no dead space is
   left below the chips.

6  feat(console): adopt the app-window shell for the dashboard
   Ports .appwin/.macbar/.metric/.chip from the reference. The sidebar carries
   module navigation, run state moves into a provider above the outlet, and the
   sticky run rail becomes a run summary in the module bar plus a settings
   drawer.

7  refactor(console): drop the ruled section header
   The app-window bar now carries the module title, so the §-numbered header,
   its component and its rules are no longer used.

8  feat(types): add regional demand and seasonal contracts
   Shapes for GET /regions, POST /demand and GET /seasonal/{region}. Model
   accuracy (nMAE, coverage, the VIC1 caveat) is part of the contract so the UI
   cannot present a region without it.

9  feat(derive): add the regional climatology and demand models
   A deterministic three-year hourly climatology per region stands in for the
   AEMO history on disk; the demand band and the five-year capacity plan are
   derived from it.

10 feat(api): expose the regional registry and demand band
   GET /regions and POST /demand join the client. In real mode a 404 from
   /demand degrades to the same model, tagged source: "modelled", so the panel
   is honest about what is not served yet.

11 feat(charts): add a shared band primitive
   One p10-p90 band renderer with an optional reference rule and hover readout,
   so demand is drawn in the same grammar as generation. ForecastBandChart is
   left untouched.

12a refactor(model): compute the seasonal pattern from the climatology
    Replaces the site-id hash with a month x hour grid computed over three
    years of the regional series, plus the storage it would take to absorb the
    recurring surplus. The Seasonal module is rebuilt on it.

12b refactor(model): replace the synthetic demand curve
    Deletes DEMAND_CURVE and the capacity model that consumed it. Regional
    demand is drawn as a p10-p90 band against the renewable band on one axis,
    with per-region accuracy and the VIC1 limitation shown where the model is
    weak.
```

## 3. Staging shared files

Run these with `git add -p <file>` and select hunks by target:

- `src/styles/dashboard.css` — (a) shell/sidebar removal → **6**;
  (b) `.dsection` removal → **7**; (c) old `.seasonal` removal + `.regional/heat/rtable/rpick`
  additions → **12a/12b**.
- `src/hooks/useDashboard.ts` — region + seasonal state → **12a**;
  demand state and the plan wiring → **12b**.
- `src/lib/derive/index.ts` — add `history`/`demand` → **9**;
  drop `seasonal` export name change → **12a**; drop `capacity` → **12b**.
- `src/lib/derive/derive.test.ts` — seasonal describes → **12a**;
  demand describes + capacity removal → **12b**.
- `src/pages/dashboard/modules.tsx` — `bar` field → **6**; Seasonal/Demand meta strings → **12b**.

Before each commit:
```bash
git diff --cached --stat                                  # what is actually staged
git diff --cached --name-only | rg -q '^Refrence/' && echo ABORT
git commit -m "<subject>" -m "<body>"
npm run build                                             # or npm test for model commits
```

## 4. Push procedure

Nothing is pushed until the whole series is green.

```bash
# 1. Gate: full CI on the committed tree
npm run ci                       # typecheck · lint · test · build

# 2. Confirm the branch is a clean fast-forward
git fetch origin --prune
git status -sb                   # expect no "behind"

# 3. If origin moved ahead, rebase (never merge, never force)
git pull --rebase origin feat/renewable-forecast-frontend

# 4. Re-run the gate if the rebase changed anything
npm run ci

# 5. Push the same branch
git push origin feat/renewable-forecast-frontend

# 6. Verify
git status -sb                   # branch up to date, only Refrence/ untracked
git log --oneline origin/feat/renewable-forecast-frontend -12
git ls-files | rg '^Refrence/'   # must print nothing
```

If the push is rejected (non-fast-forward): `git fetch`, rebase, re-run CI,
push again. **No `--force`, no `--force-with-lease`** — nothing has been
rewritten, so there is no reason to force.

## 5. Safety and rollback

- Pre-work bundle: `git bundle create /tmp/rf-verify/pre-commit.bundle --all`.
- Undo the whole series before pushing: `git reset --soft 3c9d741` — every
  change returns to the index, nothing is lost.
- Undo one commit: `git reset --soft HEAD~1` and re-stage.
- After a bad push: `git revert <sha>` (history is shared; no rewrites).
- Do not touch `main`, `ML_Model`, `frontend2` or `Phase2_Intelligence`.

## 6. Final checklist

- [ ] 13 commits, each with a single concern and a why-first body
- [ ] `Refrence/` absent from every commit (`git log --name-only` scan)
- [ ] `npm run ci` green on HEAD
- [ ] Working tree only shows `Refrence/`
- [ ] Branch pushed fast-forward; local and origin at the same commit
