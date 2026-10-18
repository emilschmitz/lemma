PROJ_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

# DuckDB's official extension template (github.com/duckdb/extension-template @ a733bb1), DuckDB v1.5.6 as a submodule.
EXT_NAME=lemma
EXT_CONFIG=${PROJ_DIR}extension_config.cmake
# No C++ unittest binary: the tests are pytest (tests/test_in_duckdb.py) against the Python 1.5.6 wheel and the built CLI.
EXT_FLAGS=-DBUILD_UNITTESTS=0

include extension-ci-tools/makefiles/duckdb_extension.Makefile
