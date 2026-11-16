# Deck outline (10 slides, ~8 minutes)

Every number on a slide must match `dashboard/index.html` on the day. Regenerate with `make factory`.

1. **The problem.** A UK insurer has about 30 Power Platform apps. The business rules are undocumented, spread across formulas, flows, Dataverse and roles. The risk is not rewriting the code; it is losing a rule nobody wrote down.
2. **Our answer in one line.** A factory that extracts every rule with its source line, generates the .NET/React/Cosmos target deterministically, and proves each rule against Microsoft's own Power Fx runtime. Whatever it cannot prove, it says so.
3. **Pipeline.** `docs/architecture.svg`. Mark the two trust anchors: deterministic parse/generate, and the Power Fx interpreter as oracle.
4. **Real app, real result.** Microsoft Business Approvals Kit (real, MIT): 158 rules from 170 candidates, 117 of 124 hand-labelled rules found, 1,464 compiled formulas pass the oracle with 0 fails. Then say the hard part plainly: 0 of 158 rules are proven, because they live in flows and control-bound formulas.
5. **Insurance journey.** Synthetic Claims Workbench: 25 of 45 rules proven by the executed oracle over 1,209 frozen cases, 2 by a named journey, 18 unproven, 0 failed. Live demo (slide 6).
6. **Live demo.** `make demo`: intake → triage → settlement → payment, then an over-authority payment refused (409) and an Auditor refused (403). About 13 s on a warm Docker cache.
7. **Evidence the jury can audit.** Traceability matrix (source line → rule → generated symbol → parity cases), mutation score 88/105, `HUMAN_REVIEW.md` (35 items, model cannot remove any).
8. **It gets better, honestly.** Leaderboard: 4 one-variable iterations, one reverted, held-out app scored only in aggregate. it3 raised tuning by +0.0015 but the held-out score fell; we show it.
9. **Responsible AI.** Model explains, code decides. Injection test, fairness flags, local model, so no data leaves the tenant, plus a full audit log and offline replay.
10. **30-app plan and the ask.** Editable effort model. At the default assumptions it projects ~27 weeks for 6 engineers, which does not fit 12 weeks. The gap is flows (67% of rules not migrated, mean of both apps), so the first investment is Durable Functions generation. Ask: 3 representative apps in week 1 to calibrate the effort model with measured rates.
