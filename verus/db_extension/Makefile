# Verus DuckDB extension build

ROOT := $(abspath ../..)
EXT_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
DUCKDB_CAPI := $(ROOT)/db_extension/extension-template-c/duckdb_capi
BUILD_DIR := $(ROOT)/build
EXT_SO := $(BUILD_DIR)/lemma_verus.duckdb_extension
META_SCRIPT := $(ROOT)/db_extension/extension-template-c/extension-ci-tools/scripts/append_extension_metadata.py

.PHONY: all extension clean

all: extension

extension: $(EXT_SO)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(EXT_SO): $(EXT_DIR)/src/lemma.cpp | $(BUILD_DIR)
	g++ -shared -o $@ -fPIC \
		$< \
		-I$(DUCKDB_CAPI) \
		-DDUCKDB_EXTENSION_NAME=lemma_verus
	python3 $(META_SCRIPT) \
		-l $@ \
		-n lemma_verus \
		-dv v1.2.0 \
		-p linux_amd64_gcc4 \
		-ev 0.0.1 \
		-o $@

clean:
	rm -f $(EXT_SO)
