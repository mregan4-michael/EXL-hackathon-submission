# Agentic Power Platform Migration Factory

Converts Microsoft Power Platform apps (canvas Power Fx, Dataverse, cloud flows, security roles) into a .NET 8 API, a React UI, a Cosmos DB design and Azure Bicep. Every rule is traced to its legacy source line and checked against Microsoft's Power Fx interpreter. Rules that cannot be checked are reported as **unproven**.

Start with [`WAKE_UP.md`](WAKE_UP.md), then [`dashboard/index.html`](dashboard/index.html).

## Quick start (offline, no API keys)

```bash
make setup          # uv sync + pre-commit
make demo           # parse -> replayed analysis -> generate -> docker compose -> claims journey
make factory        # regenerate every committed artefact from the LLM cache
make verify         # lint, mypy, pytest, parity --all
make improve        # replay all self-improvement runs; fails if any score moves
```

Needs Python 3.12 + uv, .NET 8 SDK (`DOTNET_ROOT` if it is not on PATH), Node 20 and Docker. A live model is only needed for new analysis (`make llm` starts llama.cpp with Qwen2.5-3B).

## Map

| Path | What |
|---|---|
| `legacy/` | Approvals Kit (real, MIT, pinned) and Claims Workbench (synthetic insurance app, held-out) |
| `factory/src/factory/` | parse, analyse, generate, parity, improve, evidence |
| `artefacts/<app>/` | rule catalogue, analysis report, traceability matrix |
| `generated/<app>/` | generated target (committed; CI fails on drift) |
| `parity/` | frozen test set + lock, parity reports, journey record |
| `experiments/` | ground truth + lock, run records, leaderboard |
| `HUMAN_REVIEW.md` | review queue (deterministic) |
| `docs/` | architecture, scoring, why-different, deck, demo, pitch, Q&A |
| `DECISIONS.md`, `QUESTIONS.md`, `KNOWN_FAILURES.md` | ADRs, decisions taken unattended, known failures |
| `RESPONSIBLE_AI.md`, `AI_TOOLS.md` | RAI controls, tools used |
