.PHONY: install test test-unit test-slow loop clean extension

install:
	uv sync

test: test-unit

test-unit:
	uv run pytest transpiler/tests/test_unit.py -v
	uv run pytest db_extension/test_extension.py -v

test-slow:
	RUN_SLOW=1 uv run pytest transpiler/tests/test_functional.py -v

loop:
	uv run python research_loop/harness.py -q 1 --dataset-size 50000

extension:
	g++ -shared -o db_extension/hillclimbing.duckdb_extension -fPIC \
		db_extension/src/hillclimbing.cpp \
		-Idb_extension/extension-template-c/duckdb_capi \
		-DDUCKDB_EXTENSION_NAME=hillclimbing
	python3 db_extension/extension-template-c/extension-ci-tools/scripts/append_extension_metadata.py \
		-l db_extension/hillclimbing.duckdb_extension \
		-n hillclimbing \
		-dv v1.2.0 \
		-p linux_amd64_gcc4 \
		-ev 0.0.1 \
		-o db_extension/hillclimbing.duckdb_extension
	g++ -shared -o db_extension/hillclimbing_python.duckdb_extension -fPIC \
		db_extension/src/hillclimbing.cpp \
		-Idb_extension/extension-template-c/duckdb_capi \
		-DDUCKDB_EXTENSION_NAME=hillclimbing_python
	python3 db_extension/extension-template-c/extension-ci-tools/scripts/append_extension_metadata.py \
		-l db_extension/hillclimbing_python.duckdb_extension \
		-n hillclimbing_python \
		-dv v1.2.0 \
		-p linux_amd64 \
		-ev 0.0.1 \
		-o db_extension/hillclimbing_python.duckdb_extension

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf research_loop/temp_build db_extension/hillclimbing.duckdb_extension db_extension/hillclimbing_python.duckdb_extension db_extension/bin db_extension/cache.json


