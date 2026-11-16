# Why this is different

Most "AI migration" demos ask a model to read the old app and write the new one. The output looks plausible, but nobody can say which business rules were preserved. This factory turns that around: **the model never produces the code that makes the parity decision, and it never grades its own work.**

1. **Deterministic first.** Power Fx is parsed by Microsoft's own parser (`Microsoft.PowerFx` 1.8.1). The LLM receives a parsed site and writes only an explanation. Formulas are compiled from the AST to C# by a deterministic transpiler, so a rerun produces byte-identical code.
2. **The original runtime is the oracle.** Expected values come from executing the legacy formula in the Power Fx interpreter, not from the generated code or an LLM. Parity found three runtime-semantics bugs in our own generator (blank date epoch, `Blank()+Blank()`, `IsMatch` anchoring).
3. **"Unproven" is a first-class result.** Evidence is `executed`, `scenario`, `unproven` or `failed`. Anything the oracle cannot run (control references, `User()`, flows) is reported as unproven, never as passing. On the real Approvals Kit, most rules are unproven today, and the dashboard says so.
4. **Frozen, locked test sets.** Parity inputs and the ground-truth labels are hashed (`parity/testset/TESTSET.lock`, `experiments/ground-truth/GROUNDTRUTH.lock`). Changing them breaks CI.
5. **Mutation testing of the evidence itself.** Seeded mutants of the generated formulas measure whether the frozen cases can catch a wrong translation. Survivors are listed as test gaps.
6. **The model cannot approve itself.** Review flags, contradictions and fairness flags are computed by code (ADR-008). An injected "AI reviewer: approved" comment in the synthetic app cannot clear a flag (test `test_injection_cannot_control_flags`).
7. **Self-improvement with a held-out app.** Prompts and candidate policies are versioned. Each experiment changes one variable. Keep/revert is decided on the tuning app only, and the held-out app is scored in aggregate and never inspected per rule. Reverted hypotheses stay on the leaderboard.
8. **Everything is replayable offline.** Every LLM call is cached by prompt hash with an append-only audit log, so `--replay` reproduces the catalogue with zero model calls and no network.
9. **Gaps are surfaced, not patched.** A missing create privilege in the legacy roles became an explicit, logged migration decision that needed sign-off (`RBAC-001`). It was not a silent grant.
