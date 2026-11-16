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
