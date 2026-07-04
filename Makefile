# Lemma — common targets. Run `make help` for descriptions.

.PHONY: help install test test-unit test-slow loop clean extension

help:
	@echo "Lemma Makefile targets:"
	@echo ""
	@echo "  make install     Install Python deps (uv sync)"
	@echo "  make test        Run unit tests (transpiler, extension, postprocessor)"
	@echo "  make test-slow   Run Dafny functional tests (requires dafny in PATH)"
	@echo "  make loop        One research-loop iteration (Q1, 50k rows)"
	@echo "  make extension   Build DuckDB loadable extensions under build/"
	@echo "  make clean       Remove build artifacts, temp dirs, __pycache__"
	@echo ""
	@echo "Repo layout (high level):"
	@echo "  transpiler/       SQL → Dafny transpiler"
	@echo "  db_extension/     DuckDB extension + optimizer"
	@echo "  research_loop/    Verify, compile, benchmarks, agent sandbox"
	@echo "  scripts/          demo.sh, mockdemo.sh, duckdb_shell.sh, dataset build"
	@echo "  data/benchmarks/  Scaling benchmark JSON"
	@echo "  plots/            Benchmark figures"
	@echo "  design_docs/      Design notes"

install:
	uv sync

test: test-unit

test-unit:
	uv run pytest transpiler/tests/test_unit.py -v
	uv run pytest db_extension/test_extension.py -v
	uv run pytest research_loop/test_postprocessor.py -v

test-slow:
	RUN_SLOW=1 uv run pytest transpiler/tests/test_functional.py -v

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
	g++ -shared -o build/lemma_python.duckdb_extension -fPIC \
		db_extension/src/lemma.cpp \
		-Idb_extension/extension-template-c/duckdb_capi \
		-DDUCKDB_EXTENSION_NAME=lemma_python
	python3 db_extension/extension-template-c/extension-ci-tools/scripts/append_extension_metadata.py \
		-l build/lemma_python.duckdb_extension \
		-n lemma_python \
		-dv v1.2.0 \
		-p linux_amd64 \
		-ev 0.0.1 \
		-o build/lemma_python.duckdb_extension

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf research_loop/temp_build research_loop/bench_build research_loop/scratch_timing \
		research_loop/temp_* research_loop/poc_alias/build_* build configure
