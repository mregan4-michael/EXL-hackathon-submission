# Questions I would have asked (answered myself, per the brief)

1. **No LLM API key was provided. Use a hosted model?** Picked: local Qwen2.5-3B via llama.cpp (ADR-002). Swap by setting `FACTORY_LLM_BASE_URL`/`FACTORY_LLM_MODEL`/`FACTORY_LLM_API_KEY`.
2. **Held-out recall needs ground truth, but no rules doc may exist for the synthetic app.** Picked: held-out score excludes recall and is renormalised (ADR-005).
3. **Squash merge (brief) vs my earlier note "merge commits only".** Picked: the brief, as the more recent and explicit instruction.

## Q4 Merge PRs to main unattended?
The brief asks for squash-merge per phase, but Devin's tooling blocks merging into `main` without an explicit approval in-session.
**Picked:** do not merge; stack one PR per phase (each PR's base is the previous phase branch). Merge them in order (or merge the last one into main) when you wake.
