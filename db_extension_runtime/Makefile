# Verus DuckDB extension — path lemma_runtime (stub + shared stream compile)

ROOT := $(abspath ../..)
EXT_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
SHARED_SRC := $(EXT_DIR)/../db_extension/src
DUCKDB_CAPI := $(ROOT)/db_extension/extension-template-c/duckdb_capi
BUILD_DIR := $(ROOT)/build
EXT_SO := $(BUILD_DIR)/lemma_runtime_verus.duckdb_extension
META_SCRIPT := $(ROOT)/db_extension/extension-template-c/extension-ci-tools/scripts/append_extension_metadata.py
DUCKDB_INC := $(or $(LEMMA_DUCKDB_LIB_DIR),$(BUILD_DIR)/libduckdb)

.PHONY: all extension clean

all: extension

extension: $(EXT_SO)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

RUNTIME_SRCS := $(EXT_DIR)/src/lemma_runtime.cpp $(SHARED_SRC)/lemma_stream.cpp

$(EXT_SO): $(RUNTIME_SRCS) | $(BUILD_DIR)
	g++ -shared -o $@ -fPIC \
		$(RUNTIME_SRCS) \
		-I$(DUCKDB_CAPI) \
		-I$(DUCKDB_INC) \
		-I$(EXT_DIR)/src \
		-I$(SHARED_SRC) \
		-DDUCKDB_EXTENSION_NAME=lemma_runtime_verus
	python3 $(META_SCRIPT) \
		-l $@ \
		-n lemma_runtime_verus \
		-dv v1.2.0 \
		-p linux_amd64_gcc4 \
		-ev 0.0.1 \
		-o $@

clean:
	rm -f $(EXT_SO)
