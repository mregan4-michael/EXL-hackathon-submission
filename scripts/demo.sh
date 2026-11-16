#!/usr/bin/env bash
# One-command offline demo: legacy Power Apps source -> generated .NET/React/Cosmos target -> core journey.
# No cloud, no API keys: the agent step replays cached model responses (fails loudly on a cache miss).
set -euo pipefail
cd "$(dirname "$0")/.."
APP=claims-workbench
start=$(date +%s)
step() { printf '\n== %s (%ss)\n' "$1" "$(( $(date +%s) - start ))"; }

step "1/5 parse legacy source (deterministic)"
uv run factory parse "$APP"
step "2/5 rule catalogue (replayed agent calls)"
uv run factory analyse "$APP" --replay
step "3/5 generate target (.NET 8 API, React, Cosmos design, Bicep, compose)"
uv run factory generate "$APP"

step "4/5 start target"
if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
  (cd "generated/$APP" && docker compose up -d --build)
  trap '(cd "generated/$APP" && docker compose down -v >/dev/null 2>&1) || true' EXIT
  UI="http://localhost:5173"
else
  echo "docker unavailable: running the API directly with dotnet (UI not started)"
  DOTNET=${DOTNET:-$(command -v dotnet || echo "$HOME/.dotnet/dotnet")}
  data=$(mktemp -d)
  Identity__Mode=demo Store__Path="$data" "$DOTNET" run --project "generated/$APP/src/Api/Factory.Api.csproj" >/tmp/factory-api.log 2>&1 &
  trap 'kill $! 2>/dev/null || true' EXIT
  UI="(not started)"
fi
for _ in $(seq 1 60); do curl -sf http://localhost:8080/health >/dev/null && break; sleep 1; done

step "5/5 core journey: intake -> triage -> settlement -> payment -> role refusal"
python3 scripts/journey.py
step "done"
echo "API http://localhost:8080/openapi.json   UI $UI"
if [[ "${KEEP:-0}" == "1" ]]; then trap - EXIT; echo "KEEP=1: target left running"; fi
