# Scoring (`score.py`)

```
score = 0.40 * executed_oracle_parity_rate
      + 0.20 * rule_recall_vs_ground_truth
      + 0.15 * (1 - human_review_rate)
      + 0.15 * generated_test_pass_rate
      + 0.10 * cost_efficiency
```

## Rule recall
`experiments/ground-truth/approvals-kit.json` holds 124 source locations (file + path) that I hand-labelled as business rules once, before any tuning. Its SHA-256 is in `experiments/ground-truth/GROUNDTRUTH.lock`, and every scoring run verifies it.

Labelling method: I read every deterministic candidate site and removed UI glue, display-only lookups, logging and plumbing. Each exclusion pattern is listed in the commit that created the file. Calculated columns in this kit only concatenate display names, so none are labelled as rules.

`rule_recall_vs_ground_truth` is the number of ground-truth locations that appear in some catalogue rule's `source_locations`, divided by 124.

The synthetic held-out app has no rules document (brief, section 4). Its score therefore omits recall, and the remaining weights are renormalised (ADR-005).
