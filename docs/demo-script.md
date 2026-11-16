# Demo script (5 minutes, offline)

Pre-flight: Docker running, `uv sync` done, `make demo` run once to warm the image cache. No network or API keys are needed.

| Time | Do | Say |
|---|---|---|
| 0:00 | Open `legacy/claims-workbench/CanvasApps/src/SettlementScreen.pa.yaml` at `btnApprovePayment` | "This is the legacy rule: a handler can only approve payments within their authority limit. Nobody documented it." |
| 0:30 | `make demo` | "Parse, replay the agent calls from the cache, generate, start the target, run the journey. No model is called live, so the run is reproducible." |
| 1:15 | Point at `[PASS] over-authority payment refused ... 409` and `Auditor refused payment: 403` | "Both refusals come from the generated guard and the legacy role table, checked server-side." |
| 1:45 | Open `artefacts/claims-workbench/traceability-matrix.html`, find BR-017 | "Source line, plain-English rule, generated C# symbol, number of frozen oracle cases." |
| 2:30 | Open `parity/reports/claims-workbench/parity-report.html` | "Each case is run in Microsoft's Power Fx interpreter on the original formula and in our C#. Zero fails. The mutation score shows how strong the cases are, and the survivors are listed." |
| 3:15 | Open `dashboard/index.html` | "Green is measured, orange is assumption, purple is projection. Approvals Kit: 0 proven rules, and we show that number." Change *Engineers* to 10 to show the model recompute. |
| 4:15 | Open `HUMAN_REVIEW.md` | "35 items. Fairness flags, contradictions, injection. Code decides what goes here, not the model." |
| 4:45 | Open `experiments/leaderboard.md` | "One reverted hypothesis, and one kept change whose held-out score fell. We publish both." |

Fallback if Docker fails: `scripts/demo.sh` falls back to `dotnet run` for the API and runs the same journey. The UI does not start in that mode.
