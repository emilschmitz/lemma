# Verus DuckDB extension build

ROOT := $(abspath ../..)
EXT_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
DUCKDB_CAPI := $(ROOT)/db_extension/extension-template-c/duckdb_capi
BUILD_DIR := $(ROOT)/build
EXT_SO := $(BUILD_DIR)/lemma_verus.duckdb_extension
META_SCRIPT := $(ROOT)/db_extension/extension-template-c/extension-ci-tools/scripts/append_extension_metadata.py

.PHONY: all extension pin_ffi clean

all: extension

extension: $(EXT_SO)

pin_ffi: $(PIN_LIB)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

PIN_SRCS := $(EXT_DIR)/src/lemma.cpp $(EXT_DIR)/src/lemma_pin.cpp
PIN_LIB := $(BUILD_DIR)/liblemma_pin_ffi.so

$(EXT_SO): $(PIN_SRCS) | $(BUILD_DIR)
	g++ -shared -o $@ -fPIC \
		$(PIN_SRCS) \
		-I$(DUCKDB_CAPI) \
		-I$(EXT_DIR)/src \
		-DDUCKDB_EXTENSION_NAME=lemma_verus
	python3 $(META_SCRIPT) \
		-l $@ \
		-n lemma_verus \
		-dv v1.2.0 \
		-p linux_amd64_gcc4 \
		-ev 0.0.1 \
		-o $@

$(PIN_LIB): $(EXT_DIR)/src/lemma_pin.cpp | $(BUILD_DIR)
	g++ -shared -o $@ -fPIC \
		$< \
		-I$(DUCKDB_CAPI) \
		-I$(EXT_DIR)/src \
		-DLEMMA_PIN_FFI_BUILD

clean:
	rm -f $(EXT_SO) $(PIN_LIB)
