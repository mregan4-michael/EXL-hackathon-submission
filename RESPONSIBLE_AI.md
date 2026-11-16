# Responsible AI

Scope: the factory's use of a language model to interpret legacy Power Platform logic for a UK insurer. The migrated application itself makes no AI decisions.

## Where the model is used, and where it is not

| Used for | Not used for |
|---|---|
| Plain-English statement of a parsed rule | Deciding whether a rule needs human review |
| Category (validation, eligibility, calculation, ...) | Generating the C# that is executed |
| Proposing one experiment change (critic) | Producing expected values for parity |
| | Approving, merging or signing off anything |

Model: Qwen2.5-3B-Instruct (Q4_K_M) through llama.cpp on the build VM. No client data leaves the machine, and no hosted API was used in this run. Swapping in Azure OpenAI is a configuration change (`FACTORY_LLM_*`). The same cache, audit and flag rules apply.

## Controls

1. **Human-in-the-loop by construction.** `HUMAN_REVIEW.md` is generated from deterministic flags and failed evidence. The model cannot add rules to it or remove them. Every rule carries source locations (file and line) so a reviewer can check the original.
2. **Transparency.** Each rule records the prompt version, model, cache key and confidence. `factory/out/<app>/audit.jsonl` is append-only, holding prompt hash, response, tokens and time for every call.
3. **Prompt-injection defence.** Legacy source is treated as untrusted data. It is fenced in the prompt, and model output is schema-validated. Flags are computed outside the model, and an injected comment caps confidence at 0.5 and forces review. This is tested against a planted payload in the synthetic app.
4. **Fairness.** Rules whose identifiers refer to protected or proxy characteristics (age, date of birth, gender, postcode, nationality, ethnicity, religion, vulnerability, fraud markers) get a deterministic `fairness_review` flag. Insurance pricing and claims decisions fall under the FCA Consumer Duty and the Equality Act 2010, and a flagged rule must be reviewed by a person with authority to sign it off. The factory does not judge whether a rule is lawful.
5. **Model confidence is not trusted.** The local model rates nearly every rule 1.0, so confidence is recorded but not used to skip review (see `KNOWN_FAILURES.md`).
6. **Data protection.** The synthetic Claims Workbench contains no personal data. For a real estate, run the factory on exported solution files (metadata and formulas), not production Dataverse rows. The generated Cosmos account disables key auth (`disableLocalAuth: true`).
7. **Accountability.** RBAC changes (`RBAC-001`), held-out results and reverted experiments are logged in `DECISIONS.md`, `QUESTIONS.md` and `experiments/leaderboard.md`.

## Known limits

- One small local model. Statements can be vague or wrong, which is why every statement links to source and executable evidence.
- The fairness word list is English and identifier-based. It will miss proxies hidden in data values.
- Parity covers formula behaviour and one end-to-end journey. It does not cover flows, which are design only, or UI layout.
