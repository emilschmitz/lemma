# Verus DuckDB extension — path lemma_ops (stub)

ROOT := $(abspath ../..)
EXT_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
DUCKDB_CAPI := $(ROOT)/db_extension/extension-template-c/duckdb_capi
BUILD_DIR := $(ROOT)/build
EXT_SO := $(BUILD_DIR)/lemma_ops_verus.duckdb_extension
META_SCRIPT := $(ROOT)/db_extension/extension-template-c/extension-ci-tools/scripts/append_extension_metadata.py
DUCKDB_INC := $(or $(LEMMA_DUCKDB_LIB_DIR),$(BUILD_DIR)/libduckdb)

.PHONY: all extension clean

all: extension

extension: $(EXT_SO)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(EXT_SO): $(EXT_DIR)/src/lemma_ops.cpp | $(BUILD_DIR)
	g++ -shared -o $@ -fPIC \
		$< \
		-I$(DUCKDB_CAPI) \
		-I$(DUCKDB_INC) \
		-I$(EXT_DIR)/src \
		-DDUCKDB_EXTENSION_NAME=lemma_ops_verus
	python3 $(META_SCRIPT) \
		-l $@ \
		-n lemma_ops_verus \
		-dv v1.2.0 \
		-p linux_amd64_gcc4 \
		-ev 0.0.1 \
		-o $@

clean:
	rm -f $(EXT_SO)
