# Ideas (out of scope tonight)
- Confidence calibration: qwen2.5-3b reports 1.0 for nearly every rule. A deterministic statement–formula consistency check (every threshold number and comparison operator in the formula must appear in the statement) could replace self-reported confidence.
- Operator fidelity: BR-038 (claims) says "greater than or equal to 56" but the flow uses `greater`. The same consistency check would catch this.
