# Progress log (UTC+0, append-only)

- 2026-11-16 01:05 Brief received. Run started.
- 2026-11-16 01:10 Tooling verified: .NET 8.0.428 installed, Power Fx 1.8.1 parse+eval verified, no hosted LLM key → local Qwen2.5-3B via llama.cpp (17.6 tok/s measured).
- 2026-11-16 01:15 Legacy app: Approvals Kit satisfies criteria 1–4 (ADR-001).
- 2026-11-16 01:30 Phase 0 start: skeleton, schema contract frozen (`schemas/SCHEMA.lock`).
- 2026-11-16 01:50 Phase 0 done: PR #1 CI green (lint, typecheck, unit, security).
- 2026-11-16 02:30 Phase 1: Power Fx host (Microsoft.PowerFx 1.8.1) + deterministic parsers for .msapp JSON, .pa.yaml, Entity.xml, roles, WDL flows. Measured: approvals-kit 2488 sites, Power Fx parsed 2254/2254; claims-workbench (synthetic held-out) 96 sites, 59/59. 13 tests pass.
- 2026-11-16 03:40 Phase 2 done. Each agent call is cached by prompt hash, written to an append-only audit log and covered by injection tests. Measured results:
  - approvals-kit: 170 candidates -> 158 rules; recall vs frozen ground truth 119/124; 39 rules need review. First run took 8m19s wall-clock, 90,718 tokens, 170 calls. Replay of both apps took 0.42s with 216/216 cache hits.
  - claims-workbench: 46 candidates -> 44 rules; 25 executed-oracle-eligible; screen/flow four-eyes boundary contradiction flagged (BR-019 <-> BR-042); injected comment capped at confidence 0.5 and sent to review. 23 tests pass.
