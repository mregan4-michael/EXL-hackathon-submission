#!/usr/bin/env python3
"""Score the committed artefacts with the Phase 5 objective: `uv run python score.py [app ...]`."""

import json
import sys

from factory.improve.score import score_committed

for app in sys.argv[1:] or ["approvals-kit", "claims-workbench"]:
    print(json.dumps(score_committed(app), indent=1))
