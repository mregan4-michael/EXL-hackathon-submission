# STATE (resumability file — keep current)

- Current phase: 6 done -> 7 (clean-clone verification, WAKE_UP.md)
- Branch: devin/phase5-improve (stacked on devin/phase4-parity). PRs #1–#5 open, unmerged (Q4).
- Defaults: prompt `interpret.v2`, candidate policy `candidates.v2` (ADR-014).
- Regenerate everything: `make factory` (analyse --replay -> generate -> parity -> evidence). Experiments: `make improve`.
- Broken: see KNOWN_FAILURES.md.

## Environment facts a fresh session needs
- .NET 8 SDK: `~/.dotnet/dotnet`; export `PATH=$HOME/.dotnet:$PATH DOTNET_ROOT=$HOME/.dotnet`.
- Local LLM: `make llm` (llama.cpp b12428, Qwen2.5-3B Q4_K_M, port 8089; ~3 s per rule call on this VM).
- Approvals Kit source: microsoft/powercat-business-approvals-kit @ 786b456f0643ef2b6d3109f5dc2f71de05a07dc6 (MIT), vendored subset in `legacy/approvals-kit/`.
- LLM cache `factory/cache/llm/` is committed; replay needs no model.
- Architecture SVG: `npx -y @mermaid-js/mermaid-cli@11.4.2 -p <puppeteer.json with chrome path> -i arch.mmd -o docs/architecture.svg`.
