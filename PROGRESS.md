# Progress log (UTC+0, append-only)

- 2026-11-16 01:05 Brief received. Run started.
- 2026-11-16 01:10 Tooling verified: .NET 8.0.428 installed, Power Fx 1.8.1 parse+eval verified, no hosted LLM key → local Qwen2.5-3B via llama.cpp (17.6 tok/s measured).
- 2026-11-16 01:15 Legacy app: Approvals Kit satisfies criteria 1–4 (ADR-001).
- 2026-11-16 01:30 Phase 0 start: skeleton, schema contract frozen (`schemas/SCHEMA.lock`).
- 2026-11-16 01:50 Phase 0 done: PR #1 CI green (lint, typecheck, unit, security).
- 2026-11-16 02:30 Phase 1: Power Fx host (Microsoft.PowerFx 1.8.1) + deterministic parsers for .msapp JSON, .pa.yaml, Entity.xml, roles, WDL flows. Measured: approvals-kit 2488 sites, Power Fx parsed 2254/2254; claims-workbench (synthetic held-out) 96 sites, 59/59. 13 tests pass.
