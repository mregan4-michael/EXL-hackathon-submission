# All targets run offline unless stated. See README.md.
SHELL := /bin/bash
DOTNET ?= $(shell command -v dotnet 2>/dev/null || echo $(HOME)/.dotnet/dotnet)
UV ?= uv
LLAMA_SERVER ?= $(HOME)/tools/llama/llama-b12428/llama-server
LLM_MODEL ?= $(HOME)/tools/llama/qwen2.5-3b-instruct-q4_k_m.gguf

.PHONY: setup lint typecheck test factory parity improve demo verify llm

setup:
	$(UV) sync
	$(UV) run pre-commit install
	@echo "setup complete"

lint:
	$(UV) run ruff check factory
	$(UV) run black --check factory

typecheck:
	$(UV) run mypy

test:
	$(UV) run pytest --cov=factory --cov-report=term

factory:
	$(UV) run factory run --all --replay

parity:
	$(UV) run factory parity --all

improve:
	$(UV) run factory improve --replay

demo:
	./scripts/demo.sh

verify: lint typecheck test parity

llm:
	$(LLAMA_SERVER) -m $(LLM_MODEL) -c 8192 --port 8089 -t 8 --host 127.0.0.1
