# Lemma Makefile targets

.PHONY: help install setup test test-unit test-slow loop clean extension

help:
	@echo "Lemma Makefile targets:"
	@echo ""
	@echo "  make setup       Check tools, uv sync, clone ssb-dbgen"
	@echo "  make install     Same as setup (alias)"
	@echo "  make test        Run unit tests (verus transpiler, extension)"
	@echo "  make test-slow   Run Verus functional tests (requires verus in PATH)"
	@echo "  make loop        One research-loop iteration (Q1, 50k rows)"
	@echo "  make extension   Build DuckDB loadable extensions under build/"
	@echo "  make clean       Remove build artifacts, temp dirs, __pycache__"
	@echo ""
	@echo "Repo layout (high level):"
	@echo "  verus_transpiler/ SQL → Verus transpiler"
	@echo "  db_extension/     DuckDB extension + OpenRouter agent (legacy Dafny bodies)"
	@echo "  db_extension_*    H1 path agents (copy/chunk/lease/storage)"
	@echo "  research_loop/    Verify, compile, benchmarks, agent sandbox"
	@echo "  scripts/          demo.sh, mockdemo.sh, duckdb_shell.sh, dataset build"

install: setup

setup:
	./scripts/setup.sh

test: test-unit

test-unit:
	uv run pytest tests/ -q
	uv run pytest db_extension/test_extension.py -v

test-slow:
	RUN_SLOW=1 uv run pytest tests/ -k functional -v

loop:
	uv run python research_loop/harness.py -q 1 --dataset-size 50000

extension:
	mkdir -p build
	g++ -shared -o build/lemma.duckdb_extension -fPIC \
		db_extension/src/lemma.cpp \
		-Idb_extension/extension-template-c/duckdb_capi \
		-DDUCKDB_EXTENSION_NAME=lemma
	python3 db_extension/extension-template-c/extension-ci-tools/scripts/append_extension_metadata.py \
		-l build/lemma.duckdb_extension \
		-n lemma \
		-dv v1.2.0 \
		-p linux_amd64_gcc4 \
		-ev 0.0.1 \
		-o build/lemma.duckdb_extension

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf research_loop/temp_build research_loop/bench_build research_loop/scratch_timing \
		research_loop/temp_* build configure
