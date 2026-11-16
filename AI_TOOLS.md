# AI tools used

| Tool | Used for | Not used for |
|---|---|---|
| Devin (Cognition AI) | Writing the factory code, tests, docs, ADRs and PRs in this repository, unattended | Hand-editing generated output or metrics (all generated files come from `factory generate` / `factory parity` / `factory evidence`) |
| Qwen2.5-3B-Instruct, Q4_K_M, via llama.cpp b12428 (local CPU) | Runtime interpretation of rule sites (`prompts/analyse/interpret.v*.md`) and the experiment critic (`prompts/improve/critic.v1.md`) | Code generation, parity oracle, review flags |
| Microsoft.PowerFx.Interpreter 1.8.1 | Parsing and executing legacy formulas (the oracle) | Not an AI tool; listed because it is the trust anchor |

Every runtime model call is cached under `factory/cache/llm/` and logged to an audit file, so the run can be replayed with no model. The ground-truth labels in `experiments/ground-truth/` were written by Devin, not by the runtime model. They were frozen before any tuning and are hash-locked.
