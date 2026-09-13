# Plan — commit our work onto the existing branch (no merge)

Goal: append everything we have built **on top of** `feat/renewable-forecast-frontend`
at the exact point we cloned it, on the **same branch**, and **do not merge** it
anywhere yet.

## 1. Where we are

| Fact | Value |
|---|---|
| Repo | `github.com/DHBhensdadia/hackout26-exception-handlers-renewable-intelligence` |
| Current branch | `feat/renewable-forecast-frontend` |
| Clone point (= branch tip = `origin/...`) | `f616d5e` "chore: add static assets and implementation plan" |
| Reflog | `f616d5e HEAD@{0}: clone: from ...` → nothing has been committed since |
| Remote default branch | `ML_Model` (do **not** touch) |
| Other remote branches | `main`, `frontend2`, `ML_Model` (do **not** touch) |
| Working tree | all of our work is currently **unstaged/untracked** |

Because the clone point is also the current tip, "append behind the commits of the
same branch at the point where we cloned" = **stack new commits after `f616d5e`
on this same branch**. No rebase, no history rewrite, no merge.

> If you actually meant *insert our work before `f616d5e`* (rewrite history), that
> is a different operation (interactive rebase + force-push) and is **not** in
> this plan. Say so and I will write a second plan.

## 2. Hard safety rules

1. **Never run `git add -A`, `git add .`, or `git commit -a`.**
   `Refrence/` is 1.2 GB / 24,166 files and is deliberately untracked and *not*
   gitignored. A blanket add would stage all of it.
2. Stage only the explicit paths listed below.
3. Do not commit `Refrence/`, `dist/`, `node_modules/`, `*.tsbuildinfo`.
4. Do not merge, do not push to `main`/`ML_Model`, do not open a PR, do not
   force-push. Optionally push only to `origin/feat/renewable-forecast-frontend`.
5. Take a checkpoint first so this is fully reversible.

## 3. Checkpoint (do this first)

```bash
git rev-parse HEAD                       # expect f616d5e
git status --short                       # snapshot the working tree
git diff > /tmp/rf-verify/pre-commit.diff   # backup of tracked changes
git bundle create /tmp/rf-verify/pre-commit.bundle --all   # full-branch backup
```

Rollback of any commit made by this plan (before push):
`git reset --soft f616d5e` (keeps all files, moves branch tip back).

## 4. Commit sequence

Each block is a self-contained, buildable commit. `git add -- <path>` stages
modifications **and** deletions inside that path.

### Commit 1 — tooling/design tokens
```bash
git add -- .gitignore src/styles/tokens.css
git commit -m "chore: ignore tsbuildinfo and keep Tailwind out of reference material"
```
Paths: `.gitignore` (`*.tsbuildinfo`), `src/styles/tokens.css` (`@source not "…/Refrence"`).

### Commit 2 — derivation layer + hooks
```bash
git add -- src/lib/derive src/hooks src/types.ts
git commit -m "feat(derive): add deterministic balance, reliability, seasonal, capacity and investment models"
```
Adds `src/lib/derive/*` (9 files), `src/hooks/{useDashboard,useMeasure,useActiveSection}.ts`;
`src/types.ts` drops the duplicate `config`. Builds independently (nothing imports the removed export).

### Commit 3 — console primitives + styles
```bash
git add -- src/components/ui src/styles/dashboard.css src/main.tsx
git commit -m "feat(console): add ruled-grid primitives and console styles"
```
Adds `DashedLine`, `CellGrid`, `SquareIconButton`, `dashboard.css`; `main.tsx` imports it.

### Commit 4 — dashboard rebuilt as a decision console
```bash
git add -- src/components/dashboard src/components/charts src/pages/Dashboard.tsx
git commit -m "feat(dashboard): rebuild explorer as a decision console with run rail and seven sections"
```
Adds `RunRail`, `Section`, `sections.ts`, `DecisionCallout`, `BalancePanel`/`BalanceChart`,
`ReliabilityPanel`, `SeasonalPanel`, `CapacityPanel`, `InvestmentPanel`, `ForecastPanel`;
modifies `ControlsPanel`, `ForecastTable`, `ForecastBandChart`;
deletes `MixChart.tsx`, `BalanceModule.tsx`, `RunSummary.tsx`, `SitesTable.tsx`;
rewrites `Dashboard.tsx` (7 sections §01–§07).

### Commit 5 — landing + shared styling + mock fix
```bash
git add -- src/pages/Landing.tsx src/components/SiteFooter.tsx src/styles/global.css src/api/mock.ts
git commit -m "feat(landing): refresh landing shell and fix multi-day solar diurnal shape"
```

### Commit 6 — docs
```bash
git add -- DASHBOARD_PLAN.md
git commit -m "docs: add decision-console implementation plan and verification record"
```

### Commit 7 (optional) — this plan
```bash
git add -- GIT_APPEND_PLAN.md
git commit -m "docs: add branch append plan"
```

> Prefer a single squashed commit instead? Replace commits 1–7 with:
> `git add -- .gitignore src DASHBOARD_PLAN.md` then one commit. The explicit
> path `src` still excludes `Refrence/`.

## 5. Verify after committing

```bash
git log --oneline --decorate -8          # new commits sit on top of f616d5e
git status --short                       # only Refrence/ + GIT_APPEND_PLAN.md (if not committed)
git show --stat HEAD                     # sanity-check the last commit's paths
git diff --cached --name-only            # must be empty
git ls-files | rg "^Refrence/"           # must output nothing
npm run typecheck && npm run build       # confirm final tree is green
```

Success criteria:
- `git log` shows `f616d5e` followed by our commits on `feat/renewable-forecast-frontend`.
- No commit touches `Refrence/`, `dist/`, `node_modules/`.
- Branch has **not** been merged into `main` or `ML_Model`.

## 6. Pushing (hold by default)

Nothing is pushed by this plan. When you decide, the same-branch update is:
```bash
git push origin feat/renewable-forecast-frontend
```
That is **not** a merge. Leave `main`, `ML_Model`, `frontend2`, and PRs untouched
"as of now".

## 7. Open decision

Confirm one of:
- **A (recommended):** the 6–7 logical commits above, no push.
- **B:** one squashed commit, no push.
- **C:** logical commits **and** push to `origin/feat/renewable-forecast-frontend`.
