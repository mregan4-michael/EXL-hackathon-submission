# Contributing

- Branch from `main` (`feat/...`, `fix/...`), open a PR, squash-merge when CI is green.
- Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`; `test-set:` is reserved for changes to the frozen parity test set).
- `make setup` installs hooks. Never `--no-verify`. Hooks are a convenience; CI is the gate.
- Python: `mypy --strict`, Ruff, Black. C#: nullable on, analyzers as errors, `dotnet format`. TS: `strict`, ESLint, Prettier.
- Never edit `parity/testset/` or `experiments/ground-truth/` except in a dedicated, justified commit (see `DECISIONS.md`).
