# Ideas (out of scope tonight)
- Confidence calibration: qwen2.5-3b reports 1.0 for nearly every rule. A deterministic statement–formula consistency check (every threshold number and comparison operator in the formula must appear in the statement) could replace self-reported confidence.
- Operator fidelity: BR-038 (claims) says "greater than or equal to 56" but the flow uses `greater`. The same consistency check would catch this.
- Promotion gate: require held-out score >= parent before a kept tuning change is promoted (ADR-014 shows why: it3 +0.0015 tuning, -0.0145 held-out).
- Generate Durable Functions code for flows; flows are the largest unproven/unmigrated block in the Approvals Kit and dominate the effort model.
- Bind `Self`/`Parent`/`User()` in the oracle via a canvas-context shim so control-referencing formulas become executable evidence.
- Calibrate model confidence (it is ~1.0 for nearly every rule) or drop it from the catalogue.
