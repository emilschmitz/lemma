# Lemma as a DuckDB community extension (prepared, not submitted)

Goal: `INSTALL lemma FROM community; LOAD lemma;`. `description.yml` here is the draft descriptor; it goes to
`extensions/lemma/description.yml` in a fork of [duckdb/community-extensions](https://github.com/duckdb/community-extensions).

## Requirements found (2026-11-08)

| Requirement | Source | Lemma |
| --- | --- | --- |
| A PR to duckdb/community-extensions that changes exactly one `extensions/<name>/description.yml`; the directory name equals `extension.name` | [scripts/build.py](https://github.com/duckdb/community-extensions/blob/main/scripts/build.py), [development](https://duckdb.org/community_extensions/development) | draft here |
| Unique name; clashes are renamed; the DuckDB Foundation decides case by case | [FAQ](https://duckdb.org/community_extensions/faq) | `lemma` is free: no `extensions/lemma`, no issue or PR mentions it |
| Built with DuckDB's extension template toolchain (`make release`, `make test`, vcpkg for dependencies, CI tools `v2.0-cyanoptera`) | [development](https://duckdb.org/community_extensions/development), [build.yml](https://github.com/duckdb/community-extensions/blob/main/.github/workflows/build.yml), [extension-ci-tools](https://github.com/duckdb/extension-ci-tools) | template-based (`Makefile`, `extension_config.cmake`); no vcpkg, links only libdl |
| Built for the latest stable DuckDB only: `repo.ref` builds against v2.0.0 (CI default); `variegata` = v1.5.6, `andium` = v1.4.5, `ref_next` = next main | [development](https://duckdb.org/community_extensions/development), build.py | **gap**: written against v1.5.6 internals, not built against v2.0.0 |
| An extension in a subdirectory: `repo.build_directory` | build.py, build.yml | `db_extension/duckdb_ext` |
| CI checks out the repo with `submodules: recursive`, `fetch-depth: 0`, and sets the DuckDB version itself | [_extension_distribution.yml](https://github.com/duckdb/extension-ci-tools/blob/main/.github/workflows/_extension_distribution.yml) | our `duckdb` / `extension-ci-tools` submodules are overridden; whole repo (about 55 MB of packs) cloned |
| Tests: the test phase runs `build/release/test/unittest "test/*"` (SQLLogicTest) unless `skip_tests` | extension-ci-tools `makefiles/duckdb_extension.Makefile` | `test/sql/lemma.test` added; the Makefile no longer disables the unittest binary (build.sh still does) |
| Platforms: defaults linux_amd64, linux_arm64, osx_arm64, windows_amd64, windows_amd64_mingw, wasm_mvp/eh/threads; opt-in linux_*_musl, osx_amd64, windows_arm64; `excluded_platforms` / `opt_in_platforms` as `a;b;` | [distribution_matrix.json](https://github.com/duckdb/extension-ci-tools/blob/main/config/distribution_matrix.json) | linux_amd64 only (below) |
| Extra toolchains via `requires_toolchains` (parser_tools, rust, fortran, omp, python3) | _extension_distribution.yml | none needed |
| License: no stated policy or accepted list; examples are MIT / Apache-2.0; pages call community extensions open source | FAQ, examples ([h3](https://github.com/duckdb/community-extensions/blob/main/extensions/h3/description.yml), [crypto](https://github.com/duckdb/community-extensions/blob/main/extensions/crypto/description.yml)) | **gap**: no LICENSE file in the repo |
| No policy on spawning processes or file/network access; signed = built by their CI from the published source, not vetted; `SET allow_community_extensions = false` disables them | [community_extensions](https://duckdb.org/community_extensions/), FAQ | generation starts a shell command (below) |

## How the extension behaves without the `lemma` CLI (checked 2026-11-08 with the 1.5.6 build, `lemma` not on PATH)

* `lemma_query('<sql>')`, `lemma('<sql>')` under `SET lemma_generate = 'off'`, Lemma mode: `no proved executor for this query; run
  \`lemma optimize\` (key ...)`. Never DuckDB's rows (unless `lemma_route_unproved = true`, labelled).
* `lemma('<sql>')` (default `block`): the table snapshot is written, `/bin/sh -c 'lemma generate ...'` starts, and the call fails
  with `Lemma: generating an executor failed (job ..., failed, exit 127): lemma-generate: line 1: lemma: command not found; log: ...`.
* `SET enable_external_access = false`: generation is refused before anything is written: `Permission Error: Lemma: generating an
  executor runs the generator command and writes a snapshot file, and enable_external_access is false`. Loading executor
  libraries (`dlopen` from `lemma_home`) is not gated by that setting today.
* The generator command comes only from `$LEMMA_GENERATOR` at LOAD (else `lemma generate`), never from a SQL setting.

## What blocks other platforms (from `db_extension/duckdb_ext/src`)

* **windows_amd64, windows_amd64_mingw, windows_arm64**: `<spawn.h>` `posix_spawn` with `POSIX_SPAWN_SETSID`, `/bin/sh`,
  `<sys/wait.h>` `waitpid`, `kill` of process groups, `<dlfcn.h>` `dlopen`, `extern char **environ`, `<unistd.h>`; plus `__int128`
  and `__builtin_mul_overflow` (not MSVC). A port needs `CreateProcess` / job objects / `LoadLibrary` and a 128-bit integer type.
* **wasm_mvp, wasm_eh, wasm_threads**: no processes and no `dlopen` of native executors; the design (native Rust executor libraries)
  does not apply in the browser.
* **osx_arm64, osx_amd64**: the C++ is POSIX and might compile, but the executors are Linux `lib.so` files built by the pipeline
  (Verus `--crate-type=cdylib`, `target_cpu`), and the pipeline (Docker agent sandbox, Verus) is only run on Linux x86_64. Untested.
* **linux_arm64, linux_*_musl**: the extension code has no x86 intrinsics and likely compiles; the generation pipeline (agent image
  `lemma-agent:cli`, Verus, `target_cpu`) is untested on arm64 / musl. Excluded until someone runs it there.

## Checklist for Emil

1. **License.** Choose one (MIT or Apache-2.0 match the examples), add `LICENSE` at the repo root, set `extension.license`.
2. **Repository.** `github.com/emilschmitz/lemma` is public, but its page shows no LICENSE and may be behind `main` here: push the
   commit you intend to submit, and check nothing in it must stay private (the CI clones the whole history, recursively).
   The root `.gitmodules` also lists `db_extension/extension-template-c`; it is cloned too.
3. **DuckDB v2.0.0 port (blocking for `INSTALL lemma FROM community` on current DuckDB).** The CI default is v2.0.0 and only that
   build is deployed by default. The extension uses DuckDB v1.5.6 C++ internals (`DataTable` / `RowGroupCollection` parallel scan,
   `DuckTransaction`, `OptimizerExtension`, `ExtensionLoader`, `Appender`, `MetaTransaction::ModifiedDatabase`, transaction
   callbacks). Port and build against v2.0.0 on a branch, and the manifests' `duckdb_version` check then refuses v1.5.6 executors
   (they must be reinstalled). Then set `repo.ref` to that commit (full 40-hex SHA).
4. **v1.5.6 (optional).** Set `repo.variegata` to a `main` commit containing `test/sql/lemma.test` and ask in the PR for a v1.5.6
   build (build.py selects `variegata` only when the CI runs with `DUCKDB_VERSION=v1.5.6`).
5. **Test locally first.** Build with the unittest binary and run the SQL test (needs the RAM guard):
   `scripts/ram/heavy.sh env GEN=ninja CMAKE_BUILD_PARALLEL_LEVEL=2 OVERRIDE_GIT_DESCRIBE=v1.5.6 make -C db_extension/duckdb_ext release` then
   `make -C db_extension/duckdb_ext test`. `build.sh` passes `EXT_FLAGS=-DBUILD_UNITTESTS=0` and does not build it.
6. **Submit.** Fork duckdb/community-extensions, copy `description.yml` to `extensions/lemma/description.yml` with the `<...>`
   fields filled, open the PR (one descriptor per PR). Watch its build: the platforms not excluded must pass `make release` and
   `make test`.
7. **Updates.** Each release: a new full SHA in `repo.ref` (and `version`) in a new PR.
