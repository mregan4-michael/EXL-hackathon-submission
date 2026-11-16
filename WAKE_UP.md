# WAKE UP — read this first

## Headline
The factory takes a real Microsoft Power Platform app (Business Approvals Kit, MIT) and a synthetic held-out insurance app (Claims Workbench). It reverse-engineers source-traced business rules, deterministically generates a .NET 8 / React / Cosmos DB / Bicep target, and proves behaviour formula by formula against **Microsoft's own Power Fx interpreter**. Everything runs offline, and every model call is replayable from the committed cache.

Three measured numbers:
- **45 of 45** compiled Claims Workbench formulas agree with the Power Fx oracle on **1,209** frozen cases, with 0 failures and 0 oracle drift. Approvals Kit: 1,464 pass, 0 fail, 284 not executable (not counted as passes).
- **203** source-traced rules (Approvals Kit 158, Claims Workbench 45). Recall on the tuning app is **117/124** against hand-labelled ground truth that was frozen before tuning.
- `make demo` runs parse → replayed analysis → generate → `docker compose` → core claim journey in **19.6 s from a clean clone**, after the app images were deleted and the build cache was pruned. The base images (.NET SDK, node) were already pulled. With everything warm it takes 8.5 s.

## PRs (stacked, none merged — Q4)
#1 skeleton → #2 parsers → #3 rule catalogue → #4 generated target → #5 parity → #6 self-improvement + evidence + docs (this branch, `devin/phase5-improve`). Merge them in order, or merge #6 into `main`.

## Run it
```bash
make setup     # uv sync + pre-commit
make demo      # offline core journey (Docker; falls back to `dotnet run` without Docker)
make verify    # ruff, black, mypy --strict, pytest (70), parity --all
make factory   # regenerate catalogues, targets, parity, evidence from the replay cache
make improve   # replay all 4 experiments from cache; fails if any score moves
open dashboard/index.html   # evidence dashboard (self-contained)
```
Model: Qwen2.5-3B Q4_K_M via llama.cpp on CPU (no API key was provided; ADR-002). Replay needs no model.

## Clean-clone verification (Phase 7, done on `bcfb404` + the two review fixes)
`git clone` → `uv sync --frozen` → lint, black, mypy, 68 pytest (70 after the fixes), parse, `make factory`, `make improve`, `parity --all --check`, `make verify`, `make demo`, `dotnet test` (11 passed), `dotnet build` of the Approvals Kit API (0 warnings), `npm ci && tsc --noEmit && vite build`. The tree had **zero git diff** afterwards, so the committed artefacts are exactly what the code regenerates. `az bicep build` was not available locally; it runs in CI (`target` job green on PR #6).

## What works
- Deterministic parsers for .msapp JSON, .pa.yaml, Dataverse `Entity.xml`, security roles and WDL flows. Power Fx parse: 2,254/2,254 and 59/59 formulas.
- Rule catalogue built from deterministic facts plus local-LLM interpretation. Prompts are versioned, there is an append-only audit log, and a prompt-injection test confirms a planted comment cannot remove flags or skip review.
- Generated target: 5 Cosmos containers, 45 formulas compiled AST→C#, 12 explicitly not compiled (each with a reason), 3 action endpoints, fail-closed RBAC (403 for an Auditor, 409 above the payment authority limit).
- Differential parity against a frozen, hash-locked test set, with mutation testing (88/105 Claims Workbench mutants killed, 13/13 Approvals Kit). Parity found and fixed 3 runtime-semantics bugs.
- Phase 5: 4 scored runs, each changing exactly one variable. One hypothesis was reverted (it2). The held-out score is aggregate only and is never used to choose. See `experiments/leaderboard.md`.
- Phase 6: traceability matrix (source line → rule → generated symbol → evidence), `HUMAN_REVIEW.md` (35 items), dashboard with MEASURED / ASSUMPTION / PROJECTION labelling and an editable 30-app effort model, and the full documentation set (`docs/`, `RESPONSIBLE_AI.md`, `AI_TOOLS.md`).

## What is partial (measured, current)
| | Claims Workbench | Approvals Kit |
|---|---|---|
| Rules | 45 | 158 |
| Auto-migrated (every source location has generated code) | 29 (64%) | 4 (3%) |
| Evidence: executed / scenario / unproven / failed | 25 / 2 / 18 / 0 | 0 / 0 / 158 / 0 |
| Human-review queue | 18 | 17 |
| LLM tokens / compute seconds (replay-inclusive) | 27,332 / 471.5 | 106,771 / 2,115.1 |
| Score | 0.6648 (held-out) | 0.5144 (tuning) |

At the default assumptions, the 30-app effort model projects **~161 h per app, ~4,840 h, ~27 weeks for 6 engineers**. That does **not** fit the 12-week window. The gap comes from rules the factory does not migrate (mean 67%, mostly flows). This is a projection, not a measured delivery figure.

## What failed or is not done (full list: `KNOWN_FAILURES.md`)
- **Flows are design only.** Durable Functions are not generated, so no Approvals Kit rule has executed or scenario evidence (KF-1, KF-3).
- **284 Approvals Kit formulas** use `Self`/`Parent`/`User()`, which the canvas-free oracle cannot run. They are reported as unproven (KF-2).
- **Azure browser sign-in (MSAL) is not implemented**, and nothing was deployed to Azure (KF-6, KF-10).
- **Model confidence is useless** (≈1.0 everywhere) and is not used to skip review (KF-7).
- **it3 tuning gain did not generalise:** +0.0015 tuning, −0.0145 held-out. It was promoted anyway, per the pre-registered rule (ADR-014, Q7), and the repository owner approved keeping it (KF-8).
- `RBAC-001` (ClaimsHandler may create a claim) was approved by the repository owner on 2026-11-16 (Q5). The insurer's business owner must still confirm it before go-live.
- Dataverse Min/Max column ranges are not enforced (KF-11). 17 mutants survive (KF-4).

## Self-audit: shortcuts, uncertainty, things I got wrong
- **My Phase 2 recall figure (119/124) is superseded.** Commit `fea829b` hardened prompt construction (escaping the source description), so the prompts changed and the model was called again. The re-run `interpret.v1`/`candidates.v1` baseline (it0) produced 150 rules and 115/124. Same configuration, different prompts, different model answers. The Phase 2 number was measured correctly at the time, but it is not comparable to the leaderboard. Use 115 → 117 (KF-12).
- **PROGRESS.md timestamps for Phases 3–4 were wrong** (written as 04:20 and 05:10; the commits are at 02:14 and 02:42 UTC). A correction is appended, not rewritten.
- **The ground truth was hand-labelled by me** from the same source the factory reads. It was frozen and hash-locked before tuning, but it is one labeller with no inter-rater check.
- **The held-out app is synthetic and authored by me.** It was written before the analysis code ran on it, but it is not an independent, real customer app.
- **Recall is location-based.** It counts a ground-truth source location as found if any rule cites it, which says nothing about the quality of the rule statement.
- **The demo journey's handler-create permission** exists only because of `RBAC-001`. In strict legacy terms, only a System Administrator could create claims.
- **Review round on PR #6:** 2 real bugs fixed. `App.OnStart` was counted as migrated while `gblIsManager` was still blank (Claims Workbench auto-migrated went from 30 to 29), and run loading ignored names without the `it` prefix. One finding was rejected: the `candidates.v3` clause-scoping weakness sits in an immutable, reverted policy version.
- No value was hard-coded, and no test was skipped or loosened. Unsupported items are reported as unproven, not passed.

## Decisions I took for you
`QUESTIONS.md` Q1–Q7. The biggest are: local model instead of a hosted LLM (Q1), not merging (Q4), `RBAC-001` (Q5) and promoting it3 (Q7).
