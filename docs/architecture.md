# Architecture

The factory is a Python package (`factory/`) plus a small .NET Power Fx host (`tools/fxhost/`). Every stage reads committed inputs and writes committed, diffable artefacts, so CI can rerun any stage and fail on drift.

```mermaid
flowchart LR
  subgraph Legacy["Legacy Power Platform (read-only)"]
    A1[Canvas app<br/>.msapp / .pa.yaml]
    A2[Dataverse<br/>Entity.xml, roles]
    A3[Cloud flows<br/>WDL JSON]
  end
  subgraph Analyse["Analyse (deterministic first)"]
    P[Parsers + Power Fx parse<br/>Microsoft.PowerFx 1.8.1]
    C[Candidate policy<br/>candidates.vN]
    L[Local LLM interpret<br/>prompts/analyse/interpret.vN<br/>cache + audit log]
    F[Deterministic flags<br/>review, contradiction, fairness]
  end
  subgraph Generate["Generate (deterministic)"]
    D[design.json]
    G1[.NET 8 API + Domain<br/>AST to C#]
    G2[React UI]
    G3[Cosmos containers<br/>+ Bicep + Compose]
  end
  subgraph Prove["Prove parity"]
    O[Power Fx interpreter<br/>= oracle]
    H[Frozen test sets<br/>SHA-256 lock]
    X[Generated C#<br/>= subject]
    S[Scenario journey<br/>docker compose]
    R[parity-report]
  end
  subgraph Improve["Self-improve"]
    SC[score.py]
    E[One-variable experiments<br/>tuning vs held-out]
  end
  EV[Evidence: traceability matrix,<br/>HUMAN_REVIEW.md, dashboard]
  A1 & A2 & A3 --> P --> C --> L --> F --> CAT[(rule-catalogue.json)]
  P --> D
  CAT --> D --> G1 & G2 & G3
  H --> O & X --> R
  G3 --> S --> R
  CAT & R --> SC --> E --> C & L
  CAT & D & R --> EV
```

Exported SVG: [architecture.svg](architecture.svg).

## Stages and trust boundaries

| Stage | Who decides | LLM role | Output |
|---|---|---|---|
| Parse | Deterministic parsers, Power Fx parser | none | `factory/out/<app>/model.json` |
| Candidate selection | Versioned deterministic policy | none | candidate sites |
| Interpretation | LLM, constrained JSON | writes the plain-English statement and category | catalogue fields marked as model output |
| Flags | Deterministic code (ADR-008) | none: cannot set or clear review flags | `flags` |
| Generate | Deterministic AST to C# transpiler | none | `generated/<app>/` |
| Parity | Power Fx interpreter vs generated C# | none | `parity/reports/<app>/` |
| Improve | `score.py` + keep/revert rule | critic proposes one change | `experiments/` |

## Target architecture (Azure)

- **API**: ASP.NET Core 8 minimal API in Azure Container Apps, with built-in auth (Entra ID). Legacy security roles become Entra app roles; BusinessUnit-scoped privileges need a `businessUnit` claim and fail closed without one.
- **Data**: Cosmos DB for NoSQL, one container per Dataverse table. Each partition key and the reason for it are recorded in `design.json`; child rows are partitioned by their parent so the app's reads stay single-partition. Bicep sets `disableLocalAuth: true`. The offline demo uses a file-backed store with the same partition-key contract; `docker compose --profile cosmos` runs against the Cosmos emulator instead.
- **Flows**: mapped in `design.json` to Azure Functions (timer and Cosmos change-feed triggers) or Durable Functions orchestrations. These are **design only**. No function code is generated (see `KNOWN_FAILURES.md`).
- **UI**: React + Vite static build, served by nginx in Compose. In Azure it would be served by Static Web Apps, but browser sign-in is not implemented (Q6).
- **IaC**: `generated/<app>/infra/main.bicep` (compiles in CI; never deployed in this run).
