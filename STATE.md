# STATE (resumability file — keep current)

- Current phase: 1 done -> 2 (rule catalogue)
- Done: tool discovery; Approvals Kit chosen (see DECISIONS ADR-001); schema contract written.
- Next: Phase 2 rule-catalogue builder (deterministic candidates + LLM interpretation, cache/replay, audit).
- Run parser: `DOTNET_ROOT=$HOME/.dotnet uv run factory parse approvals-kit claims-workbench` (output under factory/out/, gitignored, regenerated).
- Broken: nothing yet.

## Environment facts a fresh session needs
- .NET 8 SDK: `~/.dotnet/dotnet` (installed via dotnet-install.sh, channel 8.0).
- Local LLM: llama.cpp b12428 `~/tools/llama/llama-b12428/llama-server -m ~/tools/llama/qwen2.5-3b-instruct-q4_k_m.gguf -c 8192 --port 8089 -t 8`
  (measured on this VM: ~17.6 tok/s generation, ~97 tok/s prompt). `make llm` starts it.
- Approvals Kit source: `git clone https://github.com/microsoft/powercat-business-approvals-kit` @ 786b456f0643ef2b6d3109f5dc2f71de05a07dc6 (MIT). Vendored subset under `legacy/approvals-kit/`.
- Power Fx: NuGet Microsoft.PowerFx.Interpreter 1.8.1 (verified parse + eval of If/Switch/With/Filter/DateAdd/DateDiff/Round).
