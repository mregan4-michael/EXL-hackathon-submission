# Questions I would have asked (answered myself, per the brief)

1. **No LLM API key was provided. Use a hosted model?** Picked: local Qwen2.5-3B via llama.cpp (ADR-002). Swap by setting `FACTORY_LLM_BASE_URL`/`FACTORY_LLM_MODEL`/`FACTORY_LLM_API_KEY`.
2. **Held-out recall needs ground truth, but no rules doc may exist for the synthetic app.** Picked: held-out score excludes recall and is renormalised (ADR-005).
3. **Squash merge (brief) vs my earlier note "merge commits only".** Picked: the brief, as the more recent and explicit instruction.
