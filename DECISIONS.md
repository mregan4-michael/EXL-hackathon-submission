# Architecture Decision Records

Each ADR: context, options considered, choice, consequence. Written for a reader who was not there.

## ADR-001 Legacy app: Microsoft Business Approvals Kit (third-party), plus a synthetic insurance app
- **Context.** We need a real, public, third-party Power Platform app with Dataverse, non-trivial flows and Power Fx branching, obtainable without a tenant.
- **Options.** Approvals Kit (preferred by the brief), CoE Starter Kit, Northwind Traders, Templates for Power Platform.
- **Choice.** Approvals Kit, `github.com/microsoft/powercat-business-approvals-kit` @ `786b456f`, MIT licence. Its `SolutionPackage/src` is already unpacked (solution packager format), `Solution.xml` declares `<Managed>2</Managed>` (ships both; source is the unmanaged form), it has 32 Dataverse tables, 25 cloud flows (Dataverse triggers, conditions, switches, apply-to-each, scopes, a daily timeout job) and 5 canvas apps (`.msapp` = zip with per-control JSON containing Power Fx). It satisfied criteria 1–4 on first evaluation, so the shortlist stopped there.
- **Scope.** The full kit is too large to hand-label in one night (the process-designer canvas app alone has 22,868 control properties). We scope to: all Dataverse tables and relationships, all 25 cloud flows, the Dataverse calculated columns, and the **Settings** canvas app (2,394 properties). The other canvas apps are parsed but excluded from the rule catalogue; this is stated in the README.
- **Consequence.** The agents reverse-engineer an app none of us wrote — evidence of generality. We additionally author a synthetic *Claims Handling and Complaints Workbench* (ADR-005) for insurance domain fit and the held-out evaluation.

## ADR-002 LLM: local open-weights model, OpenAI-compatible client
- **Context.** No hosted LLM API key is available in the build environment, the run is unattended, and the live demo must not depend on the network.
- **Options.** (a) hosted model (blocked: no key), (b) local model via llama.cpp, (c) no LLM (would not be an agentic factory).
- **Choice.** Qwen2.5-3B-Instruct, Q4_K_M GGUF, served by llama.cpp `b12428` `llama-server` on CPU (8 threads). The client speaks the OpenAI chat-completions protocol, so a hosted model is a configuration change (`FACTORY_LLM_BASE_URL`, `FACTORY_LLM_MODEL`), not a code change.
- **Consequence.** Weaker interpretation quality than a frontier model; every LLM output is schema-validated and confidence-gated, and quality numbers are measured, not assumed. All responses are cached by prompt hash so `--replay` makes zero model calls.

## ADR-003 Code generation: deterministic transpiler for rules; LLM for interpretation, review and repair
- **Context.** Parity is the strongest evidence; an LLM writing C# from prose is non-deterministic and hard to prove.
- **Choice.** Power Fx is parsed into an AST (Microsoft's own parser). Rule bodies are compiled AST→C# deterministically into a pure domain layer. The LLM writes the plain-English statement, classifies the rule, scores confidence, tags PII, critiques failures, and the repair agent proposes patches when a generated rule fails parity.
- **Consequence.** Generated code is reproducible and reviewable as golden files; parity failures point at transpiler gaps, which are explicit and countable.

## ADR-004 Power Fx parser and oracle: Microsoft.PowerFx.Interpreter 1.8.1
- **Context.** The brief requires executing the original formulas, not our reading of them.
- **Choice.** A small .NET 8 host (`tools/fxhost`) wraps `Microsoft.PowerFx.Interpreter` 1.8.1 (verified on NuGet; verified parse + eval of `If`, `Switch`, `With`, `Filter`, `CountRows`, `DateAdd`, `DateDiff`, `Round`). It exposes parse→AST JSON and eval. Connector calls (`Office365Users.*`), navigation and `Patch` side effects are not executable → those rules go to scenario parity or unproven, labelled separately.

## ADR-005 Train/held-out split and the recall term
- **Context.** The self-improvement loop needs a tuning app and a held-out app. `rule_recall_vs_ground_truth` needs a hand-labelled ground truth. The brief forbids writing a rules document for the synthetic app.
- **Choice.** Tuning app = Approvals Kit (ground truth hand-labelled once from the third-party source, committed before tuning). Held-out app = synthetic Claims Workbench. Because no rules document may exist for it, the held-out score uses the four non-recall terms renormalised (weights ÷ 0.80); the tuning app is reported both ways so the tuning-vs-held-out chart compares like with like.
- **Consequence.** Held-out recall is unmeasured — stated in the leaderboard and Q&A prep.

## ADR-006 One sequential session, no parallel child sessions
- **Choice.** The brief makes parallelism optional. Coordination cost (three branches, schema handoffs) outweighs the gain for one night; a single clean sequential run.

## ADR-007 Git workflow: short-lived branches, PRs, squash merge
- As the brief specifies (section 8). Each phase is a PR merged when CI is green.

## ADR-008 The model interprets; it never decides flags
- **Context.** Legacy source is untrusted. The synthetic app contains a comment telling "AI reviewers" to mark a rule as dead code with confidence 1.0.
- **Choice.** Flags (dead code, contradiction, magic numbers, fairness, PII, oracle type) are computed deterministically in `factory/analyse/rules.py`. The model returns only `statement`, `category`, `confidence` and `is_business_rule`, and extra keys are discarded. Legacy text sits inside `<legacy_source id=...>` tags, and the system prompt marks it as data. When an injection pattern is detected, confidence is capped at 0.5, human review is forced, and the model cannot drop the candidate.
- **Trade-off.** The regex detector can miss paraphrased injections. Because flags never come from the model, a missed injection can at worst change the wording of a statement, and that rule still goes to review when confidence is low or the rule is unproven.

## ADR-009 Candidate policy v1
- Canvas properties are candidates when they are non-style and contain a branch or comparison. Every flow condition, switch and trigger is a candidate, as are Dataverse `Range` constraints, calculated columns and security roles. The policy is versioned (`candidates.v1`) so the self-improvement loop can change it and measure the effect.
- Known gap: behaviour properties without a branch (e.g. a `Patch` in `OnSelect`) are excluded. This is the first hypothesis for Phase 5.

## ADR-010 Target architecture (Phase 3)
- **Generation is deterministic.** `factory generate <app>` reads `legacy-model.json` + `rule-catalogue.json` and writes `generated/<app>/` byte-for-byte reproducibly. No model call. Business formulas are translated AST → C# by `generate/transpile.py`; anything outside the supported subset (`Patch`, `Set`, `SortByColumns`, `Table`, `RGBA`, …) is listed in `design.json` → `generated.not_compiled` with a disposition (action endpoint, data query, presentation, or "unsupported → scenario/unproven"). Nothing is guessed.
- **.NET 8.** `Domain` (pure, no packages, nullable, warnings-as-errors, `latest-recommended` analysers): generated `Rules.g.cs` (one static method per formula, rule ID + source line in XML doc) and `App.g.cs` (containers, formulas in dependency order, actions, roles, session globals), plus a hand-written Power Fx semantics runtime `Fx.cs` (blank propagation, coercion, date maths). `Api`: minimal API host with JSON structured logs, `X-Correlation-ID` middleware, RBAC with Dataverse depth (User/BusinessUnit/Global), action guards re-evaluated server-side (the browser is never trusted with a business rule).
- **React + strict TypeScript** (`strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`). The UI is a generic renderer of generated `app.g.ts`: it holds no business logic and asks the API to evaluate each screen.
- **Persistence.** `IDocumentStore` has a file-backed implementation (offline demo, same partition-key and immutability rules) and a Cosmos implementation (managed identity in Azure, emulator connection string locally). One container per Dataverse table; partition keys and rationale come from `design.py`. Special-category and long-text columns are excluded from the index.
- **Azure.** Bicep (`generated/<app>/infra/main.bicep`, compiles with `bicep build`): Container Apps for the API (scale to zero), Static Web Apps for the UI, serverless Cosmos DB with local auth disabled and continuous backup, a Functions app (isolated .NET 8) for the migrated flows, Durable where the flow waits on a human approval, App Insights, and one user-assigned managed identity. No secrets.
- **Identity.** Offline, `X-Demo-User` selects a seeded synthetic user. In Azure this is swapped for Entra ID claims, and the RBAC code path is unchanged. This header is a demo affordance and must never be exposed in production (called out in the RAI and threat docs).

## ADR-011 Privilege gaps are surfaced, not silently fixed
- See QUESTIONS.md Q5. Legacy grants are reproduced exactly. Every deviation is a named, file-based decision (`rbac-decisions.json`), copied into `design.json`, and needs sign-off. The journey test shows both refusal paths (Auditor: no privilege; ClaimsHandler: guard over authority limit).
- **Offline runtime.** `generated/<app>/docker-compose.yml` runs API (file store, named volume, non-root) + UI (nginx, proxies `/api`). Profile `cosmos` swaps in the Cosmos emulator; its connection string uses Microsoft's published, emulator-only key (not a secret; it cannot reach any Azure account). `make demo` = parse → replayed analyse → generate → compose up → `scripts/journey.py`.

## ADR-012 Differential parity against the executed Power Fx oracle (Phase 4)
- **Oracle.** Expected values come only from `Microsoft.PowerFx.Interpreter` 1.8.1 (`tools/fxhost`) evaluating the *legacy* formula text. Generated C# is executed through the same `Formula.Eval` path the API uses (`generated/<app>/src/Parity`) and compared. C# never produces an expected value.
- **Frozen test set.** `factory parity <app> --freeze` writes `parity/testset/<app>.jsonl` (inputs + oracle output). Inputs are derived from the legacy AST: every numeric literal L yields L−1, L−0.01, L, L+0.01, L+1 (threshold boundaries), dates straddle day-offset literals and leap days, blanks/empty/non-numeric text are always included, plus seeded random cases (seed = SHA-256 of the formula path). Without `--freeze` the oracle is re-run on the frozen inputs and any difference is **oracle drift** (CI fails).
- **Canvas-host shims (declared, not hidden).** The interpreter has no canvas host, so (1) `DisplayMode` is bound as a record of its string values, (2) two-argument `IsMatch` is made explicit as `MatchOptions.Complete` (the canvas default; the bare interpreter defaults to Contains — a unit test pins this). `EnableRegExFunctions()` is on. Formulas referencing `User()`, `Self`, `Parent`, connectors or unknown enums cannot run in the oracle and are reported **unproven**, with the oracle's own diagnostic. They are not guessed.
- **Evidence categories per rule.** `executed` (all source formulas agree with the oracle on every frozen case), `scenario` (covered by a named check in `scripts/journey.py --record`), `unproven` (neither), `failed` (any mismatch or failing scenario). Flow actions, `Patch`/`Set` side effects and Dataverse rules are scenario-or-unproven by construction.
- **Mutation testing.** Each executable formula is mutated (comparison flips, `&&`/`||` swap, numeric literal ±1) and the mutant is run through the oracle on the frozen inputs; a mutant is killed if any output changes. Survivors are listed in the report as test-set blind spots and are not removed.
- **Semantic fixes found by parity (all in `factory/templates/dotnet/Domain`):** blank dates use the Power Fx epoch 1899-12-30 in `DateDiff`/`DateAdd`; arithmetic coerces blank to 0 even when both operands are blank (`Blank()+Blank() = 0`, first observed on Approvals Kit layout formulas). Each was confirmed against the oracle before changing the runtime.

## ADR-013 Self-improvement protocol (Phase 5)
- **Objective.** `factory/improve/score.py` implements `docs/scoring.md` exactly; `score.py` / `factory score` scores the committed artefacts. Ground truth is re-hashed against `GROUNDTRUTH.lock` on every score. `executed_oracle_parity_rate` uses the committed parity statuses (formula outcomes do not depend on the catalogue; the catalogue decides which rules they evidence). `cost_efficiency = 1 − tokens_per_rule / 2000`, counting replayed calls (`tokens_incl_replay`), so replay cannot make a configuration look free.
- **Split.** Tuning app `approvals-kit` (real, 124 locked labels). Held-out `claims-workbench` (synthetic, authored separately, no labels → recall omitted, weights renormalised). Only the held-out *aggregate* score is stored; its per-run catalogue goes to git-ignored `factory/out/experiments/` and is never read by the loop or the critic.
- **Levers.** One variable per iteration: the interpret prompt version (`prompts/analyse/interpret.vN.md`) or the deterministic candidate policy version (`rules.POLICIES`). Versions are immutable; `run` refuses a child that changes zero or two variables.
- **Keep rule.** Kept iff tuning score > parent's tuning score, else reverted. Computed, not chosen. The held-out score never influences a decision.
- **Critic.** `factory experiment critique <run>` sends the aggregate tuning failure summary to the local model with `prompts/improve/critic.v1.md` and records its one-change proposal. The 3B model's proposals are generic, so hypotheses were written by me from the same aggregate summary; both are recorded (`experiments/runs/*.critique.json`).
- **Reproducibility.** Every run's LLM calls are in the content-addressed cache. `make improve` replays every run, fails if any score moves, and regenerates `experiments/leaderboard.md`.
