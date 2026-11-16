# Known failures

Each entry: what fails, the exact input that triggers it, why, status. Figures come from committed artefacts (`dashboard/index.html`).

| # | What fails | Trigger | Why | Status |
|---|---|---|---|---|
| KF-1 | No Approvals Kit rule has executed or scenario evidence (0 of 158) | `factory parity approvals-kit` | Its rules live in cloud flows, button `OnSelect` actions and Dataverse settings. None compile to a pure formula, and no Approvals Kit journey was built | Open: reported as `unproven` |
| KF-2 | 284 compiled Approvals Kit formulas cannot be executed by the oracle | formulas referencing `Self`, `Parent`, control properties or `User()` | The canvas-free Power Fx interpreter has no control tree or signed-in user | Open: `unproven`, not passed |
| KF-3 | Flows are design only | every `flow:*` row in `traceability-matrix` | `design.json` maps flows to Functions/Durable Functions; no code is generated | Open: counted as not migrated |
| KF-4 | 17 of 105 Claims Workbench mutants survive | `parity-report.md`, mutation section | Frozen cases miss some boundaries for those operators | Open: listed as test gaps; the frozen set was not edited to chase them |
| KF-5 | 18 Claims Workbench rules unproven | `parity-report.json` `rule_evidence` | Flow rules (design only), role privileges not exercised by the journey, and column ranges | Open |
| KF-11 | Dataverse column Min/Max ranges are not enforced by the generated API | e.g. `clm_Claim.clm_ClaimAmount` MaxValue 10000000 (`Entity.xml:26`) | The generator records field types and required flags but not ranges | Open: rows show "no generated target" in the traceability matrix |
| KF-12 | Phase 2 recall (119/124, 158 rules) is not reproducible by the it0 baseline (115/124, 150 rules) | `PROGRESS.md` Phase 2 entry vs `experiments/runs/it0-baseline.json` | Prompt construction changed in `fea829b` (escaped source description), so prompts and therefore model answers changed | Superseded: the leaderboard figures are the comparable ones |
| KF-6 | Azure browser sign-in is not implemented | deploying the React UI outside `Identity:Mode=demo` | Needs MSAL.js or a Static Web Apps linked backend (Q6) | Open: the API fails closed |
| KF-7 | Model confidence is uninformative | `confidence` in `rule-catalogue.json` | Qwen2.5-3B returns ~1.0 for nearly every rule | Open: not used to skip review |
| KF-8 | it3 tuning gain did not generalise | `experiments/leaderboard.md` it3 row | +0.0015 tuning, -0.0145 held-out (ADR-014) | Accepted per protocol; disclosed |
| KF-9 | `RBAC-001` (ClaimsHandler create claim) changes legacy privileges | `factory/fixtures/claims-workbench/rbac-decisions.json` | Legacy roles grant no create privilege (Q5) | Approved by the repository owner (2026-11-16); insurer business owner must re-confirm before go-live |
| KF-10 | Nothing was deployed to Azure | `generated/*/infra/main.bicep` | No subscription in this run; Bicep compiles only | Open |
