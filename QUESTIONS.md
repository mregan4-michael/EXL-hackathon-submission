# Questions I would have asked (answered myself, per the brief)

1. **No LLM API key was provided. Use a hosted model?** Picked: local Qwen2.5-3B via llama.cpp (ADR-002). Swap by setting `FACTORY_LLM_BASE_URL`/`FACTORY_LLM_MODEL`/`FACTORY_LLM_API_KEY`.
2. **Held-out recall needs ground truth, but no rules doc may exist for the synthetic app.** Picked: held-out score excludes recall and is renormalised (ADR-005).
3. **Squash merge (brief) vs my earlier note "merge commits only".** Picked: the brief, as the more recent and explicit instruction.

## Q4 Merge PRs to main unattended?
The brief asks for squash-merge per phase, but Devin's tooling blocks merging into `main` without an explicit approval in-session.
**Picked:** do not merge; stack one PR per phase (each PR's base is the previous phase branch). Merge them in order (or merge the last one into main) when you wake.

## Q5 No Claims Workbench role can create a claim
Parsing the roles shows no `prvCreateclm_Claim` grant, so intake (`IntakeScreen/btnSubmit`) only works for System Administrators in the legacy app.
**Picked:** keep legacy privileges exactly (the generator fails closed), and add one explicit, logged migration decision `RBAC-001` (`factory/fixtures/claims-workbench/rbac-decisions.json`) that grants ClaimsHandler Create at User depth. It appears in `design.json` → `rbac_decisions` and in the evidence pack. Delete the file to restore strict legacy behaviour.

## Q6 How do Azure users sign in to the generated UI?
Outside `Identity:Mode=demo` the API ignores `X-Demo-User` and trusts only the Entra principal that Container Apps built-in auth injects (`X-MS-CLIENT-PRINCIPAL`); Entra app roles must be named after the legacy security roles and the token must carry a `businessUnit` claim (absent = no BusinessUnit-scoped rows, fail closed).
**Picked:** secure the API now; the generated React UI still only has the offline demo-user picker. Browser sign-in for Azure (MSAL.js token acquisition, or a Static Web Apps linked backend) is **not implemented** and must be added before any Azure deployment.

## Q7 Promote it3 when its held-out score fell?
**Picked:** yes, because the pre-registered rule decides on tuning only (ADR-014). The decline is shown in the leaderboard and WAKE_UP.md. If you prefer a held-out non-regression gate, revert the defaults to `interpret.v1` (`factory/src/factory/cli.py`) and run `make factory`.
