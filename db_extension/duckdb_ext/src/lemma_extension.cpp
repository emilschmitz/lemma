// Lemma inside DuckDB 1.5.6: run a PROVED query executor (a Verus-verified run_query compiled as a shared library with the fixed
// C entry point lemma_run, see lemma_abi.h) on the caller's data, in the caller's transaction.
//
//   lemma_query(sql)        table function: the proved executor's rows for `sql`, or an error when there is none
//   lemma_query(sql, v...)  the same for a query template (`-- params:` header): one value per parameter, in declaration order
//   lemma_last_query()      which engine answered the last table-reading query of this connection, and why
//   lemma_normalize_sql(s)  the cache-key form of a SQL text; lemma_sql_key(s) its sha256 (the executor directory name)
//   SET lemma_mode = true   every table-reading SELECT is answered by its proved executor; with no executor it is an error,
//                           or (SET lemma_route_unproved = true) it runs on DuckDB unchanged and is labelled engine=duckdb
//
// A proved run_query may DECLINE (lemma.toml assumptions = false: the spec states no data assumptions and the body returns None,
// e.g. on a checked overflow; ABI status LEMMA_STATUS_DECLINED). Then lemma_query and lemma_mode raise "Lemma: declined: <reason>"
// and return no rows, unless SET lemma_route_unproved = true: then DuckDB answers the same SQL in the caller's transaction and
// lemma_last_query() says engine=duckdb, reason "declined: ...". With the route on, the executor runs while the statement is
// bound (lemma_query) or planned (lemma_mode), so a decline can still hand the statement to DuckDB's own plan.
//
// No LLM and no network inside DuckDB: a miss is an error (and, with lemma_enqueue_misses, a file in ${lemma_home}/queue for the
// offline `lemma optimize`). Nothing here computes a query result itself; the rows come from the verified library.
#define DUCKDB_EXTENSION_MAIN

#include "lemma_extension.hpp"
#include "lemma_abi.h"
#include "lemma_util.hpp"

#include "duckdb.hpp"
#include "duckdb/catalog/catalog.hpp"
#include "duckdb/catalog/catalog_entry/duck_table_entry.hpp"
#include "duckdb/catalog/catalog_entry/table_catalog_entry.hpp"
#include "duckdb/common/exception.hpp"
#include "duckdb/common/string_map_set.hpp"
#include "duckdb/common/types/decimal.hpp"
#include "duckdb/function/scalar_function.hpp"
#include "duckdb/function/table_function.hpp"
#include "duckdb/main/client_context.hpp"
#include "duckdb/main/client_context_state.hpp"
#include "duckdb/main/config.hpp"
#include "duckdb/main/connection_manager.hpp"
#include "duckdb/main/database.hpp"
#include "duckdb/main/extension/extension_loader.hpp"
#include "duckdb/execution/expression_executor.hpp"
#include "duckdb/optimizer/filter_pushdown.hpp"
#include "duckdb/optimizer/optimizer.hpp"
#include "duckdb/parser/keyword_helper.hpp"
#include "duckdb/planner/expression/bound_columnref_expression.hpp"
#include "duckdb/planner/expression/bound_conjunction_expression.hpp"
#include "duckdb/planner/expression/bound_constant_expression.hpp"
#include "duckdb/planner/expression/bound_reference_expression.hpp"
#include "duckdb/planner/expression_iterator.hpp"
#include "duckdb/planner/table_filter.hpp"
#include "duckdb/optimizer/optimizer_extension.hpp"
#include "duckdb/parallel/task_scheduler.hpp"
#include "duckdb/parser/parser.hpp"
#include "duckdb/parser/statement/select_statement.hpp"
#include "duckdb/parser/tableref/subqueryref.hpp"
#include "duckdb/planner/binder.hpp"
#include "duckdb/planner/extension_callback.hpp"
#include "duckdb/planner/operator/logical_filter.hpp"
#include "duckdb/planner/operator/logical_get.hpp"
#include "duckdb/storage/data_table.hpp"
#include "duckdb/storage/table/row_group.hpp"
#include "duckdb/storage/table/row_group_collection.hpp"
#include "duckdb/storage/table/scan_state.hpp"
#include "duckdb/transaction/duck_transaction.hpp"
#include "duckdb/transaction/local_storage.hpp"
#include "duckdb/transaction/meta_transaction.hpp"
#include "duckdb/storage/buffer_manager.hpp"
#include "duckdb/main/attached_database.hpp"
#include "duckdb/storage/storage_manager.hpp"
#include "duckdb/parser/parsed_data/create_table_info.hpp"

#include <algorithm>
#include <atomic>
#include <cerrno>
#include <climits>
#include <limits>
#include <thread>
#include <chrono>
#include <cstdlib>
#include <deque>
#include <cctype>
#include <cstring>
#include <dlfcn.h>
#include <fstream>
#include <condition_variable>
#include <list>
#include <map>
#include <mutex>
#include <regex>
#include <sstream>
#include <dirent.h>
#include <functional>
#include <ftw.h>
#include <signal.h>
#include <spawn.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;
#include <unordered_map>

static_assert(__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__, "the executor ABI is little-endian");

namespace duckdb {

namespace {

using i128 = __int128;

// Executor ABI versions this extension runs: 4 (lemma_run takes the owned input buffers), 5 (lemma_run_borrowed reads them in
// place: the input cache lends its buffers, no copy) and 6 (a streaming executor, manifest mode "stream": StreamTable hands it
// DuckDB's scan chunks in place, docs/STREAM.md). The manifest's abi_version must equal the library's.
constexpr uint32_t ABI_MIN = 4, ABI_VERSION = 6, ABI_STREAM = 6;
constexpr uint32_t PARAM_INT = 1, PARAM_STR = 4;
constexpr int KIND_INT = 1, KIND_F64 = 2, KIND_BOOL = 3, KIND_STR = 4;
const char *MISS_MESSAGE = "no proved executor for this query; run `lemma optimize`";

int64_t MicrosSince(std::chrono::steady_clock::time_point start) {
	return std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - start).count();
}

std::string ReadFile(const std::string &path) {
	std::ifstream in(path, std::ios::binary);
	if (!in) {
		throw IOException("Lemma: cannot read %s", path);
	}
	std::ostringstream ss;
	ss << in.rdbuf();
	return ss.str();
}

void MakeDirs(const std::string &path) {
	for (size_t i = 1; i <= path.size(); i++) {
		if (i == path.size() || path[i] == '/') {
			std::string prefix = path.substr(0, i);
			if (mkdir(prefix.c_str(), 0755) != 0 && errno != EEXIST) {
				throw IOException("Lemma: cannot create %s", prefix);
			}
		}
	}
}

// ---------------------------------------------------------------- settings

std::string DefaultHome() {
	const char *env = std::getenv("LEMMA_HOME");
	if (env && *env) {
		return env;
	}
	const char *home = std::getenv("HOME");
	return std::string(home ? home : "") + "/.local/share/lemma";
}

bool BoolSetting(ClientContext &context, const char *name) {
	Value v;
	if (!context.TryGetCurrentSetting(name, v) || v.IsNull()) {
		return false;
	}
	return BooleanValue::Get(v);
}

std::string HomeSetting(ClientContext &context) {
	Value v;
	if (!context.TryGetCurrentSetting("lemma_home", v) || v.IsNull()) {
		throw InvalidInputException("Lemma: lemma_home is not set");
	}
	return StringValue::Get(v);
}

// ---------------------------------------------------------------- per-connection record: which engine answered

struct LastQuery {
	bool set = false;
	std::string engine, reason, key, sql;
	int64_t scan_us = -1, load_us = -1, run_us = -1, total_us = -1, rows = -1;
	// The input cache (lemma_cache): "hit", "miss: stored", "miss: not stored (<why>)", "skip: <why>" or "off"; and the bytes of
	// the cached inputs used or stored (-1: none).
	std::string cache;
	int64_t cache_bytes = -1;
	// How the executor ran: "batch" (ABI 4/5: columns converted, then lemma_run) or "stream" (ABI 6: chunks handed in place), the
	// chunks it stepped and the scan threads (-1: none / not a stream).
	std::string mode;
	int64_t chunks = -1, threads = -1;
};

// ---------------------------------------------------------------- the data version (the ONE trusted item of the input cache)
//
// DuckDB's own counter (DuckTransactionManager::last_commit) moves on EVERY commit, read-only ones included (every autocommit
// SELECT commits and takes a commit id), so it cannot tell a repeated query that nothing changed. The version used here is built
// from DuckDB's transaction notifications instead, which every connection's LemmaState receives (README "Input cache"):
//   * TransactionBegin runs before the transaction can read or write anything (its snapshot is taken later, on first access);
//   * TransactionCommit / TransactionRollback run after DuckDB committed (or rolled back) it;
//   * a transaction that changed a non-temporary database has MetaTransaction::ModifiedDatabase() set (DuckDB refuses to commit
//     changes of a transaction that never went through ModifyDatabase: the InternalException in CommitTransaction).
// `epoch` counts ended transactions that modified a database (rollbacks too, conservatively); `open` counts connections inside a
// transaction or a query. A transaction X whose snapshot is CURRENT AT EPOCH E (X's begin saw epoch E, the epoch is still E, and no
// other connection is open) sees exactly the commits of the writers counted in E: every writer that ended before X began committed
// before X's snapshot; a writer that ended after X began moved the epoch; a writer still running is open. So two transactions
// current at the same epoch, without changes of their own, read the same committed data.
struct DataVersion {
	std::mutex lock;
	uint64_t epoch = 0;
	uint64_t open = 0;
};

DataVersion &Version() {
	static auto *v = new DataVersion(); // never destroyed: connection states may outlive static destruction order
	return *v;
}

constexpr uint64_t NO_EPOCH = UINT64_MAX; // a transaction that began before LOAD: its begin was not seen

struct RunResult;

// What the route-on bind of lemma_query computed for the bind that follows it (lemma_route_unproved, see LemmaQueryBindReplace).
struct PendingRun {
	std::string signature; // executor key + encoded parameters
	std::shared_ptr<RunResult> result;
	int64_t scan_us = 0;
	std::string cache;
	int64_t cache_bytes = -1;
};

class LemmaState : public ClientContextState {
public:
	std::mutex lock;
	LastQuery last;
	bool in_query = false;
	std::string query; // the statement text of the running query (set in QueryBegin)
	// lemma_query declined and lemma_route_unproved handed its SQL to DuckDB: the optimizer hook leaves that plan and its label alone.
	bool routed_decline = false;
	PendingRun pending;
	std::string gen_note; // lemma(...) generated (or is regenerating) an executor in this query: said in lemma_last_query()
	// The data version (DataVersion), guarded by Version().lock: inside a transaction / a query, counted in `open`, and the epoch
	// the current transaction began at (NO_EPOCH: unknown).
	bool tx_open = false, query_open = false, counted = false;
	uint64_t begin_epoch = NO_EPOCH;

	~LemmaState() override {
		auto &v = Version();
		std::lock_guard<std::mutex> guard(v.lock);
		if (counted) {
			v.open--;
			v.epoch++; // a connection destroyed inside a transaction: whatever it did, no cache entry outlives it
		}
	}
	// Under Version().lock.
	void Recount(DataVersion &v) {
		bool now = tx_open || query_open;
		if (now != counted) {
			if (now) {
				v.open++;
			} else {
				v.open--;
			}
			counted = now;
		}
	}
	void MarkOpenUnknown() {
		auto &v = Version();
		std::lock_guard<std::mutex> guard(v.lock);
		tx_open = true;
		begin_epoch = NO_EPOCH;
		Recount(v);
	}
	void TransactionBegin(MetaTransaction &, ClientContext &) override {
		auto &v = Version();
		std::lock_guard<std::mutex> guard(v.lock);
		tx_open = true;
		begin_epoch = v.epoch;
		Recount(v);
	}
	void TransactionEnd(MetaTransaction &transaction) {
		auto &v = Version();
		std::lock_guard<std::mutex> guard(v.lock);
		if (transaction.ModifiedDatabase()) {
			v.epoch++;
		}
		tx_open = false;
		begin_epoch = NO_EPOCH;
		Recount(v);
	}
	void TransactionCommit(MetaTransaction &transaction, ClientContext &) override {
		TransactionEnd(transaction);
	}
	void TransactionRollback(MetaTransaction &transaction, ClientContext &) override {
		TransactionEnd(transaction); // a failed commit is reported here too: count it as a write
	}

	void QueryBegin(ClientContext &context) override {
		{
			auto &v = Version();
			std::lock_guard<std::mutex> guard(v.lock);
			query_open = true;
			Recount(v);
		}
		std::lock_guard<std::mutex> guard(lock);
		in_query = true;
		query = context.GetCurrentQuery();
		routed_decline = false;
		pending = PendingRun();
		gen_note.clear();
	}
	void QueryEnd(ClientContext &context) override {
		{
			auto &v = Version();
			std::lock_guard<std::mutex> guard(v.lock);
			query_open = false;
			Recount(v);
		}
		std::lock_guard<std::mutex> guard(lock);
		in_query = false;
		query.clear();
		routed_decline = false;
		pending = PendingRun();
	}
	void Record(LastQuery entry) {
		std::lock_guard<std::mutex> guard(lock);
		entry.set = true;
		last = std::move(entry);
	}
};

LemmaState &GetState(ClientContext &context) {
	return *context.registered_state->GetOrCreate<LemmaState>("lemma");
}

// The state must exist BEFORE a query begins (its QueryBegin captures the statement text): create it on every connection.
class LemmaConnectionCallback : public ExtensionCallback {
public:
	void OnConnectionOpened(ClientContext &context) override {
		GetState(context);
	}
};

// ---------------------------------------------------------------- manifest + library

struct InEntry {
	bool rows = false;
	std::string table, column, field, rust_type, role, duck_type;
	bool nullable = false;
	int scale = 0, source_scale = 0;
	int64_t codes_of = -1;
	// rows entries: the transpiler's pushed-down predicate of this table (manifest "where", declarative_spec/pushdown.py), DuckDB
	// SQL over the table's columns with a query template's `$name` placeholders; empty = the whole table. Applied in the scan.
	std::string where;
};

// One query-template parameter (manifest "params"): its SQL type decides how a lemma_query argument is encoded.
struct ParamSpec {
	std::string name, sql_type, rust_type;
	int scale = 0;
	// The range run_query requires (manifest lo / hi, in run_query's units: DATE a day number, DECIMAL scaled by 10^scale); a
	// VARCHAR parameter has none. Template matching uses it (a literal outside it is no match); the library checks it on every call.
	bool has_range = false;
	int64_t lo = 0, hi = 0;
};

struct OutCol {
	std::string name, field, rust_type, duck_type;
	LogicalType type;
	int kind = 0;
	bool option = false;
};

struct Executor {
	void *handle = nullptr;
	lemma_run_fn run = nullptr;
	lemma_free_out_fn free_out = nullptr;
	lemma_alloc_input_fn alloc_input = nullptr; // ABI 3: owned input buffers
	lemma_free_input_fn free_input = nullptr;
	uint32_t abi = 0;
	lemma_run_fn run_borrowed = nullptr; // ABI 5: the owned-type inputs are lent (read in place), not taken
	// ABI 6 (a streaming executor): no lemma_run / lemma_alloc_input; the stream entry points (lemma_abi.h "ABI 6").
	lemma_stream_open_fn stream_open = nullptr;
	lemma_stream_worker_fn stream_worker = nullptr;
	lemma_stream_step_fn stream_step = nullptr;
	lemma_stream_merge_fn stream_merge = nullptr;
	lemma_stream_finish_fn stream_finish = nullptr;
	lemma_stream_drop_fn stream_drop = nullptr;
	lemma_stream_close_fn stream_close = nullptr;
};

struct Manifest {
	std::string dir, key, sql, normalized_sql, proof, lib_sha256, git_sha;
	std::string manifest_sha256; // of manifest.json: part of the input cache key
	uint32_t abi = 0;            // the executor ABI version (manifest abi_version, equal to the library's)
	bool stream = false;         // manifest mode "stream" (ABI 6): StreamTable, no input buffers, no input cache
	std::vector<InEntry> inputs;
	std::vector<OutCol> outputs;
	std::vector<ParamSpec> params;
	std::shared_ptr<Executor> exec;
};

LogicalType ParseDuckType(const std::string &t) {
	static const std::unordered_map<std::string, LogicalType> simple = {
	    {"TINYINT", LogicalType::TINYINT},     {"SMALLINT", LogicalType::SMALLINT}, {"INTEGER", LogicalType::INTEGER},
	    {"BIGINT", LogicalType::BIGINT},       {"HUGEINT", LogicalType::HUGEINT},   {"UTINYINT", LogicalType::UTINYINT},
	    {"USMALLINT", LogicalType::USMALLINT}, {"UINTEGER", LogicalType::UINTEGER}, {"UBIGINT", LogicalType::UBIGINT},
	    {"UHUGEINT", LogicalType::UHUGEINT},   {"DOUBLE", LogicalType::DOUBLE},     {"FLOAT", LogicalType::FLOAT},
	    {"VARCHAR", LogicalType::VARCHAR},     {"BOOLEAN", LogicalType::BOOLEAN},   {"DATE", LogicalType::DATE}};
	auto it = simple.find(t);
	if (it != simple.end()) {
		return it->second;
	}
	std::smatch m;
	static const std::regex dec("^DECIMAL\\((\\d+),(\\d+)\\)$");
	if (std::regex_match(t, m, dec)) {
		return LogicalType::DECIMAL(std::stoi(m[1]), std::stoi(m[2]));
	}
	throw InvalidInputException("Lemma: result type %s is not supported", t);
}

int KindOf(const std::string &rust, bool &option) {
	std::string inner = rust;
	option = false;
	if (inner.rfind("Option<", 0) == 0) {
		option = true;
		inner = inner.substr(7, inner.size() - 8);
	}
	if (inner == "f64" || inner == "Rat") { // Rat: an exact rational, written by the library as the double num / den
		return KIND_F64;
	}
	if (inner == "bool") {
		return KIND_BOOL;
	}
	if (inner == "String") {
		return KIND_STR;
	}
	return KIND_INT;
}

std::mutex executors_lock;
std::unordered_map<std::string, std::shared_ptr<Executor>> executors; // by library sha256; loaded once per process, never unloaded
std::string private_dir;

std::string JoinLines(const std::vector<lemma::Json> &lines) {
	std::string out;
	for (size_t i = 0; i < lines.size(); i++) {
		out += (i ? "\n" : "") + lines[i].Str();
	}
	return out;
}

// Load (once) the library of `m`: the bytes that are dlopen'ed are exactly the bytes whose sha256 the manifest records; a copy
// in a process-private directory, so replacing lib.so on disk never changes an already loaded executor.
std::shared_ptr<Executor> LoadLibrary(const Manifest &m, const std::string &input_layout, const std::string &output_layout,
                                      const std::string &param_layout, const std::string &stream_layout) {
	std::lock_guard<std::mutex> guard(executors_lock);
	auto it = executors.find(m.lib_sha256);
	if (it != executors.end()) {
		return it->second;
	}
	std::string bytes = ReadFile(m.dir + "/lib.so");
	if (lemma::Sha256Hex(bytes) != m.lib_sha256) {
		throw InvalidInputException("Lemma: %s/lib.so does not match the sha256 in its manifest", m.dir);
	}
	if (private_dir.empty()) {
		char tmpl[] = "/tmp/lemma-executors-XXXXXX";
		if (!mkdtemp(tmpl)) {
			throw IOException("Lemma: cannot create a private directory for executor libraries");
		}
		private_dir = tmpl;
	}
	std::string copy = private_dir + "/lemma-" + m.lib_sha256 + ".so";
	{
		std::ofstream out(copy, std::ios::binary);
		out.write(bytes.data(), std::streamsize(bytes.size()));
		if (!out) {
			throw IOException("Lemma: cannot write %s", copy);
		}
	}
	void *handle = dlopen(copy.c_str(), RTLD_NOW | RTLD_LOCAL);
	if (!handle) {
		throw IOException("Lemma: dlopen %s: %s", copy, std::string(dlerror()));
	}
	auto sym = [&](const char *name) {
		void *p = dlsym(handle, name);
		if (!p) {
			throw IOException("Lemma: executor library lacks %s", std::string(name));
		}
		return p;
	};
	auto abi = reinterpret_cast<lemma_abi_version_fn>(sym("lemma_abi_version"));
	auto lib_sql = reinterpret_cast<lemma_text_fn>(sym("lemma_query_sql"));
	auto lib_in = reinterpret_cast<lemma_text_fn>(sym("lemma_input_layout"));
	auto lib_out = reinterpret_cast<lemma_text_fn>(sym("lemma_output_layout"));
	auto lib_params = reinterpret_cast<lemma_text_fn>(sym("lemma_param_layout"));
	auto exec = std::make_shared<Executor>();
	exec->handle = handle;
	exec->abi = abi();
	if (exec->abi < ABI_MIN || exec->abi > ABI_VERSION) {
		throw InvalidInputException("Lemma: executor ABI version %d, this extension speaks %d to %d", int(exec->abi), int(ABI_MIN),
		                            int(ABI_VERSION));
	}
	if (exec->abi != m.abi) {
		throw InvalidInputException("Lemma: the executor library of %s has ABI version %d, its manifest says %d", m.key,
		                            int(exec->abi), int(m.abi));
	}
	exec->free_out = reinterpret_cast<lemma_free_out_fn>(sym("lemma_free_out"));
	if (exec->abi == ABI_STREAM) {
		exec->stream_open = reinterpret_cast<lemma_stream_open_fn>(sym("lemma_stream_open"));
		exec->stream_worker = reinterpret_cast<lemma_stream_worker_fn>(sym("lemma_stream_worker"));
		exec->stream_step = reinterpret_cast<lemma_stream_step_fn>(sym("lemma_stream_step"));
		exec->stream_merge = reinterpret_cast<lemma_stream_merge_fn>(sym("lemma_stream_merge"));
		exec->stream_finish = reinterpret_cast<lemma_stream_finish_fn>(sym("lemma_stream_finish"));
		exec->stream_drop = reinterpret_cast<lemma_stream_drop_fn>(sym("lemma_stream_drop"));
		exec->stream_close = reinterpret_cast<lemma_stream_close_fn>(sym("lemma_stream_close"));
		auto lib_stream = reinterpret_cast<lemma_text_fn>(sym("lemma_stream_layout"));
		if (std::string(lib_stream()) != stream_layout) {
			throw InvalidInputException("Lemma: the stream executor library of %s has another chunk layout than its manifest", m.key);
		}
	} else {
		exec->run = reinterpret_cast<lemma_run_fn>(sym("lemma_run"));
		exec->alloc_input = reinterpret_cast<lemma_alloc_input_fn>(sym("lemma_alloc_input"));
		exec->free_input = reinterpret_cast<lemma_free_input_fn>(sym("lemma_free_input"));
	}
	if (exec->abi == 5) {
		exec->run_borrowed = reinterpret_cast<lemma_run_fn>(sym("lemma_run_borrowed"));
	}
	if (lemma::NormalizeSql(lib_sql()) != m.normalized_sql) {
		throw InvalidInputException("Lemma: the executor library of %s was built for another query", m.key);
	}
	if (std::string(lib_in()) != input_layout || std::string(lib_out()) != output_layout) {
		throw InvalidInputException("Lemma: the executor library of %s has another column layout than its manifest", m.key);
	}
	if (std::string(lib_params()) != param_layout) {
		throw InvalidInputException("Lemma: the executor library of %s has other parameters than its manifest", m.key);
	}
	executors[m.lib_sha256] = exec;
	return exec;
}

bool FileExists(const std::string &path) {
	struct stat st;
	return stat(path.c_str(), &st) == 0;
}

std::unique_ptr<Manifest> LoadExecutor(const std::string &dir, const std::string &key, const std::string *normalized_sql);

// The executor for `sql` (its exact text, normalized), or nullptr on a miss. Every check that fails on a PRESENT executor is an
// error, never a miss.
std::unique_ptr<Manifest> FindExecutor(ClientContext &context, const std::string &sql) {
	std::string normalized = lemma::NormalizeSql(sql);
	std::string key = lemma::Sha256Hex(normalized);
	std::string dir = HomeSetting(context) + "/executors/" + key;
	if (!FileExists(dir + "/manifest.json")) {
		return nullptr;
	}
	return LoadExecutor(dir, key, &normalized);
}

// The executor installed in `dir` under `key` (checked against the manifest, and its normalized SQL against `normalized_sql` when
// given; a template found through the template index is checked against its own key and text).
std::unique_ptr<Manifest> LoadExecutor(const std::string &dir, const std::string &key, const std::string *normalized_sql) {
	lemma::Json j;
	std::string manifest_text_sha;
	try {
		std::string text = ReadFile(dir + "/manifest.json");
		manifest_text_sha = lemma::Sha256Hex(text);
		j = lemma::ParseJson(text);
	} catch (std::runtime_error &e) {
		throw InvalidInputException("Lemma: %s/manifest.json: %s", dir, std::string(e.what()));
	}
	auto m = make_uniq<Manifest>();
	try {
		m->dir = dir;
		m->manifest_sha256 = manifest_text_sha;
		m->key = j.At("key").Str();
		m->sql = j.At("sql").Str();
		m->normalized_sql = j.At("normalized_sql").Str();
		m->proof = j.At("proof").Str();
		m->lib_sha256 = j.At("lib_sha256").Str();
		m->git_sha = j.At("git_sha").Str();
		if (j.At("format").Int() != 1 || j.At("abi_version").Int() < ABI_MIN || j.At("abi_version").Int() > ABI_VERSION) {
			throw InvalidInputException("Lemma: %s: manifest format/ABI not understood by this extension", dir);
		}
		m->abi = uint32_t(j.At("abi_version").Int());
		m->stream = j.Has("mode") && j.At("mode").kind == lemma::Json::Kind::String && j.At("mode").Str() == "stream";
		if (m->stream != (m->abi == ABI_STREAM)) {
			throw InvalidInputException("Lemma: %s: manifest mode %s with ABI version %d (a stream executor is ABI 6, mode \"stream\")",
			                            dir, m->stream ? "stream" : "batch", int(m->abi));
		}
		if (!j.At("in_duckdb").Bool()) {
			throw InvalidInputException("Lemma: %s was not installed for in-DuckDB execution (in_duckdb is false)", dir);
		}
		if (m->key != key || (normalized_sql && m->normalized_sql != *normalized_sql) ||
		    lemma::Sha256Hex(m->normalized_sql) != key) {
			throw InvalidInputException("Lemma: %s holds the executor of another query", dir);
		}
		std::string version = j.At("duckdb_version").Str();
		if (version != DuckDB::LibraryVersion()) {
			throw InvalidInputException("Lemma: executor %s was built for DuckDB %s, this is DuckDB %s", key, version,
			                            std::string(DuckDB::LibraryVersion()));
		}
		static const std::regex proof("^[0-9]+ verified, 0 errors$");
		if (!std::regex_match(m->proof, proof)) {
			throw InvalidInputException("Lemma: executor %s has no complete proof (manifest proof: '%s')", key, m->proof);
		}
		for (auto &e : j.At("params").Arr()) {
			ParamSpec p;
			p.name = e.At("name").Str();
			p.sql_type = e.At("sql_type").Str();
			p.rust_type = e.At("rust_type").Str();
			p.scale = int(e.At("scale").Int());
			if (e.Has("lo") && e.Has("hi") && e.At("lo").kind == lemma::Json::Kind::Number &&
			    e.At("hi").kind == lemma::Json::Kind::Number) {
				p.has_range = true;
				p.lo = e.At("lo").Int();
				p.hi = e.At("hi").Int();
			}
			m->params.push_back(p);
		}
		if (m->params.size() != j.At("param_layout").Arr().size()) {
			throw InvalidInputException("Lemma: %s: params and param_layout differ in length", dir);
		}
		for (auto &e : j.At("inputs").Arr()) {
			InEntry in;
			in.table = e.At("table").Str();
			if (e.At("kind").Str() == "rows") {
				in.rows = true;
				if (e.Has("where") && e.At("where").kind == lemma::Json::Kind::String) {
					in.where = e.At("where").Str();
				}
			} else {
				in.column = e.At("column").Str();
				in.field = e.At("field").Str();
				in.rust_type = e.At("rust_type").Str();
				in.role = e.At("role").Str();
				in.duck_type = e.At("duck_type").Str();
				in.nullable = e.At("nullable").Bool();
				in.scale = int(e.At("scale").Int());
				in.source_scale = int(e.At("source_scale").Int());
				if (e.Has("codes_of")) {
					in.codes_of = e.At("codes_of").Int();
				}
			}
			m->inputs.push_back(in);
		}
		for (auto &e : j.At("outputs").Arr()) {
			OutCol out;
			out.name = e.At("name").Str();
			out.field = e.At("field").Str();
			out.rust_type = e.At("rust_type").Str();
			out.duck_type = e.At("duck_type").Str();
			out.type = ParseDuckType(out.duck_type);
			out.kind = KindOf(out.rust_type, out.option);
			m->outputs.push_back(out);
		}
		if (m->inputs.size() != j.At("input_layout").Arr().size()) {
			throw InvalidInputException("Lemma: %s: inputs and input_layout differ in length", dir);
		}
		std::string stream_layout;
		if (m->stream) {
			stream_layout = JoinLines(j.At("stream").At("layout").Arr());
			if (j.At("stream").At("layout").Arr().size() + 1 != m->inputs.size()) {
				throw InvalidInputException("Lemma: %s: the stream layout and the inputs differ in length", dir);
			}
			for (auto &in : m->inputs) {
				if (in.rows ? !in.where.empty() : (in.role == "code" || in.role == "dict" || in.role == "f64")) {
					throw InvalidInputException("Lemma: %s: a stream executor reads plain columns of one table, without a pushed "
					                            "predicate (input %s.%s)",
					                            dir, in.table, in.rows ? std::string("rows") : in.column);
				}
			}
			if (m->inputs.empty() || !m->inputs[0].rows ||
			    std::count_if(m->inputs.begin(), m->inputs.end(), [](const InEntry &e) { return e.rows; }) != 1) {
				throw InvalidInputException("Lemma: %s: a stream executor reads exactly one table", dir);
			}
		}
		m->exec = LoadLibrary(*m, JoinLines(j.At("input_layout").Arr()), JoinLines(j.At("output_layout").Arr()),
		                      JoinLines(j.At("param_layout").Arr()), stream_layout);
	} catch (std::runtime_error &e) {
		if (dynamic_cast<Exception *>(&e)) {
			throw;
		}
		throw InvalidInputException("Lemma: %s/manifest.json: %s", dir, std::string(e.what()));
	}
	return m;
}

void EnqueueMiss(ClientContext &context, const std::string &sql) {
	if (!BoolSetting(context, "lemma_enqueue_misses")) {
		return;
	}
	std::string normalized = lemma::NormalizeSql(sql);
	std::string queue = HomeSetting(context) + "/queue";
	MakeDirs(queue);
	std::string target = queue + "/" + lemma::Sha256Hex(normalized) + ".sql";
	std::string part = target + ".part" + std::to_string(getpid());
	{
		std::ofstream out(part, std::ios::binary);
		out << sql << "\n";
	}
	if (std::rename(part.c_str(), target.c_str()) != 0) {
		throw IOException("Lemma: cannot write %s", target);
	}
}

[[noreturn]] void ThrowMiss(ClientContext &context, const std::string &sql) {
	EnqueueMiss(context, sql);
	throw InvalidInputException("%s (key %s)", MISS_MESSAGE, lemma::Sha256Hex(lemma::NormalizeSql(sql)));
}

// ---------------------------------------------------------------- input encoding (mirror of decl_query_measure._encode_columns)

struct IntTarget {
	int width = 8;
	i128 lo = 0, hi = 0;
};

IntTarget TargetOf(const std::string &rust) {
	static const std::unordered_map<std::string, std::pair<int, bool>> widths = {
	    {"i8", {1, true}},  {"i16", {2, true}},  {"i32", {4, true}},  {"i64", {8, true}},   {"i128", {16, true}},
	    {"u8", {1, false}}, {"u16", {2, false}}, {"u32", {4, false}}, {"u64", {8, false}}, {"usize", {8, false}}};
	auto it = widths.find(rust);
	if (it == widths.end()) {
		throw InvalidInputException("Lemma: cannot load column type %s", rust);
	}
	IntTarget t;
	t.width = it->second.first;
	const i128 i128_max = ~(i128(1) << 127);
	if (t.width == 16) {
		t.hi = i128_max;
		t.lo = -i128_max - 1;
	} else if (it->second.second) {
		t.hi = (i128(1) << (8 * t.width - 1)) - 1;
		t.lo = -t.hi - 1;
	} else {
		t.hi = (i128(1) << (8 * t.width)) - 1;
		t.lo = 0;
	}
	return t;
}

std::string I128String(i128 v) {
	bool neg = v < 0;
	unsigned __int128 u = neg ? (unsigned __int128)(-(v + 1)) + 1 : (unsigned __int128)v;
	std::string s;
	do {
		s.push_back(char('0' + int(u % 10)));
		u /= 10;
	} while (u);
	if (neg) {
		s.push_back('-');
	}
	return std::string(s.rbegin(), s.rend());
}

i128 Pow10(int e) {
	i128 r = 1;
	for (int i = 0; i < e; i++) {
		r *= 10;
	}
	return r;
}

// DuckDB's hugeint -> DOUBLE cast (upper * 2^64 + lower), which the exporter's CAST(<hugeint> AS DOUBLE) applies.
double HugeToDouble(i128 v) {
	int64_t upper = int64_t(v >> 64);
	uint64_t lower = uint64_t(v);
	return double(upper) * 18446744073709551616.0 + double(lower);
}

i128 HugeOf(hugeint_t h) {
	return (i128(h.upper) << 64) | i128(h.lower);
}

// The value range of a DuckDB source cell type (for the copy fast path: a source that fits the target needs no range check).
template <class SRC>
std::pair<i128, i128> SourceRange() {
	return {i128(std::numeric_limits<SRC>::min()), i128(std::numeric_limits<SRC>::max())};
}
template <>
std::pair<i128, i128> SourceRange<date_t>() {
	return {i128(std::numeric_limits<int32_t>::min()), i128(std::numeric_limits<int32_t>::max())};
}
template <>
std::pair<i128, i128> SourceRange<hugeint_t>() {
	const i128 i128_max = ~(i128(1) << 127);
	return {-i128_max - 1, i128_max};
}

enum class Role { Valid, Int, Date, Decimal, F64, Bool, String, Code, Dict };

Role RoleOf(const std::string &role, const std::string &label) {
	static const std::unordered_map<std::string, Role> roles = {
	    {"valid", Role::Valid}, {"int", Role::Int},       {"date", Role::Date},     {"decimal", Role::Decimal},
	    {"f64", Role::F64},     {"bool", Role::Bool},     {"string", Role::String}, {"code", Role::Code},
	    {"dict", Role::Dict}};
	auto it = roles.find(role);
	if (it == roles.end()) {
		throw InvalidInputException("Lemma: %s: unknown input role %s", label, role);
	}
	return it->second;
}

// An input the library owns (ABI 3): its fixed-width integer or f64 cells go straight into a buffer of the library's allocator,
// which lemma_run takes as the Vec's memory. Mirrors assemble_library.owned.
bool OwnedType(const std::string &rust) {
	static const std::unordered_map<std::string, int> owned = {{"u8", 1},  {"u16", 1}, {"u32", 1}, {"u64", 1},   {"usize", 1},
	                                                            {"i8", 1},  {"i16", 1}, {"i32", 1}, {"i64", 1},   {"i128", 1},
	                                                            {"f64", 1}};
	return owned.count(rust) != 0;
}

// A buffer allocated by the executor library (lemma_alloc_input). Returned to it (lemma_free_input) unless released to lemma_run.
struct OwnedBuffer {
	std::shared_ptr<Executor> exec;
	uint64_t index = 0;
	uint8_t *ptr = nullptr;
	uint64_t len = 0, width = 0;
	OwnedBuffer(std::shared_ptr<Executor> exec_p, uint64_t index_p, uint64_t cap, uint64_t width)
	    : exec(std::move(exec_p)), index(index_p) {
		ptr = exec->alloc_input(index, cap);
		if (!ptr) {
			throw InvalidInputException("Lemma: the executor library allocated no buffer for input %d (%d cells)",
			                            int64_t(index), int64_t(cap));
		}
		len = cap * width;
		this->width = width;
	}
	~OwnedBuffer() {
		if (ptr) {
			exec->free_input(index, ptr, len);
		}
	}
	OwnedBuffer(const OwnedBuffer &) = delete;
	OwnedBuffer &operator=(const OwnedBuffer &) = delete;
};

// How one field input (not a rows entry, not a dictionary) is decoded: immutable while the scan threads run.
struct ColPlan {
	size_t k = 0; // manifest input index
	InEntry e;
	std::string label;
	Role role = Role::Int;
	IntTarget target;
	i128 mul = 1;              // decimal: 10^(scale - source_scale)
	bool decimal_wide = false; // f64 from DECIMAL: the exporter's HUGEINT path (else BIGINT)
	uint64_t code_limit = 0;
	idx_t chunk_col = 0;
	LogicalType type;
	size_t width = 0;      // bytes per cell in `dest`; 0 for strings
	uint8_t *dest = nullptr; // cell i of the table at dest + width * i (owned buffer, or a byte vector for bool / valid)
	size_t slot = 0;         // strings: index into TaskOut::strings; codes: index into TaskOut::dicts
	size_t dict_k = SIZE_MAX; // codes: the manifest input of its dictionary
	size_t idx = 0;           // position in the table's plan list (a task's staging buffer)

	[[noreturn]] void ThrowPack(i128 v) const {
		throw InvalidInputException("Lemma: cannot pack %s as %s (%s)", I128String(v), e.rust_type, label);
	}
	void NullCell() const {
		if (!e.nullable) {
			throw InvalidInputException("Lemma: %s has NULLs; the catalog does not declare the column nullable", label);
		}
	}
	i128 Scaled(i128 v) const {
		i128 out;
		if (__builtin_mul_overflow(v, mul, &out)) {
			throw InvalidInputException("Lemma: %s: value out of range at scale %d", label, e.scale);
		}
		return out;
	}
};

// Dictionary codes seen by ONE scan task: its distinct non-NULL strings in order of first appearance in the task. Merged into the
// table's numbering (first appearance in row order) after the scan. Keys point into `entries` (a deque: elements never move).
struct LocalDict {
	string_map_t<uint32_t> codes;
	std::deque<std::string> entries;
	std::vector<uint64_t> nulls; // rows (relative to the task) holding a NULL: code 0 of the table, whatever the remap
	bool null_seen = false;
	std::vector<int64_t> memo;   // per chunk: dictionary-vector index -> code
};

// What one scan task produced: rows [offset, offset + count) of every fixed-width destination, its strings and dictionaries.
struct TaskOut {
	uint64_t offset = 0, count = 0;
	std::vector<std::string> strings;
	std::vector<LocalDict> dicts;
	// A filtered scan (pushed predicate): the task decodes its fixed-width cells into staging buffers (one per plan, in plan
	// order), copied to their final place once every earlier task's row count is known; no gaps, no packing afterwards.
	std::unique_ptr<std::vector<std::vector<uint8_t>>> stage;
	uint64_t seq = 0;
};

void PutCell(uint8_t *out, size_t width, i128 v) {
	std::memcpy(out, &v, width); // little-endian: the low `width` bytes
}

// Integer cells (INT*, UINT*, HUGEINT, DATE, DECIMAL) of one chunk at `out`: scale, range check, `width` LE bytes each. A flat
// vector without NULLs whose source type is the target's width and fits its range is one memcpy.
template <class SRC, class TO_I128>
void DecodeInts(const ColPlan &p, Vector &vec, idx_t count, uint8_t *out, TO_I128 to_i128) {
	size_t w = p.width;
	bool scale = p.role == Role::Decimal && p.mul != 1;
	auto range = SourceRange<SRC>();
	if (!scale && sizeof(SRC) == w && range.first >= p.target.lo && range.second <= p.target.hi &&
	    vec.GetVectorType() == VectorType::FLAT_VECTOR && FlatVector::Validity(vec).AllValid()) {
		std::memcpy(out, FlatVector::GetData<SRC>(vec), w * count);
		return;
	}
	UnifiedVectorFormat f;
	vec.ToUnifiedFormat(count, f);
	auto data = UnifiedVectorFormat::GetData<SRC>(f);
	bool all_valid = f.validity.AllValid();
	if (!scale && sizeof(SRC) == w && range.first >= p.target.lo && range.second <= p.target.hi && all_valid) {
		// A selected (filtered, dictionary) vector of the target's width and range: a gather, no per-cell check needed.
		auto dst = reinterpret_cast<SRC *>(out);
		for (idx_t r = 0; r < count; r++) {
			std::memcpy(dst + r, data + f.sel->get_index(r), sizeof(SRC));
		}
		return;
	}
	for (idx_t r = 0; r < count; r++) {
		idx_t idx = f.sel->get_index(r);
		i128 v = 0;
		if (all_valid || f.validity.RowIsValid(idx)) {
			v = to_i128(data[idx]);
			if (scale) {
				v = p.Scaled(v);
			}
		} else {
			p.NullCell();
		}
		if (v < p.target.lo || v > p.target.hi) {
			p.ThrowPack(v);
		}
		PutCell(out + w * r, w, v);
	}
}

void DecodeIntegers(const ColPlan &p, Vector &vec, idx_t count, uint8_t *out) {
	auto huge = [](hugeint_t h) { return HugeOf(h); };
	auto same = [](int64_t v) { return i128(v); };
	const LogicalType &t = p.type;
	switch (t.id()) {
	case LogicalTypeId::DATE:
		return DecodeInts<date_t>(p, vec, count, out, [](date_t d) { return i128(d.days); });
	case LogicalTypeId::UBIGINT:
		return DecodeInts<uint64_t>(p, vec, count, out, [](uint64_t v) { return i128(v); });
	case LogicalTypeId::UINTEGER:
		return DecodeInts<uint32_t>(p, vec, count, out, same);
	case LogicalTypeId::USMALLINT:
		return DecodeInts<uint16_t>(p, vec, count, out, same);
	case LogicalTypeId::UTINYINT:
		return DecodeInts<uint8_t>(p, vec, count, out, same);
	case LogicalTypeId::TINYINT:
	case LogicalTypeId::SMALLINT:
	case LogicalTypeId::INTEGER:
	case LogicalTypeId::BIGINT:
	case LogicalTypeId::HUGEINT:
	case LogicalTypeId::DECIMAL:
		switch (t.InternalType()) {
		case PhysicalType::INT8:
			return DecodeInts<int8_t>(p, vec, count, out, same);
		case PhysicalType::INT16:
			return DecodeInts<int16_t>(p, vec, count, out, same);
		case PhysicalType::INT32:
			return DecodeInts<int32_t>(p, vec, count, out, same);
		case PhysicalType::INT64:
			return DecodeInts<int64_t>(p, vec, count, out, same);
		case PhysicalType::INT128:
			return DecodeInts<hugeint_t>(p, vec, count, out, huge);
		default:
			break;
		}
		break;
	default:
		break;
	}
	throw InvalidInputException("Lemma: %s: DuckDB type %s is not loadable as an integer", p.label, t.ToString());
}

// The integer value of a cell of an integer or DECIMAL column (unscaled for DECIMAL), for the f64 role.
i128 IntOf(const ColPlan &p, const UnifiedVectorFormat &f, idx_t idx) {
	const LogicalType &t = p.type;
	switch (t.InternalType()) {
	case PhysicalType::INT8:
		return UnifiedVectorFormat::GetData<int8_t>(f)[idx];
	case PhysicalType::INT16:
		return UnifiedVectorFormat::GetData<int16_t>(f)[idx];
	case PhysicalType::INT32:
		return UnifiedVectorFormat::GetData<int32_t>(f)[idx];
	case PhysicalType::INT64:
		return UnifiedVectorFormat::GetData<int64_t>(f)[idx];
	case PhysicalType::UINT8:
		return UnifiedVectorFormat::GetData<uint8_t>(f)[idx];
	case PhysicalType::UINT16:
		return UnifiedVectorFormat::GetData<uint16_t>(f)[idx];
	case PhysicalType::UINT32:
		return UnifiedVectorFormat::GetData<uint32_t>(f)[idx];
	case PhysicalType::UINT64:
		return UnifiedVectorFormat::GetData<uint64_t>(f)[idx];
	case PhysicalType::INT128:
		return HugeOf(UnifiedVectorFormat::GetData<hugeint_t>(f)[idx]);
	default:
		break;
	}
	throw InvalidInputException("Lemma: %s: DuckDB type %s is not loadable as an integer", p.label, t.ToString());
}

uint32_t CodeOf(const ColPlan &p, LocalDict &d, const string_t &s) {
	auto it = d.codes.find(s);
	if (it != d.codes.end()) {
		return it->second;
	}
	if (std::memchr(s.GetData(), 0, s.GetSize()) != nullptr) {
		throw InvalidInputException("Lemma: %s: a NUL byte in a dictionary string", p.label);
	}
	if (d.entries.size() >= p.code_limit) { // the table has at least as many distinct strings as this task
		throw InvalidInputException("Lemma: cannot pack code %d as %s (%s)", int64_t(d.entries.size()), p.e.rust_type, p.label);
	}
	uint32_t code = uint32_t(d.entries.size());
	d.entries.emplace_back(s.GetData(), s.GetSize());
	const std::string &kept = d.entries.back();
	d.codes.emplace(string_t(kept.data(), uint32_t(kept.size())), code);
	return code;
}

// Task-local dictionary codes of one chunk, rows [pos, pos + count) of the task. A DuckDB dictionary vector: the same index is
// the same string, so each index is looked up once per chunk.
void DecodeCodes(const ColPlan &p, Vector &vec, idx_t count, uint8_t *out, LocalDict &d, uint64_t pos) {
	UnifiedVectorFormat f;
	vec.ToUnifiedFormat(count, f);
	auto data = UnifiedVectorFormat::GetData<string_t>(f);
	bool dict = vec.GetVectorType() == VectorType::DICTIONARY_VECTOR;
	if (dict) {
		idx_t max_idx = 0;
		for (idx_t r = 0; r < count; r++) {
			max_idx = MaxValue<idx_t>(max_idx, f.sel->get_index(r));
		}
		d.memo.assign(max_idx + 1, -1);
	}
	for (idx_t r = 0; r < count; r++) {
		idx_t idx = f.sel->get_index(r);
		uint32_t code = 0;
		if (!f.validity.RowIsValid(idx)) {
			p.NullCell();
			d.nulls.push_back(pos + r);
		} else if (dict && d.memo[idx] >= 0) {
			code = uint32_t(d.memo[idx]);
		} else {
			code = CodeOf(p, d, data[idx]);
			if (dict) {
				d.memo[idx] = code;
			}
		}
		PutCell(out + p.width * r, p.width, code);
	}
}

void PutStr(std::string &out, const char *data, size_t len) {
	if (len > 0xFFFFFFFFull) {
		throw InvalidInputException("Lemma: a string is longer than u32");
	}
	uint32_t l = uint32_t(len);
	out.append(reinterpret_cast<const char *>(&l), 4);
	out.append(data, len);
}

// One chunk of one field into the task's rows [t.count, t.count + count), i.e. table rows t.offset + t.count + r.
void DecodeChunk(const ColPlan &p, Vector &vec, idx_t count, TaskOut &t) {
	uint64_t row = t.offset + t.count;
	uint8_t *out = p.dest ? (t.stage ? (*t.stage)[p.idx].data() + p.width * t.count : p.dest + p.width * row) : nullptr;
	switch (p.role) {
	case Role::Int:
	case Role::Date:
	case Role::Decimal:
		return DecodeIntegers(p, vec, count, out);
	case Role::Code:
		return DecodeCodes(p, vec, count, out, t.dicts[p.slot], t.count);
	default:
		break;
	}
	UnifiedVectorFormat f;
	vec.ToUnifiedFormat(count, f);
	const LogicalType &type = p.type;
	for (idx_t r = 0; r < count; r++) {
		idx_t idx = f.sel->get_index(r);
		bool valid = f.validity.RowIsValid(idx);
		if (p.role == Role::Valid) {
			out[r] = valid ? 1 : 0;
			continue;
		}
		if (!valid) {
			p.NullCell();
		}
		switch (p.role) {
		case Role::F64: {
			double d = 0.0;
			if (valid) {
				if (type.id() == LogicalTypeId::DOUBLE) {
					d = UnifiedVectorFormat::GetData<double>(f)[idx];
				} else if (type.id() == LogicalTypeId::FLOAT) {
					d = UnifiedVectorFormat::GetData<float>(f)[idx];
				} else if (type.id() == LogicalTypeId::DECIMAL) {
					i128 sv = p.Scaled(IntOf(p, f, idx));
					d = p.decimal_wide ? HugeToDouble(sv) : double(int64_t(sv));
				} else if (type.id() == LogicalTypeId::HUGEINT) {
					d = HugeToDouble(IntOf(p, f, idx));
				} else {
					i128 sv = IntOf(p, f, idx);
					d = type.id() == LogicalTypeId::UBIGINT ? double(uint64_t(sv)) : double(int64_t(sv));
				}
			}
			std::memcpy(out + 8 * r, &d, 8);
			break;
		}
		case Role::Bool:
			out[r] = valid && UnifiedVectorFormat::GetData<bool>(f)[idx] ? 1 : 0;
			break;
		case Role::String:
			if (valid) {
				auto sv = UnifiedVectorFormat::GetData<string_t>(f)[idx];
				PutStr(t.strings[p.slot], sv.GetData(), sv.GetSize());
			} else {
				PutStr(t.strings[p.slot], "", 0);
			}
			break;
		default:
			throw InternalException("Lemma: role %s in a scan", p.e.role);
		}
	}
}

// The converted inputs of one executor call, kept by the input cache (lemma_cache). Immutable once in the cache: every call that
// uses it only reads it (shared_ptr), and eviction only drops the cache's reference.
struct CachedInputs {
	enum Kind : uint8_t { ROWS, OWNED, LENT, BYTES, BUFFER };
	std::vector<Kind> kind;
	// LENT (ABI 5): the scan's own library buffer, kept here and lent to every call (lemma_run_borrowed reads it in place); freed
	// with lemma_free_input when the entry and every call holding it are gone.
	std::vector<std::shared_ptr<OwnedBuffer>> lent;
	std::vector<std::string> buffers;                 // BUFFER: strings, dictionaries (borrowed by lemma_run as they are)
	std::vector<std::vector<uint8_t>> bytes;          // BYTES: bool, validity (borrowed as they are)
	std::vector<std::unique_ptr<uint8_t[]>> owned;    // OWNED (ABI 4): a copy of the cells; each call gets its own library buffer
	std::vector<uint64_t> width;                      // OWNED, LENT: bytes per cell
	std::vector<LemmaCol> cols;                       // n of every input; data/len of LENT, BYTES and BUFFER inputs
	uint64_t size = 0;                                // bytes held
	uint64_t epoch = 0;
	std::vector<weak_ptr<AttachedDatabase>> databases; // the databases read, alive: an address in the key is not reused
};

struct ScanResult {
	std::vector<std::string> buffers;                // borrowed byte inputs: strings, dictionaries
	std::vector<std::vector<uint8_t>> bytes;         // borrowed one-byte inputs: bool, validity
	// owned inputs (null where an input is not owned): taken by lemma_run (ABI 4), or lent to lemma_run_borrowed (ABI 5) and freed
	// here afterwards unless the input cache keeps them
	std::vector<std::shared_ptr<OwnedBuffer>> owned;
	std::vector<LemmaCol> cols;
	int64_t scan_us = 0;
	std::shared_ptr<const CachedInputs> hold; // borrowed inputs that live in the input cache
	std::string cache = "off";               // LastQuery::cache
	int64_t cache_bytes = -1;

	// lemma_run (ABI 4) takes the owned buffers whatever it returns: from here on they are the library's.
	void ReleaseOwned() {
		for (auto &o : owned) {
			if (o) {
				o->ptr = nullptr;
			}
		}
	}
};

idx_t ScanThreads(ClientContext &context) {
	Value v;
	if (context.TryGetCurrentSetting("lemma_scan_threads", v) && !v.IsNull() && v.GetValue<int64_t>() > 0) {
		return idx_t(v.GetValue<int64_t>());
	}
	return MaxValue<idx_t>(1, idx_t(TaskScheduler::GetScheduler(context).NumberOfThreads()));
}

// One scan task source: the committed row groups, or the transaction-local ones (this transaction's own uncommitted rows).
// Tasks of the parallel scan are whole row groups (DuckDB's own parallel table scan); a task's rows land at its position in the
// single-threaded row order: (row start - base row id), after all committed rows for the local part.
struct ScanSource {
	RowGroupCollection *collection = nullptr;
	ParallelCollectionScanState state;
	bool local = false;
	uint64_t base = 0;   // the collection's first row id
	uint64_t offset = 0; // where its rows start in the destination (upper bound of the rows before it)
	uint64_t upper = 0;  // rows in the collection (visible or not): an upper bound of what this source yields
};

// Rows of one table, in the single-threaded scan order: parallel tasks write their rows at their row-group position, then the
// rows are packed toward the front where a task returned fewer rows than its range (deleted rows, rows of a newer snapshot).
// Every worker uses the caller's transaction, so all see one snapshot (and its own uncommitted rows).
// With a pushed-down predicate (PushedScan): DuckDB's table filters are applied inside the scan (zone maps skip row groups and
// vectors; a vector returns only its matching rows) and the filters DuckDB kept above its scan (`residual`) select rows of each
// chunk before any cell is decoded, so only matching rows are handed over.
uint64_t ScanTable(ClientContext &context, DuckTransaction &transaction, DataTable &storage, const vector<StorageIndex> &ids,
                   const vector<LogicalType> &types, std::vector<ColPlan> &plans, const std::shared_ptr<Executor> &exec,
                   ScanResult &res, idx_t want_threads, TableFilterSet *filters, const Expression *residual) {
	std::vector<std::unique_ptr<ScanSource>> sources;
	auto committed = make_uniq<ScanSource>();
	committed->collection = storage.GetRowGroupCollection().get();
	committed->collection->InitializeParallelScan(committed->state);
	committed->base = committed->state.row_groups->GetBaseRowId();
	committed->upper = committed->state.max_row - committed->base;
	uint64_t upper = committed->upper;
	sources.push_back(std::move(committed));
	auto local_storage = LocalStorage::Get(transaction).GetStorage(storage);
	if (local_storage && local_storage->GetCollection().GetTotalRows() > 0) {
		auto local = make_uniq<ScanSource>();
		local->collection = &local_storage->GetCollection();
		local->local = true;
		local->collection->InitializeParallelScan(local->state);
		local->base = local->state.row_groups->GetBaseRowId();
		local->upper = local->state.max_row - local->base;
		local->offset = upper;
		upper += local->upper;
		sources.push_back(std::move(local));
	}
	// destinations, sized for the upper bound
	size_t nstrings = 0, ndicts = 0;
	for (size_t pi = 0; pi < plans.size(); pi++) {
		plans[pi].idx = pi;
	}
	for (auto &p : plans) {
		if (p.role == Role::String) {
			p.slot = nstrings++;
		} else if (p.role == Role::Code) {
			p.slot = ndicts++;
		}
		if (p.width == 0) {
			continue;
		}
		if (res.owned[p.k]) {
			throw InternalException("Lemma: input %d scanned twice", int64_t(p.k));
		}
		if (OwnedType(p.e.rust_type)) {
			res.owned[p.k] = std::make_shared<OwnedBuffer>(exec, p.k, upper, p.width);
			p.dest = res.owned[p.k]->ptr;
		} else {
			res.bytes[p.k].resize(upper);
			p.dest = res.bytes[p.k].data();
		}
	}
	idx_t row_group_rows = MaxValue<idx_t>(1, storage.GetRowGroupSize());
	idx_t tasks_estimate = upper / row_group_rows + sources.size();
	idx_t nthreads = MaxValue<idx_t>(1, MinValue<idx_t>(want_threads, tasks_estimate));

	std::mutex out_lock;
	std::vector<std::unique_ptr<TaskOut>> tasks;
	std::atomic<bool> stop {false};
	std::exception_ptr error;
	// A filtered scan stages each task's cells and commits them in task order (TaskOut::stage); a whole-table scan writes them
	// at the task's row-group position and packs the (rare) gaps of deleted rows afterwards.
	const bool staged = filters || residual;
	std::mutex order_lock;
	std::condition_variable order_cv;
	std::vector<std::unique_ptr<std::vector<std::vector<uint8_t>>>> spare; // free staging sets
	idx_t stage_sets = 0;
	uint64_t next_seq = 0, frontier = 0, frontier_at = 0, last_start = 0;
	std::map<uint64_t, TaskOut *> finished; // decoded tasks waiting for every earlier task's row count
	auto commit = [&](TaskOut *t) {
		std::vector<TaskOut *> ready;
		{
			std::lock_guard<std::mutex> guard(order_lock);
			finished[t->seq] = t;
			for (auto it = finished.find(frontier); it != finished.end(); it = finished.find(frontier)) {
				it->second->offset = frontier_at;
				frontier_at += it->second->count;
				ready.push_back(it->second);
				finished.erase(it);
				frontier++;
			}
		}
		for (auto r : ready) { // copy to the final place, outside the lock: the places of different tasks never overlap
			for (auto &p : plans) {
				if (p.dest && r->count) {
					std::memcpy(p.dest + p.width * r->offset, (*r->stage)[p.idx].data(), p.width * r->count);
				}
			}
			std::lock_guard<std::mutex> guard(order_lock);
			spare.push_back(std::move(r->stage));
			order_cv.notify_all();
		}
	};
	auto worker = [&]() {
		try {
			TableScanState ts;
			ts.Initialize(ids, &context, filters && !filters->filters.empty() ? filters : nullptr);
			DataChunk chunk;
			chunk.Initialize(Allocator::Get(context), types);
			unique_ptr<ExpressionExecutor> keep; // the residual predicate, one executor per worker (its state is not shared)
			SelectionVector sel(STANDARD_VECTOR_SIZE);
			if (residual) {
				keep = make_uniq<ExpressionExecutor>(context, *residual);
			}
			for (auto &src : sources) {
				CollectionScanState &cs = src->local ? ts.local_state : ts.table_state;
				while (!stop.load()) {
					auto t = make_uniq<TaskOut>();
					bool got;
					if (staged) {
						// A staging set and the next task under one lock: task order = sequence order, and the earliest unfinished
						// task always holds a set, so a worker waiting for a set never waits on itself.
						std::unique_lock<std::mutex> lk(order_lock);
						if (spare.empty() && stage_sets < 2 * nthreads) {
							stage_sets++;
							auto set = make_uniq<std::vector<std::vector<uint8_t>>>(plans.size());
							for (auto &p : plans) {
								(*set)[p.idx].resize(p.width * row_group_rows);
							}
							spare.push_back(std::move(set));
						}
						order_cv.wait(lk, [&]() { return !spare.empty() || stop.load(); });
						if (stop.load()) {
							break;
						}
						got = src->collection->NextParallelScan(context, src->state, cs);
						if (got) {
							t->stage = std::move(spare.back());
							spare.pop_back();
							t->seq = next_seq++;
							uint64_t at = src->offset + (cs.row_group->GetRowStart() + cs.vector_index * STANDARD_VECTOR_SIZE - src->base);
							if (t->seq > 0 && at < last_start) {
								throw InternalException("Lemma: scan tasks handed out out of row order");
							}
							last_start = at;
						}
					} else {
						got = src->collection->NextParallelScan(context, src->state, cs);
					}
					if (!got) {
						break;
					}
					uint64_t start = cs.row_group->GetRowStart() + cs.vector_index * STANDARD_VECTOR_SIZE;
					if (start < src->base || cs.max_row < start || cs.max_row - src->base > src->upper) {
						throw InternalException("Lemma: a scan task outside its table (%d..%d)", int64_t(start),
						                        int64_t(cs.max_row));
					}
					t->offset = src->offset + (start - src->base);
					uint64_t range = cs.max_row - start;
					if (staged) {
						if (range > row_group_rows) {
							throw InternalException("Lemma: a scan task larger than a row group");
						}
					}
					t->strings.resize(nstrings);
					t->dicts.resize(ndicts);
					while (true) {
						chunk.Reset();
						if (!cs.Scan(transaction, chunk) || chunk.size() == 0) {
							break;
						}
						if (t->count + chunk.size() > range) {
							throw InternalException("Lemma: a scan task returned more rows than its range");
						}
						if (keep) {
							idx_t kept = keep->SelectExpression(chunk, sel);
							if (kept == 0) {
								continue;
							}
							if (kept < chunk.size()) {
								chunk.Slice(sel, kept);
							}
						}
						for (auto &p : plans) {
							DecodeChunk(p, chunk.data[p.chunk_col], chunk.size(), *t);
						}
						t->count += chunk.size();
					}
					TaskOut *raw = t.get();
					{
						std::lock_guard<std::mutex> guard(out_lock);
						tasks.push_back(std::move(t));
					}
					if (staged) {
						commit(raw);
					}
				}
			}
		} catch (...) {
			{
				std::lock_guard<std::mutex> guard(out_lock);
				if (!error) {
					error = std::current_exception();
				}
			}
			std::lock_guard<std::mutex> guard(order_lock);
			stop = true;
			order_cv.notify_all();
		}
	};
	{
		std::vector<std::thread> pool;
		for (idx_t i = 1; i < nthreads; i++) {
			pool.emplace_back(worker);
		}
		worker();
		for (auto &th : pool) {
			th.join();
		}
	}
	if (error) {
		std::rethrow_exception(error);
	}
	if (staged && (!finished.empty() || frontier != next_seq)) {
		throw InternalException("Lemma: a staged scan task was never committed");
	}
	// Row order: tasks by position; pack fixed-width cells toward the front where a task left a gap. A staged task that kept no
	// row has the same final offset as the task after it: the hand-out order (seq) breaks that tie, else an unstable sort could
	// put the empty task second and the check below would see an overlap (SEC q24 with its pushed predicate). Unstaged tasks have
	// distinct offsets (their row-group positions) and seq 0.
	std::sort(tasks.begin(), tasks.end(), [](const std::unique_ptr<TaskOut> &a, const std::unique_ptr<TaskOut> &b) {
		return a->offset != b->offset ? a->offset < b->offset : a->seq < b->seq;
	});
	uint64_t total = 0;
	for (auto &t : tasks) {
		if (t->offset < total) {
			throw InternalException("Lemma: overlapping scan tasks");
		}
		if (t->offset != total) {
			for (auto &p : plans) {
				if (p.dest && t->count) {
					std::memmove(p.dest + p.width * total, p.dest + p.width * t->offset, p.width * t->count);
				}
			}
			t->offset = total;
		}
		total += t->count;
	}
	// Dictionary codes: number the distinct strings in order of first appearance in row order (the tasks in order, each task's
	// strings in its order), then rewrite each task's codes where its own numbering differs; a NULL cell is code 0.
	for (auto &p : plans) {
		if (p.role != Role::Code) {
			continue;
		}
		LocalDict global;
		std::vector<std::vector<uint32_t>> remaps(tasks.size());
		std::vector<bool> identity(tasks.size(), true);
		for (size_t ti = 0; ti < tasks.size(); ti++) {
			LocalDict &d = tasks[ti]->dicts[p.slot];
			auto &remap = remaps[ti];
			remap.resize(d.entries.size());
			for (size_t c = 0; c < d.entries.size(); c++) {
				const std::string &s = d.entries[c];
				string_t key(s.data(), uint32_t(s.size()));
				auto it = global.codes.find(key);
				uint32_t code;
				if (it != global.codes.end()) {
					code = it->second;
				} else {
					if (global.entries.size() >= p.code_limit) {
						throw InvalidInputException("Lemma: cannot pack code %d as %s (%s)", int64_t(global.entries.size()),
						                            p.e.rust_type, p.label);
					}
					code = uint32_t(global.entries.size());
					global.entries.push_back(s);
					const std::string &kept = global.entries.back();
					global.codes.emplace(string_t(kept.data(), uint32_t(kept.size())), code);
				}
				remap[c] = code;
				identity[ti] = identity[ti] && code == c;
			}
			global.null_seen = global.null_seen || !d.nulls.empty();
		}
		std::atomic<size_t> next {0};
		auto rewrite = [&]() {
			for (size_t ti = next++; ti < tasks.size(); ti = next++) {
				if (identity[ti]) {
					continue;
				}
				TaskOut &t = *tasks[ti];
				uint8_t *base = p.dest + p.width * t.offset;
				for (uint64_t r = 0; r < t.count; r++) {
					uint32_t c = 0;
					std::memcpy(&c, base + p.width * r, p.width);
					PutCell(base + p.width * r, p.width, remaps[ti][c]);
				}
				for (auto r : t.dicts[p.slot].nulls) {
					PutCell(base + p.width * r, p.width, 0);
				}
			}
		};
		{
			std::vector<std::thread> pool;
			for (idx_t i = 1; i < nthreads; i++) {
				pool.emplace_back(rewrite);
			}
			rewrite();
			for (auto &th : pool) {
				th.join();
			}
		}
		// the dictionary input of this codes field
		std::string out;
		std::vector<std::string> entries(global.entries.begin(), global.entries.end());
		if (entries.empty() && global.null_seen) {
			entries.emplace_back(""); // every cell is NULL: code 0 still has to index an entry
		}
		for (auto &s : entries) {
			PutStr(out, s.data(), s.size());
		}
		if (p.dict_k == SIZE_MAX) {
			throw InvalidInputException("Lemma: %s: a codes field without its dictionary", p.label);
		}
		res.buffers[p.dict_k] = std::move(out);
		res.cols[p.dict_k] = LemmaCol {nullptr, 0, entries.size()};
	}
	for (auto &p : plans) {
		if (p.role == Role::String) {
			size_t size = 0;
			for (auto &t : tasks) {
				size += t->strings[p.slot].size();
			}
			std::string out;
			out.reserve(size);
			for (auto &t : tasks) {
				out += t->strings[p.slot];
			}
			res.buffers[p.k] = std::move(out);
		}
	}
	return total;
}

// The transpiler's pushed-down predicate of one table, planned by DuckDB: the columns to scan (the needed ones and those the
// predicate reads, in DuckDB's scan order), the table filters DuckDB's filter pushdown put into its scan, and the part it kept
// above the scan as one expression over chunk positions. `empty`: DuckDB proved the predicate never holds (no row is scanned).
struct PushedScan {
	vector<StorageIndex> ids;
	vector<LogicalType> types;
	std::unordered_map<std::string, idx_t> pos; // column name -> chunk column
	unique_ptr<TableFilterSet> filters;
	unique_ptr<Expression> residual;
	bool empty = false;
};

unique_ptr<Expression> ToChunkRefs(unique_ptr<Expression> e, const std::map<std::pair<idx_t, idx_t>, idx_t> &chunk_col) {
	if (e->GetExpressionClass() == ExpressionClass::BOUND_COLUMN_REF) {
		auto &ref = e->Cast<BoundColumnRefExpression>();
		auto it = chunk_col.find({ref.binding.table_index, ref.binding.column_index});
		if (it == chunk_col.end()) {
			throw InternalException("Lemma: a pushed filter reads a column the scan does not produce");
		}
		return make_uniq<BoundReferenceExpression>(ref.return_type, it->second);
	}
	ExpressionIterator::EnumerateChildren(*e, [&](unique_ptr<Expression> &child) { child = ToChunkRefs(std::move(child), chunk_col); });
	return e;
}

// `SELECT <cols> FROM <table> WHERE <where>` bound in the caller's context and given DuckDB's own expression rewriter and filter
// pushdown (no other optimizer, no optimizer extension): the plan is PROJECTION / FILTER / GET of this very table, or EMPTY_RESULT.
// Any other shape is an error, never a silent full scan. The predicate is the transpiler's (pushdown.py: single-table, sound to
// apply before the proved code); trusted here: DuckDB evaluates it correctly (docs/TRUSTED_FAMILIES.md).
PushedScan PlanPushdown(ClientContext &context, TableCatalogEntry &entry, const std::string &table,
                        const std::vector<std::string> &cols, const std::string &where) {
	std::string q = "SELECT ";
	for (size_t i = 0; i < cols.size(); i++) {
		q += (i ? ", " : "") + KeywordHelper::WriteQuoted(cols[i], '"');
	}
	q += " FROM " + KeywordHelper::WriteQuoted(table, '"') + " WHERE " + where;
	Parser parser(context.GetParserOptions());
	parser.ParseQuery(q);
	if (parser.statements.size() != 1 || parser.statements[0]->type != StatementType::SELECT_STATEMENT) {
		throw InvalidInputException("Lemma: the pushed predicate of %s is not one WHERE clause: %s", table, where);
	}
	auto binder = Binder::CreateBinder(context);
	auto bound = binder->Bind(*parser.statements[0]);
	Optimizer optimizer(*binder, context);
	optimizer.rewriter.VisitOperator(*bound.plan);
	FilterPushdown pushdown(optimizer);
	auto plan = pushdown.Rewrite(std::move(bound.plan));
	PushedScan out;
	vector<unique_ptr<Expression>> kept;
	LogicalOperator *op = plan.get();
	while (op->type != LogicalOperatorType::LOGICAL_GET) {
		if (op->type == LogicalOperatorType::LOGICAL_EMPTY_RESULT) {
			out.empty = true;
			return out;
		}
		if (op->type == LogicalOperatorType::LOGICAL_PROJECTION) {
			for (auto &e : op->expressions) {
				if (e->GetExpressionClass() != ExpressionClass::BOUND_COLUMN_REF) {
					throw InvalidInputException("Lemma: the pushed predicate of %s planned a computed projection", table);
				}
			}
		} else if (op->type == LogicalOperatorType::LOGICAL_FILTER) {
			if (!op->Cast<LogicalFilter>().projection_map.empty()) {
				throw InvalidInputException("Lemma: the pushed predicate of %s planned a projecting filter", table);
			}
			for (auto &e : op->expressions) {
				kept.push_back(e->Copy());
			}
		} else {
			throw InvalidInputException("Lemma: DuckDB planned the pushed predicate of %s as %s; the scan cannot apply it", table,
			                            LogicalOperatorToString(op->type));
		}
		if (op->children.size() != 1) {
			throw InvalidInputException("Lemma: the pushed predicate of %s planned an operator with %d inputs", table,
			                            int64_t(op->children.size()));
		}
		op = op->children[0].get();
	}
	auto &get = op->Cast<LogicalGet>();
	auto scanned = get.GetTable();
	if (!scanned || scanned.get() != &entry || !op->children.empty()) {
		throw InvalidInputException("Lemma: the pushed predicate of %s was not planned as a scan of that table", table);
	}
	auto &column_ids = get.GetColumnIds();
	for (idx_t i = 0; i < column_ids.size(); i++) {
		if (column_ids[i].IsVirtualColumn() || column_ids[i].HasChildren()) {
			throw InvalidInputException("Lemma: the pushed predicate of %s scans a virtual or nested column", table);
		}
		auto &col = entry.GetColumn(LogicalIndex(column_ids[i].GetPrimaryIndex()));
		out.ids.emplace_back(col.StorageOid());
		out.types.push_back(col.Type());
		out.pos[col.Name()] = i;
	}
	// The logical plan keys its table filters by the table's column index; the scan keys them by position in its column ids (what
	// DuckDB's physical planner does, CreateTableFilterSet). A filter on a type the scan cannot filter (supports_pushdown_type) is
	// evaluated as an expression on the chunk instead, as DuckDB's own plan does.
	out.filters = make_uniq<TableFilterSet>();
	vector<unique_ptr<Expression>> residual;
	for (auto &f : get.table_filters.filters) {
		optional_idx at;
		for (idx_t i = 0; i < column_ids.size(); i++) {
			if (column_ids[i].GetPrimaryIndex() == f.first) {
				at = i;
				break;
			}
		}
		if (!at.IsValid()) {
			throw InternalException("Lemma: a pushed table filter of %s on a column the scan does not read", table);
		}
		if (get.function.supports_pushdown_type && !get.function.supports_pushdown_type(*get.bind_data, f.first)) {
			BoundReferenceExpression ref(out.types[at.GetIndex()], at.GetIndex());
			residual.push_back(f.second->ToExpression(ref));
		} else {
			out.filters->filters[at.GetIndex()] = f.second->Copy();
		}
	}
	if (!kept.empty()) {
		std::map<std::pair<idx_t, idx_t>, idx_t> chunk_col;
		auto bindings = get.GetColumnBindings();
		for (idx_t i = 0; i < bindings.size(); i++) {
			chunk_col[{bindings[i].table_index, bindings[i].column_index}] = get.projection_ids.empty() ? i : get.projection_ids[i];
		}
		for (auto &e : kept) {
			residual.push_back(ToChunkRefs(std::move(e), chunk_col));
		}
	}
	unique_ptr<Expression> all;
	for (auto &e : residual) {
		all = all ? make_uniq<BoundConjunctionExpression>(ExpressionType::CONJUNCTION_AND, std::move(all), std::move(e)) : std::move(e);
	}
	out.residual = std::move(all);
	return out;
}

// A query template's `$name` placeholders (outside quotes and comments) replaced by the SQL literals of the values lemma_query was
// given; the same substitution as the SQL DuckDB answers a routed decline with.
std::string SubstituteParams(const Manifest &m, const std::string &sql, const std::unordered_map<std::string, std::string> &literal);

// One table of the manifest, resolved in the caller's transaction and planned: what ScanTable reads, and the scan's identity for
// the input cache (the table, its pushed predicate as DuckDB planned it in this call).
struct TablePrep {
	size_t i = 0;
	TableCatalogEntry *entry = nullptr;
	DataTable *storage = nullptr;
	DuckTransaction *transaction = nullptr;
	vector<StorageIndex> ids;
	vector<LogicalType> types;
	std::vector<ColPlan> plans;
	PushedScan pushed;
	std::string identity;
};

// Resolve and plan every table of the manifest (column type checks, the pushed predicate with this call's values) without
// reading a row.
std::vector<TablePrep> PrepareInputs(ClientContext &context, const Manifest &m,
                                     const std::unordered_map<std::string, std::string> &literals) {
	std::vector<TablePrep> preps;
	size_t i = 0;
	while (i < m.inputs.size()) {
		const InEntry &rows = m.inputs[i];
		if (!rows.rows) {
			throw InvalidInputException("Lemma: manifest input %d is not a rows entry", int64_t(i));
		}
		size_t end = i + 1;
		while (end < m.inputs.size() && !m.inputs[end].rows) {
			end++;
		}
		auto &entry = Catalog::GetEntry<TableCatalogEntry>(context, INVALID_CATALOG, INVALID_SCHEMA, rows.table);
		if (!entry.IsDuckTable()) {
			throw InvalidInputException("Lemma: %s is not a DuckDB table", rows.table);
		}
		auto &storage = entry.GetStorage();
		auto &transaction = DuckTransaction::Get(context, entry.ParentCatalog());
		vector<StorageIndex> ids;
		vector<LogicalType> types;
		std::unordered_map<std::string, idx_t> pos; // column name -> chunk column
		std::vector<ColPlan> plans;
		std::unordered_map<size_t, size_t> dict_of_codes; // codes input -> its dictionary input
		for (size_t k = i + 1; k < end; k++) {
			const InEntry &e = m.inputs[k];
			auto &col = entry.GetColumn(e.column);
			if (col.Generated()) {
				throw InvalidInputException("Lemma: %s.%s is a generated column", rows.table, e.column);
			}
			if (col.Type().ToString() != e.duck_type) {
				throw InvalidInputException("Lemma: %s.%s is %s now, the executor was proved for %s", rows.table, e.column,
				                            col.Type().ToString(), e.duck_type);
			}
			if (pos.find(col.Name()) == pos.end()) {
				pos[col.Name()] = ids.size();
				ids.emplace_back(col.StorageOid());
				types.push_back(col.Type());
			}
			ColPlan p;
			p.k = k;
			p.e = e;
			p.label = rows.table + "." + e.column;
			p.role = RoleOf(e.role, p.label);
			if (p.role == Role::Dict) {
				if (e.codes_of <= int64_t(i) || e.codes_of >= int64_t(end) || m.inputs[size_t(e.codes_of)].role != "code" ||
				    dict_of_codes.count(size_t(e.codes_of))) {
					throw InvalidInputException("Lemma: %s.%s: the dictionary names no codes field", rows.table, e.column);
				}
				dict_of_codes[size_t(e.codes_of)] = k; // filled from its codes field by the scan
				continue;
			}
			p.chunk_col = pos[col.Name()];
			p.type = col.Type();
			switch (p.role) {
			case Role::Code:
				p.target = TargetOf(e.rust_type);
				p.code_limit = e.rust_type == "u8" ? 256ull : e.rust_type == "u16" ? 65536ull : 4294967296ull;
				p.width = size_t(p.target.width);
				break;
			case Role::Int:
			case Role::Date:
			case Role::Decimal:
				p.target = TargetOf(e.rust_type);
				p.width = size_t(p.target.width);
				break;
			case Role::F64:
				p.width = 8;
				break;
			case Role::Bool:
			case Role::Valid:
				p.width = 1;
				break;
			default:
				p.width = 0;
				break;
			}
			if (p.width && OwnedType(e.rust_type) != (p.role != Role::Bool && p.role != Role::Valid)) {
				throw InvalidInputException("Lemma: %s: role %s does not fit the field type %s", p.label, e.role, e.rust_type);
			}
			if (p.role == Role::Decimal || (p.role == Role::F64 && col.Type().id() == LogicalTypeId::DECIMAL)) {
				if (e.source_scale > e.scale) {
					throw InvalidInputException("Lemma: %s has more than %d fractional digits", p.label, e.scale);
				}
				p.mul = Pow10(e.scale - e.source_scale);
				p.decimal_wide = DecimalType::GetWidth(col.Type()) + (e.scale - e.source_scale) > 18;
			}
			plans.push_back(std::move(p));
		}
		if (ids.empty()) {
			// No column is read (e.g. COUNT(*)): count the rows visible to this transaction with a scan of the first column.
			auto &first = entry.GetColumns().GetColumn(PhysicalIndex(0));
			ids.emplace_back(first.StorageOid());
			types.push_back(first.Type());
			pos[first.Name()] = 0;
		}
		for (auto &p : plans) {
			if (p.role == Role::Code && dict_of_codes.count(p.k)) {
				p.dict_k = dict_of_codes[p.k];
			}
		}
		PushedScan pushed;
		if (!rows.where.empty()) {
			// The transpiler's pushdown (manifest "where"): DuckDB filters inside the scan, only matching rows are decoded.
			std::vector<std::string> names(ids.size());
			for (auto &kv : pos) {
				names[kv.second] = kv.first;
			}
			pushed = PlanPushdown(context, entry, rows.table, names, SubstituteParams(m, rows.where, literals));
			if (pushed.empty) {
				pushed.residual = make_uniq<BoundConstantExpression>(Value::BOOLEAN(false)); // DuckDB: never true; no row is kept
			} else {
				for (auto &p : plans) {
					auto it = pushed.pos.find(names[p.chunk_col]);
					if (it == pushed.pos.end()) {
						throw InternalException("Lemma: the pushed scan of %s lost column %s", rows.table, names[p.chunk_col]);
					}
					p.chunk_col = it->second;
				}
				ids = pushed.ids;
				types = pushed.types;
			}
		}
		TablePrep prep;
		prep.i = i;
		prep.entry = &entry;
		prep.storage = &storage;
		prep.transaction = &transaction;
		auto &catalog = entry.ParentCatalog();
		prep.identity = catalog.GetName() + "." + entry.schema.name + "." + entry.name + "@" +
		                std::to_string(reinterpret_cast<uintptr_t>(&catalog.GetAttached())) + "/" +
		                std::to_string(reinterpret_cast<uintptr_t>(&storage)) + " where " +
		                (rows.where.empty() ? std::string("-") : SubstituteParams(m, rows.where, literals));
		if (pushed.empty) {
			prep.identity += " planned: empty";
		}
		if (pushed.filters) {
			for (auto &f : pushed.filters->filters) {
				prep.identity += " filter[" + std::to_string(f.first) + "]: " + f.second->ToString("c" + std::to_string(f.first));
			}
		}
		if (pushed.residual) {
			prep.identity += " residual: " + pushed.residual->ToString();
		}
		prep.ids = std::move(ids);
		prep.types = std::move(types);
		prep.plans = std::move(plans);
		prep.pushed = std::move(pushed);
		preps.push_back(std::move(prep));
		i = end;
	}
	return preps;
}

// Scan the prepared tables: exactly the columns the manifest names, in the caller's transaction (its snapshot, its own
// uncommitted changes included), on lemma_scan_threads threads (default: DuckDB's `threads`), in single-threaded row order.
// Fixed-width integer and f64 fields are decoded once, straight into buffers of the executor library (owned inputs, ABI 3); bool
// and validity into byte buffers; strings and dictionaries into byte strings.
ScanResult ScanPrepared(ClientContext &context, const Manifest &m, std::vector<TablePrep> &preps) {
	auto start = std::chrono::steady_clock::now();
	ScanResult res;
	res.buffers.resize(m.inputs.size());
	res.bytes.resize(m.inputs.size());
	res.owned.resize(m.inputs.size());
	res.cols.resize(m.inputs.size());
	idx_t want_threads = ScanThreads(context);
	for (auto &prep : preps) {
		auto &plans = prep.plans;
		uint64_t total = ScanTable(context, *prep.transaction, *prep.storage, prep.ids, prep.types, plans, m.exec, res,
		                           want_threads, prep.pushed.filters.get(), prep.pushed.residual.get());
		res.cols[prep.i] = LemmaCol {nullptr, 0, total};
		for (auto &p : plans) {
			if (p.role == Role::String) {
				res.cols[p.k] = LemmaCol {nullptr, 0, total};
			} else if (p.width) {
				if (res.owned[p.k]) {
					res.cols[p.k] = LemmaCol {res.owned[p.k]->ptr, res.owned[p.k]->len, total};
				} else {
					res.bytes[p.k].resize(total);
					res.cols[p.k] = LemmaCol {res.bytes[p.k].data(), total, total};
				}
			}
		}
	}
	for (size_t k = 0; k < res.cols.size(); k++) {
		if (!res.owned[k] && res.bytes[k].empty() && !m.inputs[k].rows) {
			res.cols[k].data = reinterpret_cast<const uint8_t *>(res.buffers[k].data());
			res.cols[k].len = res.buffers[k].size();
		}
	}
	res.scan_us = MicrosSince(start);
	return res;
}

// ---------------------------------------------------------------- the input cache (lemma_cache)
//
// Key: the manifest (its sha256: the query, layouts, inputs, pushed predicates), the data epoch, and per table its identity (catalog,
// schema, name, database and storage addresses) and its pushed predicate with this call's values substituted and as DuckDB
// planned it. A query template's values reach the inputs only through the pushed predicates, so different values are different
// keys. An entry is used only by a call whose snapshot is current at the entry's epoch (DataVersion) and that has no changes of its
// own; otherwise the call scans and stores nothing. LRU eviction under lemma_cache_max_mb.

struct InputCache {
	std::mutex lock;
	std::list<std::string> lru; // most recently used first
	std::unordered_map<std::string, std::pair<std::shared_ptr<const CachedInputs>, std::list<std::string>::iterator>> map;
	uint64_t bytes = 0, hits = 0, misses = 0, stores = 0, evictions = 0, skips = 0;
	// Copies of owned cells into or out of the cache (ABI 4 executors only: lemma_run takes its buffers): calls that copied, bytes.
	uint64_t copies = 0, copy_bytes = 0;

	// Under `lock`.
	void Drop(std::unordered_map<std::string, std::pair<std::shared_ptr<const CachedInputs>, std::list<std::string>::iterator>>::iterator it) {
		bytes -= it->second.first->size;
		lru.erase(it->second.second);
		map.erase(it);
	}
	void DropOtherEpochs(uint64_t epoch) {
		for (auto it = map.begin(); it != map.end();) {
			auto next = std::next(it);
			if (it->second.first->epoch != epoch) {
				Drop(it);
				evictions++;
			}
			it = next;
		}
	}
};

InputCache &Cache() {
	static auto *c = new InputCache(); // never destroyed (see Version())
	return *c;
}

uint64_t CacheCapBytes(ClientContext &context) {
	Value v;
	double mb = -1;
	if (context.TryGetCurrentSetting("lemma_cache_max_mb", v) && !v.IsNull()) {
		mb = v.GetValue<double>();
	}
	if (mb < 0) { // default: a quarter of DuckDB's memory_limit
		return BufferManager::GetBufferManager(context).GetMaxMemory() / 4;
	}
	return uint64_t(mb * 1024.0 * 1024.0);
}

// memcpy of many (dest, src, bytes) jobs on `threads` threads, in pieces of at most 32 MB.
void ParallelCopy(const std::vector<std::tuple<uint8_t *, const uint8_t *, uint64_t>> &jobs, idx_t threads) {
	constexpr uint64_t PIECE = 32ull << 20;
	std::vector<std::tuple<uint8_t *, const uint8_t *, uint64_t>> pieces;
	for (auto &j : jobs) {
		for (uint64_t off = 0; off < std::get<2>(j); off += PIECE) {
			pieces.emplace_back(std::get<0>(j) + off, std::get<1>(j) + off, MinValue<uint64_t>(PIECE, std::get<2>(j) - off));
		}
	}
	std::atomic<size_t> next {0};
	auto work = [&]() {
		for (size_t i = next++; i < pieces.size(); i = next++) {
			std::memcpy(std::get<0>(pieces[i]), std::get<1>(pieces[i]), std::get<2>(pieces[i]));
		}
	};
	idx_t n = MaxValue<idx_t>(1, MinValue<idx_t>(threads, idx_t(pieces.size())));
	std::vector<std::thread> pool;
	for (idx_t i = 1; i < n; i++) {
		pool.emplace_back(work);
	}
	work();
	for (auto &t : pool) {
		t.join();
	}
}

// Why this call may not use or fill the input cache ("" if it may), and the epoch its snapshot is current at.
std::string CacheBlocker(ClientContext &context, std::vector<TablePrep> &preps, uint64_t &epoch) {
	for (auto &prep : preps) {
		auto &catalog = prep.entry->ParentCatalog();
		if (catalog.IsTemporaryCatalog() || catalog.IsSystemCatalog() || catalog.GetAttached().IsTemporary()) {
			return "reads a temporary table";
		}
		// The caller's own uncommitted changes (local appends, deletes, updates) are in its snapshot, not in anyone else's.
		if (!prep.transaction->IsReadOnly() || prep.transaction->ChangesMade()) {
			return "this transaction has uncommitted changes";
		}
	}
	if (MetaTransaction::Get(context).ModifiedDatabase()) {
		return "this transaction has uncommitted changes";
	}
	auto &st = GetState(context);
	auto &v = Version();
	std::lock_guard<std::mutex> guard(v.lock);
	if (!st.tx_open || st.begin_epoch == NO_EPOCH) {
		return "this transaction began before LOAD";
	}
	if (st.begin_epoch != v.epoch) {
		return "a write committed since this transaction began";
	}
	if (v.open > (st.counted ? 1u : 0u)) {
		return "another connection has an open transaction";
	}
	epoch = v.epoch;
	return "";
}

std::string CacheKey(const Manifest &m, uint64_t epoch, const std::vector<TablePrep> &preps) {
	std::string key = m.manifest_sha256 + "|" + m.lib_sha256 + "|epoch " + std::to_string(epoch);
	for (auto &prep : preps) {
		key += "|" + prep.identity;
	}
	return key;
}

InputCache &Cache();

void CountCopy(const std::vector<std::tuple<uint8_t *, const uint8_t *, uint64_t>> &jobs) {
	if (jobs.empty()) {
		return;
	}
	uint64_t bytes = 0;
	for (auto &j : jobs) {
		bytes += std::get<2>(j);
	}
	auto &c = Cache();
	std::lock_guard<std::mutex> guard(c.lock);
	c.copies++;
	c.copy_bytes += bytes;
}

// The inputs of one call from a cache entry. ABI 5: every input is handed over from the entry itself (the owned cells are lent:
// no allocation, no copy). ABI 4: owned inputs copied into fresh buffers of the library (lemma_run takes them), the borrowed ones
// handed over from the entry.
ScanResult FromCache(ClientContext &context, const Manifest &m, const std::shared_ptr<const CachedInputs> &e) {
	ScanResult res;
	res.owned.resize(m.inputs.size());
	res.cols = e->cols;
	std::vector<std::tuple<uint8_t *, const uint8_t *, uint64_t>> jobs;
	for (size_t k = 0; k < e->cols.size(); k++) {
		if (e->kind[k] != CachedInputs::OWNED) {
			continue;
		}
		uint64_t n = e->cols[k].n;
		res.owned[k] = std::make_shared<OwnedBuffer>(m.exec, k, n, e->width[k]);
		res.cols[k] = LemmaCol {res.owned[k]->ptr, res.owned[k]->len, n};
		jobs.emplace_back(res.owned[k]->ptr, e->owned[k].get(), n * e->width[k]);
	}
	ParallelCopy(jobs, ScanThreads(context));
	CountCopy(jobs);
	res.hold = e;
	res.cache_bytes = int64_t(e->size);
	return res;
}

// A cache entry from a fresh scan: the borrowed inputs move into it (and `res` points at them there). The owned cells: ABI 5, the
// entry keeps the scan's library buffers themselves (lent to this call and every later one, no copy); ABI 4, they are copied.
std::shared_ptr<CachedInputs> ToCache(ClientContext &context, const Manifest &m, ScanResult &res, uint64_t epoch,
                                      std::vector<TablePrep> &preps) {
	auto e = std::make_shared<CachedInputs>();
	size_t n = m.inputs.size();
	e->kind.resize(n);
	e->buffers.resize(n);
	e->bytes.resize(n);
	e->owned.resize(n);
	e->lent.resize(n);
	e->width.resize(n, 0);
	e->cols = res.cols;
	e->epoch = epoch;
	std::vector<std::tuple<uint8_t *, const uint8_t *, uint64_t>> jobs;
	for (size_t k = 0; k < n; k++) {
		if (m.inputs[k].rows) {
			e->kind[k] = CachedInputs::ROWS;
		} else if (res.owned[k] && m.exec->abi >= 5) {
			e->kind[k] = CachedInputs::LENT;
			e->width[k] = res.owned[k]->width;
			e->lent[k] = res.owned[k];
			e->size += res.cols[k].n * e->width[k];
		} else if (res.owned[k]) {
			e->kind[k] = CachedInputs::OWNED;
			e->width[k] = res.owned[k]->width;
			uint64_t len = res.cols[k].n * e->width[k];
			e->owned[k] = std::unique_ptr<uint8_t[]>(new uint8_t[MaxValue<uint64_t>(len, 1)]);
			jobs.emplace_back(e->owned[k].get(), res.owned[k]->ptr, len);
			e->cols[k] = LemmaCol {nullptr, 0, res.cols[k].n};
			e->size += len;
		} else if (!res.bytes[k].empty()) {
			e->kind[k] = CachedInputs::BYTES;
			e->bytes[k] = std::move(res.bytes[k]);
			e->cols[k] = LemmaCol {e->bytes[k].data(), res.cols[k].len, res.cols[k].n};
			e->size += e->bytes[k].size();
		} else {
			e->kind[k] = CachedInputs::BUFFER;
			e->buffers[k] = std::move(res.buffers[k]);
			e->cols[k] = LemmaCol {reinterpret_cast<const uint8_t *>(e->buffers[k].data()), e->buffers[k].size(), res.cols[k].n};
			e->size += e->buffers[k].size();
		}
		if (e->kind[k] == CachedInputs::BYTES || e->kind[k] == CachedInputs::BUFFER) {
			res.cols[k] = e->cols[k]; // the moved bytes (a short string's bytes move with it)
		}
	}
	ParallelCopy(jobs, ScanThreads(context));
	CountCopy(jobs);
	for (auto &prep : preps) {
		e->databases.push_back(prep.entry->ParentCatalog().GetAttached().shared_from_this());
	}
	res.hold = e;
	return e;
}

// The inputs of one executor call: from the input cache when this call's snapshot allows it and an entry exists, else from a
// scan (stored in the cache when allowed). res.scan_us is the whole preparation (plan + cache or scan); res.cache says which.
ScanResult ScanInputs(ClientContext &context, const Manifest &m, const std::unordered_map<std::string, std::string> &literals) {
	auto start = std::chrono::steady_clock::now();
	auto preps = PrepareInputs(context, m, literals);
	if (!BoolSetting(context, "lemma_cache")) {
		auto res = ScanPrepared(context, m, preps);
		res.cache = "off";
		res.scan_us = MicrosSince(start);
		return res;
	}
	auto &cache = Cache();
	uint64_t epoch = 0;
	std::string blocker = CacheBlocker(context, preps, epoch);
	if (!blocker.empty()) {
		{
			std::lock_guard<std::mutex> guard(cache.lock);
			cache.skips++;
		}
		auto res = ScanPrepared(context, m, preps);
		res.cache = "skip: " + blocker;
		res.scan_us = MicrosSince(start);
		return res;
	}
	std::string key = CacheKey(m, epoch, preps);
	std::shared_ptr<const CachedInputs> found;
	{
		std::lock_guard<std::mutex> guard(cache.lock);
		cache.DropOtherEpochs(epoch);
		auto it = cache.map.find(key);
		if (it != cache.map.end()) {
			bool alive = it->second.first->databases.size() == preps.size();
			for (size_t t = 0; alive && t < preps.size(); t++) {
				auto db = it->second.first->databases[t].lock();
				alive = db && db.get() == &preps[t].entry->ParentCatalog().GetAttached();
			}
			if (alive) {
				found = it->second.first;
				cache.lru.splice(cache.lru.begin(), cache.lru, it->second.second);
				cache.hits++;
			} else {
				cache.Drop(it);
				cache.evictions++;
			}
		}
		if (!found) {
			cache.misses++;
		}
	}
	if (found) {
		auto res = FromCache(context, m, found);
		res.cache = "hit";
		res.scan_us = MicrosSince(start);
		return res;
	}
	auto res = ScanPrepared(context, m, preps);
	uint64_t cap = CacheCapBytes(context);
	uint64_t need = 0;
	for (size_t k = 0; k < m.inputs.size(); k++) {
		need += res.owned[k] ? res.cols[k].n * res.owned[k]->width : res.bytes[k].size() + res.buffers[k].size();
	}
	if (need > cap) {
		res.cache = "miss: not stored (" + std::to_string(need) + " bytes > lemma_cache_max_mb)";
		res.scan_us = MicrosSince(start);
		return res;
	}
	auto entry = ToCache(context, m, res, epoch, preps);
	{
		std::lock_guard<std::mutex> guard(cache.lock);
		auto it = cache.map.find(key);
		if (it != cache.map.end()) {
			cache.Drop(it); // a concurrent call stored the same inputs first
		}
		while (!cache.lru.empty() && cache.bytes + entry->size > cap) {
			cache.Drop(cache.map.find(cache.lru.back()));
			cache.evictions++;
		}
		cache.lru.push_front(key);
		cache.map[key] = {entry, cache.lru.begin()};
		cache.bytes += entry->size;
		cache.stores++;
	}
	res.cache = "miss: stored";
	res.cache_bytes = int64_t(entry->size);
	res.scan_us = MicrosSince(start);
	return res;
}

// ---------------------------------------------------------------- running the executor and reading its result

struct ResultColumn {
	int kind = 0;
	const uint8_t *valid = nullptr;
	const uint8_t *cells = nullptr;
	std::vector<uint64_t> str_off; // string columns: offset of each cell's length prefix
};

struct RunResult {
	std::string bytes;
	uint64_t rows = 0;
	int64_t load_us = 0, run_us = 0;
	std::vector<ResultColumn> cols;
	bool declined = false;      // LEMMA_STATUS_DECLINED: run_query returned None; no rows, `decline_reason` says why
	std::string decline_reason;
	std::string mode = "batch"; // "batch" (ABI 4/5, lemma_run) or "stream" (ABI 6, StreamRun)
	int64_t chunks = -1, threads = -1; // stream: chunks stepped, scan threads (workers)
};

template <class T>
T Read(const std::string &b, size_t off) {
	T v;
	std::memcpy(&v, b.data() + off, sizeof(T));
	return v;
}

// One lemma_query argument as the executor takes it (lemma_abi.h): the value run_query receives, no conversion that could change
// it. BIGINT: an integer-typed value; DATE: a DATE value (its day number); DECIMAL(p,s): an integer or DECIMAL value with at most
// s fractional digits (scaled by 10^s, exact); VARCHAR: a VARCHAR value. Anything else, NULL included, is an error. The range
// run_query requires is checked by the library.
struct ParamBytes {
	uint32_t kind = 0;
	std::string bytes;
};

ParamBytes EncodeParam(const ParamSpec &p, const Value &v) {
	ParamBytes out;
	if (v.IsNull()) {
		throw BinderException("lemma_query: parameter %s is NULL", p.name);
	}
	auto &t = v.type();
	auto put_i64 = [&](int64_t x) {
		out.kind = PARAM_INT;
		out.bytes.assign(reinterpret_cast<const char *>(&x), sizeof(x));
	};
	if (p.sql_type == "VARCHAR") {
		if (t.id() != LogicalTypeId::VARCHAR) {
			throw BinderException("lemma_query: parameter %s is VARCHAR, got %s", p.name, t.ToString());
		}
		out.kind = PARAM_STR;
		out.bytes = StringValue::Get(v);
		return out;
	}
	if (p.sql_type == "BIGINT") {
		if (!t.IsIntegral()) {
			throw BinderException("lemma_query: parameter %s is BIGINT, got %s", p.name, t.ToString());
		}
		put_i64(v.DefaultCastAs(LogicalType::BIGINT).GetValue<int64_t>());
		return out;
	}
	if (p.sql_type == "DATE") {
		if (t.id() != LogicalTypeId::DATE) {
			throw BinderException("lemma_query: parameter %s is DATE, got %s (write DATE 'YYYY-MM-DD')", p.name, t.ToString());
		}
		put_i64(int64_t(v.GetValue<date_t>().days));
		return out;
	}
	if (p.sql_type.rfind("DECIMAL(", 0) == 0) {
		if (!t.IsIntegral() && t.id() != LogicalTypeId::DECIMAL) {
			throw BinderException("lemma_query: parameter %s is %s, got %s", p.name, p.sql_type, t.ToString());
		}
		static const std::regex number("^(-?)([0-9]+)(?:\\.([0-9]+))?$");
		std::string text = v.ToString();
		std::smatch mt;
		if (!std::regex_match(text, mt, number)) {
			throw BinderException("lemma_query: parameter %s: cannot read %s as a decimal", p.name, text);
		}
		std::string frac = mt[3].str();
		while (int(frac.size()) > p.scale && frac.back() == '0') {
			frac.pop_back(); // DECIMAL(18,4) 0.0500 is 0.05
		}
		if (int(frac.size()) > p.scale) {
			throw BinderException("lemma_query: parameter %s = %s has more than %d fractional digits", p.name, text, p.scale);
		}
		std::string digits = mt[2].str() + frac + std::string(size_t(p.scale) - frac.size(), '0');
		i128 scaled = 0;
		for (char c : digits) {
			scaled = scaled * 10 + (c - '0');
			if (scaled > i128(INT64_MAX)) {
				throw BinderException("lemma_query: parameter %s = %s does not fit the executor's i64", p.name, text);
			}
		}
		put_i64(int64_t(mt[1].str().empty() ? scaled : -scaled));
		return out;
	}
	throw InvalidInputException("Lemma: parameter %s has SQL type %s, which this extension cannot pass", p.name, p.sql_type);
}

RunResult ParseRun(const Manifest &m, int32_t code, std::string bytes);

RunResult RunExecutor(const Manifest &m, ScanResult &in, const std::vector<ParamBytes> &params) {
	LemmaOut out {nullptr, 0, 0};
	std::vector<LemmaParam> abi_params;
	for (auto &p : params) {
		abi_params.push_back(
		    LemmaParam {p.kind, reinterpret_cast<const uint8_t *>(p.bytes.data()), uint64_t(p.bytes.size())});
	}
	int32_t code;
	if (m.exec->abi >= 5) {
		// The owned-type inputs are LENT: the library reads them in place and gives them back untouched; they stay alive in `in`
		// (its own buffers, or the input cache entry it holds) until after the call, and are freed (or kept by the cache) by the
		// extension.
		code = m.exec->run_borrowed(in.cols.data(), in.cols.size(), abi_params.data(), abi_params.size(), &out);
	} else {
		in.ReleaseOwned(); // lemma_run takes every owned input buffer, whatever it returns (lemma_abi.h)
		code = m.exec->run(in.cols.data(), in.cols.size(), abi_params.data(), abi_params.size(), &out);
	}
	std::string bytes(reinterpret_cast<const char *>(out.ptr), size_t(out.len));
	m.exec->free_out(&out);
	return ParseRun(m, code, std::move(bytes));
}

// The status and bytes of lemma_run (ABI 4/5) or lemma_stream_finish (ABI 6): a decline, an error (raised), or the LMR1 result.
RunResult ParseRun(const Manifest &m, int32_t code, std::string bytes) {
	RunResult r;
	if (code == LEMMA_STATUS_DECLINED) {
		r.declined = true;
		r.decline_reason = bytes;
		return r;
	}
	if (code != LEMMA_STATUS_OK) {
		throw InvalidInputException("Lemma: the proved executor refused the data (no rows returned): %s", bytes);
	}
	r.bytes = std::move(bytes);
	const std::string &b = r.bytes;
	auto need = [&](size_t end) {
		if (end > b.size()) {
			throw InternalException("Lemma: executor result is truncated");
		}
	};
	need(32);
	if (b.compare(0, 4, "LMR1") != 0) {
		throw InternalException("Lemma: executor result has no LMR1 header");
	}
	r.load_us = int64_t(Read<uint64_t>(b, 4));
	r.run_us = int64_t(Read<uint64_t>(b, 12));
	r.rows = Read<uint64_t>(b, 20);
	uint32_t ncols = Read<uint32_t>(b, 28);
	size_t off = 32;
	if (ncols != m.outputs.size()) {
		throw InternalException("Lemma: executor returned %d columns, the manifest has %d", int64_t(ncols),
		                        int64_t(m.outputs.size()));
	}
	need(off + ncols);
	r.cols.resize(ncols);
	for (uint32_t c = 0; c < ncols; c++) {
		r.cols[c].kind = uint8_t(b[off + c]);
		if (r.cols[c].kind != m.outputs[c].kind) {
			throw InternalException("Lemma: result column %d has kind %d, the manifest says %d", int64_t(c),
			                        int64_t(r.cols[c].kind), int64_t(m.outputs[c].kind));
		}
	}
	off += ncols;
	const uint8_t *base = reinterpret_cast<const uint8_t *>(b.data());
	for (uint32_t c = 0; c < ncols; c++) {
		auto &col = r.cols[c];
		need(off + r.rows);
		col.valid = base + off;
		off += r.rows;
		col.cells = base + off;
		if (col.kind == KIND_STR) {
			col.str_off.resize(r.rows);
			for (uint64_t i = 0; i < r.rows; i++) {
				need(off + 4);
				col.str_off[i] = off;
				off += 4 + Read<uint32_t>(b, off);
			}
			need(off);
		} else {
			size_t w = col.kind == KIND_INT ? 16 : col.kind == KIND_F64 ? 8 : 1;
			need(off + w * r.rows);
			off += w * r.rows;
		}
	}
	if (off != b.size()) {
		throw InternalException("Lemma: executor result has trailing bytes");
	}
	return r;
}

// ---------------------------------------------------------------- ABI 6: StreamTable, a streaming executor (docs/STREAM.md)
//
// The ScanTable worker loop without destinations, packing or dictionaries (as the spike db_extension/duckdb_ext/spike/stream_spike.cpp
// measured it): DuckDB's parallel scan of the one table in the caller's transaction (committed row groups with MVCC, then this
// transaction's own uncommitted rows; NO pushed predicate: the proved step evaluates the WHERE), one executor worker per thread, every
// chunk handed to it in place as a LemmaChunk. (j, off) of a chunk come from ONE fetch_add of the stream's counter; after the scan the
// workers are merged pairwise and finished with the counter's final (m, n). This is what the trusted items S1 (chunk view) and S2
// (stream end) of the proof rely on (lemma_abi.h "ABI 6"); the proved runtime checks the tiling itself, so a lost, doubled or misplaced
// chunk is an ERROR (the test-only setting lemma_stream_fault injects one).

static_assert(sizeof(string_t) == 16 && string_t::INLINE_LENGTH == 12, "the stream ABI passes DuckDB 1.5.6 string_t as 16 bytes");
static_assert(sizeof(sel_t) == 4, "a stream VARCHAR selection is u32");

constexpr uint64_t STREAM_OFF_BITS = 36; // the counter: chunk index in the high 28 bits, row offset in the low 36 bits
constexpr uint64_t STREAM_OFF_MASK = (uint64_t(1) << STREAM_OFF_BITS) - 1;

// 0, 1, 2, ... (a FLAT VARCHAR vector's selection; a dictionary vector without a selection vector).
const uint32_t *IdentitySel() {
	static const auto *ids = [] {
		auto *v = new std::vector<uint32_t>(STANDARD_VECTOR_SIZE);
		for (idx_t i = 0; i < STANDARD_VECTOR_SIZE; i++) {
			(*v)[i] = uint32_t(i);
		}
		return v;
	}();
	return ids->data();
}

// DuckDB's dictionary id (a string) as the u64 the chunk carries: FNV-1a, never 0 (0 = FLAT or no id). Plain data for the agent.
uint64_t DictIdOf(const std::string &id) {
	if (id.empty()) {
		return 0;
	}
	uint64_t h = 1469598103934665603ull;
	for (unsigned char c : id) {
		h = (h ^ c) * 1099511628211ull;
	}
	return h ? h : 1;
}

// One worker's buffers for one chunk column: decoded cells (STANDARD_VECTOR_SIZE cells) and gathered string entries.
struct StreamCol {
	std::vector<uint8_t> cells;
	std::vector<string_t> ents;
	// a DICTIONARY vector whose dictionary has NULL entries: its entries with each NULL one replaced by the empty string, and the
	// dictionary they were copied from (DuckDB's id and entry array; reused while the next chunk has the same dictionary)
	std::vector<string_t> dict_ents;
	std::vector<uint8_t> dict_valid;
	std::string dict_id;
	const string_t *dict_src = nullptr;
	idx_t dict_nulls = 0;   // its NULL entries
	uint32_t dict_null = 0; // the last of them
};

// DuckDB's cells of this column ARE the column-file encoding (same width and signedness, no rescaling): handed in place.
bool InPlaceInts(const ColPlan &p) {
	if (p.role == Role::Decimal && p.mul != 1) {
		return false;
	}
	auto id = p.type.id();
	bool src_unsigned = id == LogicalTypeId::UTINYINT || id == LogicalTypeId::USMALLINT || id == LogicalTypeId::UINTEGER ||
	                    id == LogicalTypeId::UBIGINT;
	bool dst_unsigned = !p.e.rust_type.empty() && p.e.rust_type[0] == 'u';
	return GetTypeIdSize(p.type.InternalType()) == p.width && src_unsigned == dst_unsigned;
}

// One chunk column as a LemmaVec. Fixed width: in place when the vector is FLAT, already the encoding and (for a column not declared
// nullable) has no NULL; else decoded by the tested DecodeIntegers into the worker's buffer (CONSTANT / DICTIONARY / sequence vectors,
// rescaled DECIMALs; a NULL in a column not declared nullable is an error there). A nullable column's NULL cells keep whatever DuckDB
// has: S1 promises a value only where the cell is valid; its __valid column comes from the validity at the physical index.
// VARCHAR: FLAT without NULLs, or DICTIONARY of known size over a FLAT child without NULLs: DuckDB's string_t entries and selection
// in place; DICTIONARY over a FLAT child with NULL entries (every storage dictionary: entry 0 is NULL): DuckDB's selection in place,
// the entries copied once per dictionary with each NULL entry the empty string; else the entries of the chunk's rows gathered into
// the buffer (a NULL row: the empty string, its __valid says NULL).
void StreamVec(const ColPlan &p, Vector &vec, idx_t n, StreamCol &buf, LemmaVec &out) {
	out = LemmaVec {nullptr, nullptr, 0, 0};
	switch (p.role) {
	case Role::Int:
	case Role::Date:
	case Role::Decimal:
		if (vec.GetVectorType() == VectorType::FLAT_VECTOR && InPlaceInts(p) &&
		    (p.e.nullable || FlatVector::Validity(vec).AllValid())) {
			out.data = FlatVector::GetData(vec);
			return;
		}
		DecodeIntegers(p, vec, n, buf.cells.data());
		out.data = buf.cells.data();
		return;
	case Role::Valid:
	case Role::Bool: {
		UnifiedVectorFormat f;
		vec.ToUnifiedFormat(n, f);
		// the cells are read only for a BOOLEAN column; a __valid column reads the validity of its value column's vector
		const bool *bools = p.role == Role::Bool ? UnifiedVectorFormat::GetData<bool>(f) : nullptr;
		for (idx_t r = 0; r < n; r++) {
			idx_t idx = f.sel->get_index(r);
			bool valid = f.validity.RowIsValid(idx);
			if (p.role == Role::Valid) {
				buf.cells[r] = valid ? 1 : 0;
				continue;
			}
			if (!valid) {
				p.NullCell();
			}
			buf.cells[r] = valid && bools[idx] ? 1 : 0;
		}
		out.data = buf.cells.data();
		return;
	}
	case Role::String: {
		auto type = vec.GetVectorType();
		if (type == VectorType::FLAT_VECTOR && FlatVector::Validity(vec).AllValid()) {
			out.data = reinterpret_cast<const uint8_t *>(FlatVector::GetData<string_t>(vec));
			out.sel = IdentitySel();
			out.nents = n;
			return;
		}
		if (type == VectorType::DICTIONARY_VECTOR && DictionaryVector::DictionarySize(vec).IsValid() &&
		    DictionaryVector::Child(vec).GetVectorType() == VectorType::FLAT_VECTOR) {
			auto &child = DictionaryVector::Child(vec);
			auto &sel = DictionaryVector::SelVector(vec);
			const uint32_t *rows = sel.IsSet() ? sel.data() : IdentitySel(); // no selection vector: row r is entry r
			idx_t nents = DictionaryVector::DictionarySize(vec).GetIndex();
			const auto *entries = FlatVector::GetData<string_t>(child);
			auto &validity = FlatVector::Validity(child);
			const std::string &id = DictionaryVector::DictionaryId(vec);
			if (validity.AllValid()) {
				out.data = reinterpret_cast<const uint8_t *>(entries);
				out.nents = nents;
				out.sel = rows; // S1 checks sel < nents
				out.dict = DictIdOf(id);
				return;
			}
			// DuckDB's storage dictionaries (dictionary and dict_fsst compression) keep entry 0 as a NULL entry, so their child is
			// never "all valid", and a NULL entry's string_t may be uninitialized (dictionary compression never writes entry 0).
			// DuckDB's selection is handed in place with a copy of the entries in which every NULL entry is the empty string, made
			// once per dictionary: the copy is reused while the next chunk's dictionary is the same object (the same non-empty id,
			// a fresh random UUID per DictionaryVector::CreateReusableDictionary, the same entry array and size; DuckDB writes a
			// reusable dictionary's entries once, when a segment's scan creates it). A row that selects a NULL entry is a NULL cell
			// (an error unless the column is nullable; its __valid comes from the validity at the physical index).
			bool same = !id.empty() && id == buf.dict_id && entries == buf.dict_src && nents == buf.dict_ents.size();
			if (same || nents <= n) {
				if (!same) {
					buf.dict_ents.resize(nents);
					buf.dict_valid.resize(nents);
					buf.dict_nulls = 0;
					for (idx_t e = 0; e < nents; e++) {
						bool ok = validity.RowIsValid(e);
						buf.dict_valid[e] = ok ? 1 : 0;
						buf.dict_ents[e] = ok ? entries[e] : string_t(uint32_t(0)); // the empty string, inline
						if (!ok) {
							buf.dict_nulls++;
							buf.dict_null = uint32_t(e);
						}
					}
					buf.dict_id = id;
					buf.dict_src = entries;
				}
				if (!p.e.nullable) { // a nullable column may have NULL rows (its __valid says which)
					bool null_row = false;
					if (buf.dict_nulls == 1) { // the storage dictionaries: entry 0 only (a branch-free compare per row)
						uint32_t z = buf.dict_null, hit = 0;
						for (idx_t r = 0; r < n; r++) {
							hit |= uint32_t(rows[r] == z);
						}
						null_row = hit != 0;
					} else {
						const uint8_t *ok = buf.dict_valid.data();
						for (idx_t r = 0; r < n && !null_row; r++) {
							uint32_t e = rows[r];
							null_row = e < nents && !ok[e]; // an index out of range: S1's own check refuses the chunk
						}
					}
					if (null_row) {
						p.NullCell();
					}
				}
				out.data = reinterpret_cast<const uint8_t *>(buf.dict_ents.data());
				out.nents = nents;
				out.sel = rows;
				out.dict = DictIdOf(id);
				return;
			}
		}
		UnifiedVectorFormat f;
		vec.ToUnifiedFormat(n, f);
		auto data = UnifiedVectorFormat::GetData<string_t>(f);
		for (idx_t r = 0; r < n; r++) {
			idx_t idx = f.sel->get_index(r);
			if (f.validity.RowIsValid(idx)) {
				buf.ents[r] = data[idx];
			} else {
				p.NullCell();
				buf.ents[r] = string_t(uint32_t(0)); // the empty string, inline
			}
		}
		out.data = reinterpret_cast<const uint8_t *>(buf.ents.data());
		out.sel = IdentitySel();
		out.nents = n;
		return;
	}
	default:
		throw InternalException("Lemma: role %s in a stream", p.e.role);
	}
}

// The library's handles of one call: every worker is finished, merged or dropped, then the stream closed, on every path.
struct StreamHandles {
	const Executor *exec = nullptr;
	LemmaStream *stream = nullptr;
	std::vector<LemmaWorker *> workers;
	~StreamHandles() {
		for (auto w : workers) {
			if (w) {
				exec->stream_drop(w);
			}
		}
		if (stream) {
			exec->stream_close(stream);
		}
	}
};

std::string TakeOut(const Executor &exec, LemmaOut &out) {
	std::string bytes(reinterpret_cast<const char *>(out.ptr), size_t(out.len));
	exec.free_out(&out);
	return bytes;
}

// Test-only (lemma_stream_fault): a scheduling bug injected on purpose, to show the proved runtime answers ERROR, never wrong rows.
enum class StreamFault { None, Drop, Duplicate, Shift, Count };

StreamFault StreamFaultSetting(ClientContext &context) {
	Value v;
	if (!context.TryGetCurrentSetting("lemma_stream_fault", v) || v.IsNull()) {
		return StreamFault::None;
	}
	auto s = StringValue::Get(v);
	if (s.empty()) {
		return StreamFault::None;
	}
	if (s == "drop") {
		return StreamFault::Drop;
	}
	if (s == "duplicate") {
		return StreamFault::Duplicate;
	}
	if (s == "shift") {
		return StreamFault::Shift;
	}
	if (s == "count") {
		return StreamFault::Count;
	}
	throw InvalidInputException("Lemma: lemma_stream_fault '%s': '' (none), 'drop', 'duplicate', 'shift' or 'count'", s);
}

// The stream executor of `m` over its table, in the caller's transaction. scan_us: catalog + scan + steps (until every worker
// returned); the merge and exec_finish are the result's run_us (finish) and part of the caller's total.
RunResult StreamRun(ClientContext &context, const Manifest &m, const std::vector<ParamBytes> &params, int64_t &scan_us) {
	auto start = std::chrono::steady_clock::now();
	const Executor &exec = *m.exec;
	auto preps = PrepareInputs(context, m, {});
	if (preps.size() != 1) {
		throw InvalidInputException("Lemma: stream executor %s reads %d tables, a stream reads one", m.key, int64_t(preps.size()));
	}
	TablePrep &prep = preps[0];
	auto &plans = prep.plans;
	if (plans.size() + 1 != m.inputs.size()) {
		throw InternalException("Lemma: stream executor %s: %d planned columns for %d inputs", m.key, int64_t(plans.size()),
		                        int64_t(m.inputs.size()));
	}
	for (size_t i = 0; i < plans.size(); i++) {
		if (plans[i].k != i + 1 || (plans[i].width == 0) != (plans[i].role == Role::String)) {
			throw InternalException("Lemma: stream executor %s: column %d is out of layout order", m.key, int64_t(i));
		}
	}
	StreamFault fault = StreamFaultSetting(context);
	StreamHandles h;
	h.exec = &exec;
	{
		std::vector<LemmaParam> abi_params;
		for (auto &p : params) {
			abi_params.push_back(LemmaParam {p.kind, reinterpret_cast<const uint8_t *>(p.bytes.data()), uint64_t(p.bytes.size())});
		}
		LemmaOut err {nullptr, 0, 0};
		h.stream = exec.stream_open(nullptr, 0, abi_params.data(), abi_params.size(), &err);
		std::string msg = TakeOut(exec, err);
		if (!h.stream) {
			throw InvalidInputException("Lemma: the stream executor refused its parameters (no rows returned): %s", msg);
		}
	}
	// the sources, as ScanTable: the committed row groups, then this transaction's own uncommitted rows
	DataTable &storage = *prep.storage;
	DuckTransaction &transaction = *prep.transaction;
	std::vector<std::unique_ptr<ScanSource>> sources;
	auto committed = make_uniq<ScanSource>();
	committed->collection = storage.GetRowGroupCollection().get();
	committed->collection->InitializeParallelScan(committed->state);
	uint64_t upper = committed->state.max_row - committed->state.row_groups->GetBaseRowId();
	sources.push_back(std::move(committed));
	auto local_storage = LocalStorage::Get(transaction).GetStorage(storage);
	if (local_storage && local_storage->GetCollection().GetTotalRows() > 0) {
		auto local = make_uniq<ScanSource>();
		local->collection = &local_storage->GetCollection();
		local->local = true;
		local->collection->InitializeParallelScan(local->state);
		upper += local->state.max_row - local->state.row_groups->GetBaseRowId();
		sources.push_back(std::move(local));
	}
	idx_t row_group_rows = MaxValue<idx_t>(1, storage.GetRowGroupSize());
	idx_t nthreads = MaxValue<idx_t>(1, MinValue<idx_t>(ScanThreads(context), upper / row_group_rows + sources.size()));
	for (idx_t w = 0; w < nthreads; w++) {
		LemmaOut err {nullptr, 0, 0};
		LemmaWorker *worker = exec.stream_worker(h.stream, &err);
		std::string msg = TakeOut(exec, err);
		if (!worker) {
			throw InvalidInputException("Lemma: the stream executor could not start a worker (no rows returned): %s", msg);
		}
		h.workers.push_back(worker);
	}

	std::atomic<uint64_t> counter {0};
	std::atomic<bool> stop {false}, interrupted {false};
	std::mutex err_lock;
	std::exception_ptr error;
	auto run_worker = [&](idx_t w) {
		try {
			TableScanState ts;
			ts.Initialize(prep.ids, &context, nullptr);
			DataChunk chunk;
			chunk.Initialize(Allocator::Get(context), prep.types);
			std::vector<StreamCol> bufs(plans.size());
			for (size_t i = 0; i < plans.size(); i++) {
				if (plans[i].role == Role::String) {
					bufs[i].ents.resize(STANDARD_VECTOR_SIZE);
				} else {
					bufs[i].cells.resize(plans[i].width * STANDARD_VECTOR_SIZE);
				}
			}
			std::vector<LemmaVec> vecs(plans.size());
			LemmaWorker *worker = h.workers[w];
			for (auto &src : sources) {
				CollectionScanState &cs = src->local ? ts.local_state : ts.table_state;
				while (!stop.load(std::memory_order_relaxed) && src->collection->NextParallelScan(context, src->state, cs)) {
					while (!stop.load(std::memory_order_relaxed)) {
						if (context.interrupted) {
							interrupted = true;
							stop = true;
							break;
						}
						chunk.Reset();
						if (!cs.Scan(transaction, chunk) || chunk.size() == 0) {
							break;
						}
						idx_t n = chunk.size();
						for (size_t i = 0; i < plans.size(); i++) {
							StreamVec(plans[i], chunk.data[plans[i].chunk_col], n, bufs[i], vecs[i]);
						}
						// (j, off): ONE fetch_add hands the chunk its index and its first row (S1's offset of these rows in the stream)
						uint64_t packed = counter.fetch_add((uint64_t(1) << STREAM_OFF_BITS) | uint64_t(n));
						uint64_t j = packed >> STREAM_OFF_BITS, off = packed & STREAM_OFF_MASK;
						if (off + n > STREAM_OFF_MASK || j + 1 >= (uint64_t(1) << (64 - STREAM_OFF_BITS))) {
							throw InvalidInputException("Lemma: a stream of more than 2^36 rows or 2^28 chunks");
						}
						LemmaChunk c {j, off, uint64_t(n), uint64_t(vecs.size()), vecs.data()};
						int32_t st;
						if (fault == StreamFault::Drop && j == 1) {
							st = LEMMA_STEP_OK; // a lost chunk
						} else if (fault == StreamFault::Duplicate && j == 1) {
							st = exec.stream_step(worker, &c);
							if (st == LEMMA_STEP_OK) {
								st = exec.stream_step(worker, &c); // the same chunk twice
							}
						} else {
							if (fault == StreamFault::Shift && j == 1) {
								c.off += 1; // a chunk handed at the wrong offset
							}
							st = exec.stream_step(worker, &c);
						}
						if (st != LEMMA_STEP_OK) {
							stop = true; // declined or refused: the answer is a decline or an error whatever the other chunks hold
						}
					}
				}
			}
		} catch (...) {
			std::lock_guard<std::mutex> guard(err_lock);
			if (!error) {
				error = std::current_exception();
			}
			stop = true;
		}
	};
	{
		std::vector<std::thread> pool;
		for (idx_t i = 1; i < nthreads; i++) {
			pool.emplace_back(run_worker, i);
		}
		run_worker(0);
		for (auto &t : pool) {
			t.join();
		}
	}
	if (error) {
		std::rethrow_exception(error);
	}
	if (interrupted) {
		throw InterruptException();
	}
	scan_us = MicrosSince(start);
	// pairwise merge, each round on its own threads: worker 2i takes worker 2i + 1 (consumed)
	while (h.workers.size() > 1) {
		size_t pairs = h.workers.size() / 2;
		std::vector<std::thread> pool;
		for (size_t i = 0; i < pairs; i++) {
			pool.emplace_back([&, i]() { exec.stream_merge(h.workers[2 * i], h.workers[2 * i + 1]); });
		}
		for (auto &t : pool) {
			t.join();
		}
		std::vector<LemmaWorker *> next;
		for (size_t i = 0; i < h.workers.size(); i += 2) {
			next.push_back(h.workers[i]); // the merge status is the finish's to report (a merged-in error stays an error)
		}
		h.workers = std::move(next);
	}
	uint64_t total = counter.load();
	uint64_t m_chunks = total >> STREAM_OFF_BITS, n_rows = total & STREAM_OFF_MASK;
	if (fault == StreamFault::Count) {
		n_rows += 1; // a wrong row count for S2
	}
	LemmaWorker *last = h.workers[0];
	h.workers.clear(); // finish consumes it
	LemmaOut out {nullptr, 0, 0};
	int32_t code = exec.stream_finish(last, m_chunks, n_rows, &out);
	std::string bytes = TakeOut(exec, out);
	if (code == LEMMA_STATUS_ERROR) {
		throw InvalidInputException("Lemma: the proved stream executor refused to answer (ERROR, no rows returned): %s", bytes);
	}
	RunResult r = ParseRun(m, code, std::move(bytes));
	r.mode = "stream";
	r.chunks = int64_t(m_chunks);
	r.threads = int64_t(nthreads);
	return r;
}

template <class T>
void PutRange(Vector &vec, idx_t i, i128 v, i128 lo, i128 hi, const OutCol &c) {
	if (v < lo || v > hi) {
		throw InvalidInputException("Lemma: result value %s does not fit %s (%s)", I128String(v), c.duck_type, c.name);
	}
	FlatVector::GetData<T>(vec)[i] = T(v);
}

void WriteCell(Vector &vec, idx_t out_i, const OutCol &c, const ResultColumn &rc, const std::string &b, uint64_t row) {
	if (!rc.valid[row]) {
		FlatVector::SetNull(vec, out_i, true);
		return;
	}
	if (rc.kind == KIND_STR) {
		size_t off = rc.str_off[row];
		uint32_t len = Read<uint32_t>(b, off);
		FlatVector::GetData<string_t>(vec)[out_i] = StringVector::AddString(vec, b.data() + off + 4, len);
		return;
	}
	if (rc.kind == KIND_F64) {
		double d;
		std::memcpy(&d, rc.cells + 8 * row, 8);
		if (c.type.id() == LogicalTypeId::FLOAT) {
			FlatVector::GetData<float>(vec)[out_i] = float(d);
		} else {
			FlatVector::GetData<double>(vec)[out_i] = d;
		}
		return;
	}
	if (rc.kind == KIND_BOOL) {
		FlatVector::GetData<bool>(vec)[out_i] = rc.cells[row] != 0;
		return;
	}
	i128 v;
	std::memcpy(&v, rc.cells + 16 * row, 16);
	const i128 i128_max = ~(i128(1) << 127);
	switch (c.type.id()) {
	case LogicalTypeId::TINYINT:
		return PutRange<int8_t>(vec, out_i, v, INT8_MIN, INT8_MAX, c);
	case LogicalTypeId::SMALLINT:
		return PutRange<int16_t>(vec, out_i, v, INT16_MIN, INT16_MAX, c);
	case LogicalTypeId::INTEGER:
		return PutRange<int32_t>(vec, out_i, v, INT32_MIN, INT32_MAX, c);
	case LogicalTypeId::BIGINT:
		return PutRange<int64_t>(vec, out_i, v, INT64_MIN, INT64_MAX, c);
	case LogicalTypeId::UTINYINT:
		return PutRange<uint8_t>(vec, out_i, v, 0, UINT8_MAX, c);
	case LogicalTypeId::USMALLINT:
		return PutRange<uint16_t>(vec, out_i, v, 0, UINT16_MAX, c);
	case LogicalTypeId::UINTEGER:
		return PutRange<uint32_t>(vec, out_i, v, 0, UINT32_MAX, c);
	case LogicalTypeId::UBIGINT:
		return PutRange<uint64_t>(vec, out_i, v, 0, UINT64_MAX, c);
	case LogicalTypeId::DATE: {
		if (v < INT32_MIN || v > INT32_MAX) {
			throw InvalidInputException("Lemma: result day %s is not a DATE (%s)", I128String(v), c.name);
		}
		FlatVector::GetData<date_t>(vec)[out_i] = date_t(int32_t(v));
		return;
	}
	case LogicalTypeId::HUGEINT: {
		hugeint_t h;
		h.lower = uint64_t(v);
		h.upper = int64_t(v >> 64);
		FlatVector::GetData<hugeint_t>(vec)[out_i] = h;
		return;
	}
	case LogicalTypeId::UHUGEINT: {
		if (v < 0) {
			throw InvalidInputException("Lemma: result value %s does not fit UHUGEINT (%s)", I128String(v), c.name);
		}
		uhugeint_t h;
		h.lower = uint64_t(v);
		h.upper = uint64_t(v >> 64);
		FlatVector::GetData<uhugeint_t>(vec)[out_i] = h;
		return;
	}
	case LogicalTypeId::DECIMAL: {
		int width = DecimalType::GetWidth(c.type);
		i128 bound = width >= 38 ? i128_max : Pow10(width) - 1;
		if (v < -bound || v > bound) {
			throw InvalidInputException("Lemma: result value %s does not fit %s (%s)", I128String(v), c.duck_type, c.name);
		}
		switch (c.type.InternalType()) {
		case PhysicalType::INT16:
			FlatVector::GetData<int16_t>(vec)[out_i] = int16_t(v);
			return;
		case PhysicalType::INT32:
			FlatVector::GetData<int32_t>(vec)[out_i] = int32_t(v);
			return;
		case PhysicalType::INT64:
			FlatVector::GetData<int64_t>(vec)[out_i] = int64_t(v);
			return;
		default: {
			hugeint_t h;
			h.lower = uint64_t(v);
			h.upper = int64_t(v >> 64);
			FlatVector::GetData<hugeint_t>(vec)[out_i] = h;
			return;
		}
		}
	}
	default:
		throw InvalidInputException("Lemma: cannot return an integer as %s (%s)", c.duck_type, c.name);
	}
}

// ---------------------------------------------------------------- query templates: matching a query's literals to a stored template
//
// A template executor (`-- params:` header, `$name` placeholders; lifted automatically by `lemma generate` or written by hand) is
// listed in ${lemma_home}/templates/<sha256 of its skeleton>/<executor key> (research_loop/in_duckdb.py index_template). A query
// without an exact executor is looked up there by ITS skeleton (lemma::TemplateSkeleton: every literal token and placeholder is `?`),
// and matches a candidate only if its normalized text equals the template body (normalized, `$` kept) with each placeholder replaced
// by one literal token of the parameter's kind, character for character (lemma::MatchTemplate), and every bound value fits the
// parameter's type and the range run_query requires. So the query IS the template's text instantiated with its own literals: the
// executor's proof (for every parameter value in that range) covers it.

// The query as an executor answers it: the manifest, the values lemma_query would take, and the SQL DuckDB answers a routed decline with.
struct Resolved {
	std::unique_ptr<Manifest> manifest;
	vector<Value> inputs; // [the executor's SQL text, parameter values...]
	std::string sql;      // the caller's SQL
	bool via_template = false;
	std::string duck_sql; // for a template match: the caller's text (it is the template with these values); else empty
};

lemma::LiteralKind ParamLiteralKind(const ParamSpec &p) {
	if (p.sql_type == "VARCHAR") {
		return lemma::LiteralKind::String;
	}
	if (p.sql_type == "DATE") {
		return lemma::LiteralKind::Date;
	}
	return lemma::LiteralKind::Number;
}

// The value of a bound literal for parameter `p`, or false when it does not fit the parameter's type or the range run_query requires
// (no match: a different executor is needed). Exact: a DECIMAL literal with more fractional digits than the scale never matches.
bool LiteralValue(const ParamSpec &p, const std::string &text, Value &out) {
	if (p.sql_type == "VARCHAR") {
		std::string inner;
		for (size_t i = 1; i + 1 < text.size(); i++) {
			inner += text[i];
			if (text[i] == '\'') {
				i++; // '' is one quote
			}
		}
		out = Value(inner);
		return true;
	}
	if (p.sql_type == "DATE") {
		size_t q = text.find('\'');
		std::string day = text.substr(q + 1, text.size() - q - 2);
		static const std::regex iso("^[0-9]{4}-[0-9]{2}-[0-9]{2}$");
		if (!std::regex_match(day, iso)) {
			return false;
		}
		date_t d;
		idx_t pos = 0;
		bool special = false;
		if (Date::TryConvertDate(day.c_str(), day.size(), pos, d, special, true) != DateCastResult::SUCCESS || special) {
			return false;
		}
		if (p.has_range && (int64_t(d.days) < p.lo || int64_t(d.days) > p.hi)) {
			return false;
		}
		out = Value::DATE(d);
		return true;
	}
	int scale = p.sql_type == "BIGINT" ? 0 : p.scale;
	if (p.sql_type != "BIGINT" && p.sql_type.rfind("DECIMAL(", 0) != 0) {
		return false;
	}
	size_t dot = text.find('.');
	std::string whole = text.substr(0, dot);
	std::string frac = dot == std::string::npos ? "" : text.substr(dot + 1);
	if (int(frac.size()) > scale) {
		return false;
	}
	std::string digits = whole + frac + std::string(size_t(scale) - frac.size(), '0');
	i128 scaled = 0;
	for (char c : digits) {
		scaled = scaled * 10 + (c - '0');
		if (scaled > i128(INT64_MAX)) {
			return false;
		}
	}
	int64_t v = int64_t(scaled);
	if (p.has_range && (v < p.lo || v > p.hi)) {
		return false;
	}
	out = scale == 0 && p.sql_type == "BIGINT" ? Value::BIGINT(v) : Value::DECIMAL(v, 18, uint8_t(scale));
	return true;
}

// The template text without its `-- params:` header line (templates.parse_template: the line's text goes, its newline stays).
std::string TemplateBody(const std::string &sql) {
	size_t start = 0;
	while (start <= sql.size()) {
		size_t end = sql.find('\n', start);
		if (end == std::string::npos) {
			end = sql.size();
		}
		size_t i = start;
		while (i < end && (sql[i] == ' ' || sql[i] == '\t')) {
			i++;
		}
		if (sql.compare(i, 2, "--") == 0) {
			i += 2;
			while (i < end && (sql[i] == ' ' || sql[i] == '\t')) {
				i++;
			}
			if (end - i >= 6 && StringUtil::CIEquals(sql.substr(i, 6), "params")) {
				i += 6;
				while (i < end && (sql[i] == ' ' || sql[i] == '\t')) {
					i++;
				}
				if (i < end && sql[i] == ':') {
					return sql.substr(0, start) + sql.substr(end);
				}
			}
		}
		start = end + 1;
	}
	return sql;
}

// The installed executors listed under `skeleton_key`, sorted (deterministic).
std::vector<std::string> IndexEntries(const std::string &home, const std::string &skeleton_key) {
	std::vector<std::string> out;
	std::string dir = home + "/templates/" + skeleton_key;
	DIR *d = opendir(dir.c_str());
	if (!d) {
		return out;
	}
	while (auto *e = readdir(d)) {
		std::string name = e->d_name;
		if (name.size() == 64 && name.find_first_not_of("0123456789abcdef") == std::string::npos) {
			out.push_back(name);
		}
	}
	closedir(d);
	std::sort(out.begin(), out.end());
	return out;
}

// A stored template whose instance is exactly `sql`, or nullptr. A present but broken or refused executor is an error, as for an exact
// key; a stale index entry (its executor removed) is skipped.
std::unique_ptr<Resolved> MatchStoredTemplate(ClientContext &context, const std::string &sql) {
	std::string normalized = lemma::NormalizeSql(sql);
	if (normalized != lemma::NormalizeSql(sql, true)) {
		return nullptr; // a `$` outside quotes (a prepared parameter, dollar quoting): never a template instance
	}
	std::string home = HomeSetting(context);
	for (auto &key : IndexEntries(home, lemma::Sha256Hex(lemma::TemplateSkeleton(normalized)))) {
		std::string dir = home + "/executors/" + key;
		if (!FileExists(dir + "/manifest.json")) {
			continue;
		}
		auto m = LoadExecutor(dir, key, nullptr);
		if (m->params.empty()) {
			continue;
		}
		std::map<std::string, lemma::LiteralKind> kinds;
		for (auto &p : m->params) {
			kinds[p.name] = ParamLiteralKind(p);
		}
		std::map<std::string, std::string> bound;
		if (!lemma::MatchTemplate(lemma::NormalizeSql(TemplateBody(m->sql), true), normalized, kinds, bound)) {
			continue;
		}
		auto r = make_uniq<Resolved>();
		r->inputs.push_back(Value(m->sql));
		bool fits = true;
		for (auto &p : m->params) {
			Value v;
			if (bound.find(p.name) == bound.end() || !LiteralValue(p, bound[p.name], v)) {
				fits = false;
				break;
			}
			r->inputs.push_back(v);
		}
		if (!fits) {
			continue;
		}
		r->manifest = std::move(m);
		r->sql = sql;
		r->via_template = true;
		r->duck_sql = sql;
		return r;
	}
	return nullptr;
}

// Exact key first (the caller's own values follow the SQL for a template text), then a stored template (no values may follow).
std::unique_ptr<Resolved> Resolve(ClientContext &context, const vector<Value> &inputs) {
	auto sql = StringValue::Get(inputs[0]);
	auto m = FindExecutor(context, sql);
	if (m) {
		auto r = make_uniq<Resolved>();
		r->manifest = std::move(m);
		r->inputs = inputs;
		r->sql = sql;
		return r;
	}
	if (inputs.size() != 1) {
		return nullptr;
	}
	return MatchStoredTemplate(context, sql);
}

// ---------------------------------------------------------------- per-executor use (lemma_list)

struct Usage {
	int64_t runs = 0, cache_hits = 0;
	std::chrono::steady_clock::time_point touched;
	bool ever_touched = false;
};
std::mutex usage_lock;
std::unordered_map<std::string, Usage> usage; // by executor directory, since LOAD (this process)

// Count a run and keep ${dir}/last_used's mtime at the last use (written at most every 10 s per executor and process).
void RecordUse(const Manifest &m, const std::string &cache) {
	bool touch = false;
	{
		std::lock_guard<std::mutex> guard(usage_lock);
		auto &u = usage[m.dir];
		u.runs++;
		if (cache == "hit") {
			u.cache_hits++;
		}
		auto now = std::chrono::steady_clock::now();
		if (!u.ever_touched || now - u.touched > std::chrono::seconds(10)) {
			u.touched = now;
			u.ever_touched = true;
			touch = true;
		}
	}
	if (touch) {
		std::string path = m.dir + "/last_used";
		std::ofstream(path, std::ios::app).flush(); // creates it; utimes sets the time (never fails a query)
		utimes(path.c_str(), nullptr);
	}
}

std::string IsoTime(time_t t) {
	char buf[32];
	struct tm tmv;
	gmtime_r(&t, &tmv);
	strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &tmv);
	return buf;
}

std::string MtimeIso(const std::string &path) {
	struct stat st;
	return stat(path.c_str(), &st) == 0 ? IsoTime(st.st_mtime) : std::string();
}

int64_t FileSize(const std::string &path) {
	struct stat st;
	return stat(path.c_str(), &st) == 0 ? int64_t(st.st_size) : -1;
}

std::string JsonQuote(const std::string &s) {
	std::string out = "\"";
	for (unsigned char c : s) {
		if (c == '"' || c == '\\') {
			out += '\\';
			out += char(c);
		} else if (c < 0x20) {
			char buf[8];
			snprintf(buf, sizeof(buf), "\\u%04x", c);
			out += buf;
		} else {
			out += char(c);
		}
	}
	return out + "\"";
}

void WriteFileAtomic(const std::string &path, const std::string &text) {
	std::string part = path + ".part" + std::to_string(getpid());
	{
		std::ofstream out(part, std::ios::binary);
		out << text;
		if (!out) {
			throw IOException("Lemma: cannot write %s", part);
		}
	}
	if (std::rename(part.c_str(), path.c_str()) != 0) {
		throw IOException("Lemma: cannot write %s", path);
	}
}

int RemoveEntry(const char *path, const struct stat *, int, struct FTW *) {
	return ::remove(path);
}

void RemoveTree(const std::string &path) {
	if (nftw(path.c_str(), RemoveEntry, 16, FTW_DEPTH | FTW_PHYS) != 0 && errno != ENOENT) {
		throw IOException("Lemma: cannot remove %s", path);
	}
}

// ---------------------------------------------------------------- generation: lemma(...) for a query without an executor
//
// The pipeline (sandboxed agent, Verus, compile, install: `lemma generate`, lemma_cli/generate.py) is a separate process. It cannot open
// the caller's database file (DuckDB holds its lock), so the extension first writes a SNAPSHOT: every table the query reads, all its
// columns, as this transaction sees them (its own uncommitted rows included), into a fresh DuckDB file in the job directory. The proof
// does not depend on the data (assumptions = false: no data assumption); the snapshot gives the pipeline the schema, the profile and
// the timing data. The job runs detached (its own session), writes `log`, and `exit_code` when it ends; the snapshot is deleted then.
//
//   ${lemma_home}/jobs/<id>/job.json      what was asked (query, key, mode, regenerate, snapshot size, generator command, ...)
//                          /query.sql     the caller's SQL
//                          /snapshot.duckdb   while the job runs
//                          /log           the generator's stdout + stderr
//                          /pgid          the job's process group (written once it started)
//                          /exit_code     when it ended (0: an executor was installed)
//                          /cancelled     Ctrl-C of a blocking lemma(...) (the process group got SIGTERM)

std::string Setting(ClientContext &context, const char *name) {
	Value v;
	if (!context.TryGetCurrentSetting(name, v) || v.IsNull()) {
		throw InvalidInputException("Lemma: %s is not set", std::string(name));
	}
	return v.ToString();
}

// The generator command of each database (read from $LEMMA_GENERATOR at LOAD, else `lemma generate`).
std::mutex generator_lock;
std::unordered_map<DatabaseInstance *, std::string> generators;

std::string GeneratorCommand(ClientContext &context) {
	std::lock_guard<std::mutex> guard(generator_lock);
	auto it = generators.find(&DatabaseInstance::GetDatabase(context));
	if (it == generators.end()) {
		throw InternalException("Lemma: no generator command recorded for this database");
	}
	return it->second;
}

// Removes the containers a job's pipeline started (label lemma.job=<id>, research_loop/job_label.py); its output goes to the job's log.
const char *DOCKER_CLEANUP = "command -v docker >/dev/null 2>&1 && { ids=$(docker ps -aq --filter \"label=lemma.job=$LEMMA_JOB_ID\"); "
                             "[ -z \"$ids\" ] || docker rm -f $ids; }";

// The job's environment: this process's, with LEMMA_HOME = lemma_home and LEMMA_JOB_ID = the job.
std::vector<std::string> JobEnvironment(const std::string &home, const std::string &id) {
	std::vector<std::string> env_text;
	for (char **e = environ; *e; e++) {
		if (std::strncmp(*e, "LEMMA_HOME=", 11) != 0 && std::strncmp(*e, "LEMMA_JOB_ID=", 13) != 0) {
			env_text.emplace_back(*e);
		}
	}
	env_text.push_back("LEMMA_HOME=" + home);
	env_text.push_back("LEMMA_JOB_ID=" + id);
	return env_text;
}

pid_t SpawnShell(const std::vector<std::string> &args, const std::vector<std::string> &env_text, bool new_session) {
	std::vector<char *> argv, envp;
	for (auto &a : args) {
		argv.push_back(const_cast<char *>(a.c_str()));
	}
	argv.push_back(nullptr);
	for (auto &e : env_text) {
		envp.push_back(const_cast<char *>(e.c_str()));
	}
	envp.push_back(nullptr);
	posix_spawnattr_t attr;
	posix_spawnattr_init(&attr);
	if (new_session) {
		posix_spawnattr_setflags(&attr, POSIX_SPAWN_SETSID);
	}
	pid_t pid;
	int err = posix_spawn(&pid, "/bin/sh", nullptr, &attr, argv.data(), envp.data());
	posix_spawnattr_destroy(&attr);
	if (err != 0) {
		throw IOException("Lemma: cannot start /bin/sh: %s", std::string(strerror(err)));
	}
	return pid;
}

// Remove the job's containers now (a cancelled job's runner was killed before it could): at most 60 s.
void CleanupJobContainers(const std::string &home, const std::string &id) {
	std::string dir = home + "/jobs/" + id;
	pid_t pid = SpawnShell({"/bin/sh", "-c", std::string("(") + DOCKER_CLEANUP + ") >>\"$1/log\" 2>&1", "lemma-cleanup", dir},
	                       JobEnvironment(home, id), false);
	int status = 0;
	for (int i = 0; i < 600; i++) {
		if (waitpid(pid, &status, WNOHANG) == pid) {
			return;
		}
		std::this_thread::sleep_for(std::chrono::milliseconds(100));
	}
	kill(pid, SIGKILL);
	waitpid(pid, &status, 0);
}

std::string GenerateMode(ClientContext &context) {
	auto mode = StringUtil::Lower(Setting(context, "lemma_generate"));
	if (mode != "block" && mode != "background" && mode != "off") {
		throw InvalidInputException("Lemma: lemma_generate is '%s'; it takes 'block', 'background' or 'off'", mode);
	}
	return mode;
}

std::string Trimmed(std::string s) {
	StringUtil::Trim(s);
	return s;
}

std::string ReadSmall(const std::string &path) {
	std::ifstream in(path, std::ios::binary);
	std::ostringstream ss;
	ss << in.rdbuf();
	return ss.str();
}

struct JobView {
	std::string id, dir, status, key, sql, mode, created, finished, log, error, installed;
	bool regenerate = false;
	int64_t exit_code = -1, snapshot_bytes = -1, pgid = 0;
};

bool GroupAlive(int64_t pgid) {
	return pgid > 0 && (kill(-pid_t(pgid), 0) == 0 || errno == EPERM);
}

// The last non-empty line of the log that starts with `prefix` ("" = any), at most 600 bytes of it.
std::string LastLogLine(const std::string &log, const std::string &prefix) {
	std::string text = ReadSmall(log);
	std::string found;
	size_t start = 0;
	while (start < text.size()) {
		size_t end = text.find('\n', start);
		if (end == std::string::npos) {
			end = text.size();
		}
		std::string line = text.substr(start, end - start);
		if (!Trimmed(line).empty() && line.compare(0, prefix.size(), prefix) == 0) {
			found = line;
		}
		start = end + 1;
	}
	return found.size() > 600 ? found.substr(found.size() - 600) : found;
}

// `details`: also read the log (installed key, error line); the status alone does not need it.
JobView ReadJob(const std::string &dir, const std::string &id, bool details = true) {
	JobView j;
	j.id = id;
	j.dir = dir;
	j.log = dir + "/log";
	auto doc = lemma::ParseJson(ReadFile(dir + "/job.json"));
	j.key = doc.At("key").Str();
	j.sql = doc.At("sql").Str();
	j.mode = doc.At("mode").Str();
	j.created = doc.At("created").Str();
	j.regenerate = doc.At("regenerate").Bool();
	j.snapshot_bytes = doc.At("snapshot_bytes").Int();
	std::string pg = Trimmed(ReadSmall(dir + "/pgid")), code = Trimmed(ReadSmall(dir + "/exit_code"));
	j.pgid = pg.empty() ? 0 : std::stoll(pg);
	if (!code.empty()) {
		j.exit_code = std::stoll(code);
		j.finished = MtimeIso(dir + "/exit_code");
	}
	if (FileExists(dir + "/cancelled")) {
		j.status = "cancelled";
		j.finished = MtimeIso(dir + "/cancelled");
	} else if (!code.empty()) {
		j.status = j.exit_code == 0 ? "done" : "failed";
	} else if (j.pgid == 0) {
		j.status = "starting";
	} else if (GroupAlive(j.pgid)) {
		j.status = "running";
	} else if (FileExists(dir + "/exit_code")) {
		return ReadJob(dir, id, details); // it ended between the two reads
	} else {
		j.status = "lost"; // its processes are gone without an exit code (killed, or the machine restarted)
	}
	if (!details) {
		return j;
	}
	j.installed = LastLogLine(j.log, "INSTALLED ");
	if (!j.installed.empty()) {
		j.installed = Trimmed(j.installed.substr(10));
		j.installed = j.installed.substr(0, j.installed.find(' '));
	}
	if (j.status == "failed" || j.status == "lost") {
		j.error = LastLogLine(j.log, "");
	}
	return j;
}

std::vector<JobView> ListJobs(const std::string &home, bool details = true) {
	std::vector<JobView> out;
	std::string root = home + "/jobs";
	DIR *d = opendir(root.c_str());
	if (!d) {
		return out;
	}
	std::vector<std::string> ids;
	while (auto *e = readdir(d)) {
		std::string name = e->d_name;
		if (name[0] != '.' && FileExists(root + "/" + name + "/job.json")) {
			ids.push_back(name);
		}
	}
	closedir(d);
	std::sort(ids.begin(), ids.end());
	for (auto &id : ids) {
		out.push_back(ReadJob(root + "/" + id, id, details));
	}
	return out;
}

// The base tables `sql` reads, bound in the caller's context (a query that does not bind is an error before anything starts).
std::vector<TableCatalogEntry *> TablesRead(ClientContext &context, const std::string &sql) {
	Parser parser(context.GetParserOptions());
	parser.ParseQuery(sql);
	if (parser.statements.size() != 1 || parser.statements[0]->type != StatementType::SELECT_STATEMENT) {
		throw InvalidInputException("Lemma: lemma() takes one SELECT statement");
	}
	auto binder = Binder::CreateBinder(context);
	auto bound = binder->Bind(*parser.statements[0]);
	std::vector<TableCatalogEntry *> out;
	std::function<void(LogicalOperator &)> walk = [&](LogicalOperator &op) {
		if (op.type == LogicalOperatorType::LOGICAL_GET) {
			auto table = op.Cast<LogicalGet>().GetTable();
			if (table && std::find(out.begin(), out.end(), table.get()) == out.end()) {
				out.push_back(table.get());
			}
		}
		for (auto &child : op.children) {
			walk(*child);
		}
	};
	walk(*bound.plan);
	if (out.empty()) {
		throw InvalidInputException("Lemma: the query reads no table; there is nothing to generate an executor for");
	}
	return out;
}

// Every table in `tables`, all its columns, as the caller's transaction sees them (committed rows of its snapshot and its own
// uncommitted ones), into a new DuckDB file at `path` (same schema names, table names and CREATE TABLE text). Returns the rows.
int64_t ExportSnapshot(ClientContext &context, const std::vector<TableCatalogEntry *> &tables, const std::string &path) {
	DBConfig config;
	DuckDB db(path, &config);
	Connection con(db);
	int64_t rows = 0;
	for (auto *entry : tables) {
		if (!entry->IsDuckTable()) {
			throw InvalidInputException("Lemma: %s is not a DuckDB table; the generator's snapshot can only copy DuckDB tables", entry->name);
		}
		for (auto &col : entry->GetColumns().Logical()) {
			if (col.Generated()) {
				throw InvalidInputException("Lemma: %s.%s is a generated column; the generator's snapshot cannot copy it", entry->name,
				                            col.Name());
			}
		}
		if (entry->schema.name != DEFAULT_SCHEMA) {
			auto r = con.Query("CREATE SCHEMA IF NOT EXISTS " + KeywordHelper::WriteQuoted(entry->schema.name, '"'));
			if (r->HasError()) {
				throw InvalidInputException("Lemma: snapshot: %s", r->GetError());
			}
		}
		// The table's own CREATE TABLE (columns, types, defaults, constraints), without the caller's catalog name.
		auto info = entry->GetInfo();
		info->catalog.clear();
		auto created = con.Query(info->ToString());
		if (created->HasError()) {
			throw InvalidInputException("Lemma: snapshot of %s: %s", entry->name, created->GetError());
		}
		auto &storage = entry->GetStorage();
		auto &transaction = DuckTransaction::Get(context, entry->ParentCatalog());
		vector<StorageIndex> ids;
		vector<LogicalType> types;
		for (auto &col : entry->GetColumns().Physical()) {
			ids.emplace_back(col.StorageOid());
			types.push_back(col.Type());
		}
		TableScanState state;
		storage.InitializeScan(context, transaction, state, ids);
		DataChunk chunk;
		chunk.Initialize(Allocator::Get(context), types);
		Appender appender(con, entry->schema.name, entry->name);
		while (true) {
			chunk.Reset();
			storage.Scan(transaction, chunk, state);
			if (chunk.size() == 0) {
				break;
			}
			rows += int64_t(chunk.size());
			appender.AppendDataChunk(chunk);
		}
		appender.Close();
	}
	auto done = con.Query("CHECKPOINT");
	if (done->HasError()) {
		throw InvalidInputException("Lemma: snapshot: %s", done->GetError());
	}
	return rows;
}

std::atomic<uint64_t> job_counter {0};

// Start the generator for `sql` as a detached job (its own session and process group); returns the job id.
std::string StartJob(ClientContext &context, const std::string &sql, bool regenerate, const std::string &mode) {
	Value external;
	if (context.TryGetCurrentSetting("enable_external_access", external) && !external.IsNull() && !BooleanValue::Get(external)) {
		throw PermissionException("Lemma: generating an executor runs the generator command and writes a snapshot file, and "
		                          "enable_external_access is false");
	}
	std::string home = HomeSetting(context);
	if (home.empty() || home[0] != '/') { // the job runs in its own directory: every path it gets is absolute
		char cwd[4096];
		if (!getcwd(cwd, sizeof(cwd))) {
			throw IOException("Lemma: cannot resolve lemma_home %s", home);
		}
		home = std::string(cwd) + "/" + home;
	}
	std::string generator = GeneratorCommand(context);
	if (Trimmed(generator).empty()) {
		throw InvalidInputException("Lemma: the generator command ($LEMMA_GENERATOR at LOAD) is empty");
	}
	auto tables = TablesRead(context, sql);
	std::string key = lemma::Sha256Hex(lemma::NormalizeSql(sql));
	std::string id = IsoTime(time(nullptr)) + "-" + key.substr(0, 12) + "-" + std::to_string(getpid()) + "-" +
	                 std::to_string(job_counter++);
	for (auto &c : id) {
		if (c == ':') {
			c = '-';
		}
	}
	std::string dir = home + "/jobs/" + id;
	MakeDirs(dir);
	WriteFileAtomic(dir + "/query.sql", sql + "\n");
	auto start = std::chrono::steady_clock::now();
	std::string snapshot = dir + "/snapshot.duckdb";
	int64_t rows;
	try {
		rows = ExportSnapshot(context, tables, snapshot);
	} catch (...) {
		RemoveTree(dir); // nothing started: no job
		throw;
	}
	int64_t export_us = MicrosSince(start);
	int64_t bytes = FileSize(snapshot);
	std::string source = tables[0]->ParentCatalog().GetAttached().GetStorageManager().GetDBPath();
	std::string names;
	for (auto *t : tables) {
		names += (names.empty() ? "" : ", ") + JsonQuote(t->schema.name + "." + t->name);
	}
	bool lift = BoolSetting(context, "lemma_lift_constants");
	WriteFileAtomic(dir + "/job.json",
	                "{\n \"id\": " + JsonQuote(id) + ",\n \"key\": " + JsonQuote(key) + ",\n \"sql\": " + JsonQuote(sql) +
	                    ",\n \"mode\": " + JsonQuote(mode) + ",\n \"regenerate\": " + (regenerate ? "true" : "false") +
	                    ",\n \"lift_constants\": " + (lift ? "true" : "false") + ",\n \"created\": " + JsonQuote(IsoTime(time(nullptr))) +
	                    ",\n \"source_db\": " + JsonQuote(source) + ",\n \"tables\": [" + names + "],\n \"snapshot_rows\": " +
	                    std::to_string(rows) + ",\n \"snapshot_bytes\": " + std::to_string(bytes) + ",\n \"export_us\": " +
	                    std::to_string(export_us) + ",\n \"generator\": " + JsonQuote(generator) + "\n}\n");
	// /bin/sh -c SCRIPT lemma-generate <dir> <args...>: the generator runs in a background subshell of a new session (so a Ctrl-C of
	// the caller's terminal does not reach it, and its whole process group can be signalled), output to `log`; then the snapshot is
	// deleted and exit_code written. The launching shell exits at once (no zombie is left to this process).
	// When the generator ends (or dies), the containers its pipeline left with the job's label are removed.
	std::string script = "cd \"$1\" || exit 97; shift; (" + generator + " \"$@\" >>log 2>&1; c=$?; (" + DOCKER_CLEANUP +
	                     ") >>log 2>&1; rm -f snapshot.duckdb snapshot.duckdb.wal; echo $c >exit_code.part; "
	                     "mv exit_code.part exit_code) </dev/null >/dev/null 2>&1 &";
	std::vector<std::string> args = {"/bin/sh", "-c", script, "lemma-generate", dir, "--db", snapshot, "--sql-file",
	                                 dir + "/query.sql", "--source-db", source, lift ? "--lift-constants" : "--no-lift-constants"};
	if (regenerate) {
		args.push_back("--regenerate");
	}
	pid_t pid = SpawnShell(args, JobEnvironment(home, id), true);
	int status = 0;
	waitpid(pid, &status, 0); // the launcher only backgrounds the job
	WriteFileAtomic(dir + "/pgid", std::to_string(pid) + "\n");
	if (!WIFEXITED(status) || WEXITSTATUS(status) != 0) {
		throw IOException("Lemma: the generator launcher failed (job %s)", dir);
	}
	return id;
}

// A job for this exact query that is still running (its id), or "".
std::string RunningJob(const std::string &home, const std::string &key) {
	for (auto &j : ListJobs(home, false)) {
		if (j.key == key && (j.status == "running" || j.status == "starting")) {
			return j.id;
		}
	}
	return "";
}

// lemma_generate = 'block': wait for the job, copying its log to stderr; Ctrl-C (an interrupted query) cancels it: SIGTERM to its
// process group, SIGKILL 5 s later. Returns the job as it ended.
JobView WaitJob(ClientContext &context, const std::string &home, const std::string &id) {
	std::string dir = home + "/jobs/" + id;
	std::ifstream log;
	std::string pending;
	auto pump = [&]() {
		if (!log.is_open()) {
			log.open(dir + "/log", std::ios::binary);
			if (!log.is_open()) {
				return;
			}
		}
		log.clear();
		char buf[4096];
		while (log.read(buf, sizeof(buf)) || log.gcount() > 0) {
			pending.append(buf, size_t(log.gcount()));
			if (log.eof()) {
				break;
			}
		}
		log.clear();
		size_t nl;
		while ((nl = pending.find('\n')) != std::string::npos) {
			fprintf(stderr, "[lemma generate] %s\n", pending.substr(0, nl).c_str());
			pending.erase(0, nl + 1);
		}
		fflush(stderr);
	};
	fprintf(stderr, "[lemma generate] job %s started (log %s/log); Ctrl-C cancels it\n", id.c_str(), dir.c_str());
	while (true) {
		pump();
		auto job = ReadJob(dir, id, false);
		if (job.status != "running" && job.status != "starting") {
			pump();
			return ReadJob(dir, id);
		}
		if (context.interrupted) {
			WriteFileAtomic(dir + "/cancelled", IsoTime(time(nullptr)) + "\n");
			kill(-pid_t(job.pgid), SIGTERM);
			for (int i = 0; i < 50 && GroupAlive(job.pgid); i++) {
				std::this_thread::sleep_for(std::chrono::milliseconds(100));
			}
			if (GroupAlive(job.pgid)) {
				kill(-pid_t(job.pgid), SIGKILL);
			}
			CleanupJobContainers(home, id); // the runner that would have removed them is gone
			std::remove((dir + "/snapshot.duckdb").c_str());
			std::remove((dir + "/snapshot.duckdb.wal").c_str());
			fprintf(stderr, "[lemma generate] job %s cancelled\n", id.c_str());
			throw InterruptException();
		}
		std::this_thread::sleep_for(std::chrono::milliseconds(200));
	}
}

// What lemma(...) does when the query has no executor (or regenerate := true). `existing`: an executor answers it now.
// Returns "" when lemma(...) should go on and answer (block: the job finished and installed one; background regenerate: the existing
// executor answers meanwhile; off: the bind raises the usual miss), else the id of a background job still generating (no executor yet).
std::string GenerateFor(ClientContext &context, const std::string &sql, bool existing, bool regenerate, std::string &note) {
	std::string mode = GenerateMode(context);
	if (mode == "off") {
		if (regenerate) {
			throw InvalidInputException("Lemma: regenerate := true, but lemma_generate is 'off' (SET lemma_generate = 'block' or 'background')");
		}
		return "";
	}
	std::string home = HomeSetting(context);
	std::string key = lemma::Sha256Hex(lemma::NormalizeSql(sql));
	std::string id = RunningJob(home, key);
	if (id.empty()) {
		id = StartJob(context, sql, regenerate, mode);
	}
	std::string dir = home + "/jobs/" + id;
	if (mode == "background") {
		if (existing) {
			note = "; regenerating in the background (job " + id + "), the installed executor answers until a new one proves";
			return "";
		}
		return id;
	}
	auto job = WaitJob(context, home, id);
	if (job.status != "done") {
		throw InvalidInputException("Lemma: generating an executor failed (job %s, %s%s): %s%s", id, job.status,
		                            job.exit_code >= 0 ? ", exit " + std::to_string(job.exit_code) : std::string(),
		                            job.error.empty() ? std::string("see the log") : job.error,
		                            std::string("; log: ") + job.log +
		                                (existing ? "; the installed executor is unchanged" : ""));
	}
	note = "; generated now (job " + id + ")";
	return "";
}

// ---------------------------------------------------------------- the executor table function

struct LemmaBindData : public TableFunctionData {
	std::shared_ptr<Manifest> manifest;
	std::string sql;
	std::vector<ParamBytes> params; // a query template's values, encoded for the executor
	std::unordered_map<std::string, std::string> literals; // the same values as SQL literals (a pushed predicate's `$name`)
	bool from_optimizer = false;     // lemma_mode replaced the plan of a plain SELECT
	std::string via = "lemma_query()"; // how the executor was reached, for lemma_last_query()'s reason
	std::string note;                  // generation news for lemma_last_query()'s reason (lemma(...))
	// lemma_route_unproved: the executor already ran (at bind or plan time, to be able to route a decline); Init uses this result.
	std::shared_ptr<RunResult> precomputed;
	int64_t precomputed_scan_us = 0;
	std::string precomputed_cache;
	int64_t precomputed_cache_bytes = -1;

	unique_ptr<FunctionData> Copy() const override {
		auto c = make_uniq<LemmaBindData>();
		c->manifest = manifest;
		c->sql = sql;
		c->params = params;
		c->literals = literals;
		c->from_optimizer = from_optimizer;
		c->via = via;
		c->note = note;
		c->precomputed = precomputed;
		c->precomputed_scan_us = precomputed_scan_us;
		c->precomputed_cache = precomputed_cache;
		c->precomputed_cache_bytes = precomputed_cache_bytes;
		return std::move(c);
	}
	bool Equals(const FunctionData &other) const override {
		auto &o = other.Cast<LemmaBindData>();
		if (manifest != o.manifest || sql != o.sql || params.size() != o.params.size() || precomputed != o.precomputed) {
			return false;
		}
		for (size_t i = 0; i < params.size(); i++) {
			if (params[i].kind != o.params[i].kind || params[i].bytes != o.params[i].bytes) {
				return false;
			}
		}
		return true;
	}
};

struct LemmaGlobalState : public GlobalTableFunctionState {
	std::shared_ptr<RunResult> result;
	uint64_t next = 0;
};

std::string RunSignature(const Manifest &m, const std::vector<ParamBytes> &params) {
	std::string sig = m.key;
	for (auto &p : params) {
		sig += "|" + std::to_string(p.kind) + ":" + std::to_string(p.bytes.size()) + ":" + p.bytes;
	}
	return sig;
}

// The inputs (input cache or scan) in the caller's transaction, then the executor once.
struct Ran {
	std::shared_ptr<RunResult> first;
	int64_t second = 0; // scan_us: plan + scan or cache
	std::string cache;
	int64_t cache_bytes = -1;
};

Ran ScanAndRun(ClientContext &context, const Manifest &m, const std::vector<ParamBytes> &params,
               const std::unordered_map<std::string, std::string> &literals) {
	if (m.stream) {
		// ABI 6: no input buffers, so nothing to cache; the chunks go to the proved executor as DuckDB's scan hands them out.
		Ran out;
		out.first = std::make_shared<RunResult>(StreamRun(context, m, params, out.second));
		out.cache = "skip: streaming executor";
		return out;
	}
	auto scan = ScanInputs(context, m, literals);
	Ran out;
	out.first = std::make_shared<RunResult>(RunExecutor(m, scan, params));
	out.second = scan.scan_us;
	out.cache = scan.cache;
	out.cache_bytes = scan.cache_bytes;
	return out;
}

// How the executor ran (lemma_last_query mode / chunks / threads).
void LabelRun(LastQuery &lq, const RunResult &r) {
	lq.mode = r.mode;
	lq.chunks = r.chunks;
	lq.threads = r.threads;
}

std::string DeclinedRouteReason(const std::string &reason) {
	return "declined: " + reason + "; answered by DuckDB (lemma_route_unproved = true), not by the proved executor";
}

// The SQL literal of each query-template parameter value lemma_query was given (inputs[0] is the SQL text): what a `$name`
// placeholder becomes in the SQL DuckDB runs (a routed decline, a pushed-down predicate). EncodeParam checks the same values.
std::unordered_map<std::string, std::string> ParamLiterals(const Manifest &m, const vector<Value> &inputs) {
	std::unordered_map<std::string, std::string> literal;
	for (idx_t i = 0; i < m.params.size(); i++) {
		auto &p = m.params[i];
		LogicalType type = p.sql_type == "VARCHAR" ? LogicalType::VARCHAR : ParseDuckType(p.sql_type);
		literal[p.name] = "(" + inputs[i + 1].DefaultCastAs(type).ToSQLString() + ")";
	}
	return literal;
}

// The SQL DuckDB runs for a declined query when lemma_route_unproved is on: the text itself, with each `$name` placeholder of a
// query template (outside quotes and comments) replaced by the SQL literal of the value lemma_query was given.
std::string InstantiateForDuckdb(const Manifest &m, const std::string &sql, const vector<Value> &inputs) {
	if (m.params.empty()) {
		return sql;
	}
	return SubstituteParams(m, sql, ParamLiterals(m, inputs));
}

std::string SubstituteParams(const Manifest &m, const std::string &sql, const std::unordered_map<std::string, std::string> &literal) {
	std::string out;
	size_t i = 0, n = sql.size();
	auto ident = [](char c) { return std::isalnum(static_cast<unsigned char>(c)) || c == '_'; };
	while (i < n) {
		char c = sql[i];
		size_t j = i;
		if (c == '\'' || c == '"') {
			j = sql.find(c, i + 1);
			j = j == std::string::npos ? n : j + 1;
		} else if (sql.compare(i, 2, "--") == 0) {
			j = sql.find('\n', i);
			j = j == std::string::npos ? n : j + 1;
		} else if (sql.compare(i, 2, "/*") == 0) {
			j = sql.find("*/", i + 2);
			j = j == std::string::npos ? n : j + 2;
		} else if (c == '$' && i + 1 < n && (std::isalpha(static_cast<unsigned char>(sql[i + 1])) || sql[i + 1] == '_')) {
			j = i + 1;
			while (j < n && ident(sql[j])) {
				j++;
			}
			auto it = literal.find(sql.substr(i + 1, j - i - 1));
			if (it == literal.end()) {
				throw InvalidInputException("Lemma: placeholder %s is not a parameter of executor %s", sql.substr(i, j - i), m.key);
			}
			out += it->second;
			i = j;
			continue;
		} else {
			j = i + 1;
		}
		out.append(sql, i, j - i);
		i = j;
	}
	return out;
}

// How a template match is shown in lemma_last_query(): the executor and the values bound from the caller's literals.
std::string TemplateVia(const Resolved &r) {
	std::string via = "template " + r.manifest->key.substr(0, 12) + " (";
	for (idx_t i = 0; i < r.manifest->params.size(); i++) {
		via += (i ? ", $" : "$") + r.manifest->params[i].name + " = " + r.inputs[i + 1].ToSQLString();
	}
	return via + ")";
}

bool RegenerateArg(TableFunctionBindInput &input) {
	auto it = input.named_parameters.find("regenerate");
	return it != input.named_parameters.end() && !it->second.IsNull() && BooleanValue::Get(it->second);
}

// DuckDB's own plan of `sql` as the answer of lemma(...) (a subquery, in the caller's transaction), labelled by `lq`.
unique_ptr<TableRef> DuckdbAnswers(ClientContext &context, const std::string &sql, LastQuery lq) {
	Parser parser(context.GetParserOptions());
	parser.ParseQuery(sql);
	if (parser.statements.size() != 1 || parser.statements[0]->type != StatementType::SELECT_STATEMENT) {
		throw InvalidInputException("Lemma: %s, and the SQL is not one SELECT DuckDB could answer", lq.reason);
	}
	auto &state = GetState(context);
	state.Record(lq);
	{
		std::lock_guard<std::mutex> guard(state.lock);
		state.routed_decline = true;
	}
	auto select = unique_ptr_cast<SQLStatement, SelectStatement>(std::move(parser.statements[0]));
	return make_uniq<SubqueryRef>(std::move(select));
}

// Before the bind. lemma(...) only: a query without an executor (exact key, then a stored template), or regenerate := true, goes to the
// generator (lemma_generate: block waits for it, background starts it, off does nothing). Then, with lemma_route_unproved = true,
// the executor runs now so that a DECLINE can still become DuckDB's own plan of the same SQL (a subquery, in the caller's
// transaction), labelled engine=duckdb; a result that did not decline is handed to the bind (PendingRun). A background generation
// with nothing to answer yet is an error, or with lemma_route_unproved DuckDB's answer, labelled.
unique_ptr<TableRef> LemmaQueryBindReplace(ClientContext &context, TableFunctionBindInput &input) {
	if (input.inputs.empty() || input.inputs[0].IsNull() || input.inputs[0].type().id() != LogicalTypeId::VARCHAR) {
		return nullptr; // the bind raises the argument error
	}
	auto sql = StringValue::Get(input.inputs[0]);
	bool route = BoolSetting(context, "lemma_route_unproved");
	auto resolved = Resolve(context, input.inputs);
	auto &state = GetState(context);
	if (input.table_function.name == "lemma" && input.inputs.size() == 1 && (!resolved || RegenerateArg(input))) {
		std::string note;
		std::string waiting = GenerateFor(context, sql, resolved != nullptr, RegenerateArg(input), note);
		if (!waiting.empty()) {
			std::string log = HomeSetting(context) + "/jobs/" + waiting + "/log";
			LastQuery lq;
			lq.key = lemma::Sha256Hex(lemma::NormalizeSql(sql));
			lq.sql = sql;
			if (route) {
				lq.engine = "duckdb";
				lq.reason = "no proved executor yet: generating one in the background (job " + waiting +
				            "); answered by DuckDB (lemma_route_unproved = true), not by a proved executor";
				return DuckdbAnswers(context, sql, lq);
			}
			lq.engine = "none";
			lq.reason = "no proved executor yet: generating one in the background (job " + waiting + ")";
			state.Record(lq);
			throw InvalidInputException("Lemma: no proved executor for this query yet; generating one in the background (job %s, "
			                            "log %s): see SELECT * FROM lemma_jobs()",
			                            waiting, log);
		}
		if (!note.empty()) {
			std::lock_guard<std::mutex> guard(state.lock);
			state.gen_note = note;
		}
		if (StringUtil::StartsWith(note, "; generated")) {
			resolved = Resolve(context, input.inputs);
			if (!resolved) {
				throw InvalidInputException("Lemma: the generator finished (%s) but no installed executor answers this query; see "
				                            "SELECT * FROM lemma_jobs()",
				                            note.substr(2));
			}
		}
	}
	if (!route || !resolved || resolved->inputs.size() != 1 + resolved->manifest->params.size()) {
		return nullptr;
	}
	auto &manifest = resolved->manifest;
	std::vector<ParamBytes> params;
	for (idx_t i = 0; i < manifest->params.size(); i++) {
		params.push_back(EncodeParam(manifest->params[i], resolved->inputs[i + 1]));
	}
	auto start = std::chrono::steady_clock::now();
	auto run = ScanAndRun(context, *manifest, params, ParamLiterals(*manifest, resolved->inputs));
	if (!run.first->declined) {
		std::lock_guard<std::mutex> guard(state.lock);
		state.pending.signature = RunSignature(*manifest, params);
		state.pending.result = run.first;
		state.pending.scan_us = run.second;
		state.pending.cache = run.cache;
		state.pending.cache_bytes = run.cache_bytes;
		return nullptr;
	}
	LastQuery lq;
	lq.engine = "duckdb";
	lq.reason = DeclinedRouteReason(run.first->decline_reason);
	LabelRun(lq, *run.first);
	lq.key = manifest->key;
	lq.sql = sql;
	lq.scan_us = run.second;
	lq.cache = run.cache;
	lq.cache_bytes = run.cache_bytes;
	lq.total_us = MicrosSince(start);
	return DuckdbAnswers(context,
	                     resolved->via_template ? resolved->duck_sql
	                                            : InstantiateForDuckdb(*manifest, StringValue::Get(resolved->inputs[0]), resolved->inputs),
	                     lq);
}

unique_ptr<FunctionData> LemmaQueryBind(ClientContext &context, TableFunctionBindInput &input,
                                        vector<LogicalType> &return_types, vector<string> &names) {
	const std::string fn = input.table_function.name;
	if (input.inputs.empty() || input.inputs[0].IsNull() || input.inputs[0].type().id() != LogicalTypeId::VARCHAR) {
		throw BinderException("%s takes a non-NULL VARCHAR, the SQL text, then a query template's parameter values", fn);
	}
	auto sql = StringValue::Get(input.inputs[0]);
	auto resolved = Resolve(context, input.inputs);
	if (!resolved) {
		LastQuery lq;
		lq.engine = "none";
		lq.reason = std::string(MISS_MESSAGE);
		lq.key = lemma::Sha256Hex(lemma::NormalizeSql(sql));
		lq.sql = sql;
		GetState(context).Record(lq);
		ThrowMiss(context, sql);
	}
	auto &manifest = resolved->manifest;
	auto bind = make_uniq<LemmaBindData>();
	if (resolved->inputs.size() != 1 + manifest->params.size()) {
		std::string want;
		for (auto &p : manifest->params) {
			want += (want.empty() ? "" : ", ") + p.name + " " + p.sql_type;
		}
		throw BinderException("%s: executor %s takes %d parameter value(s) after the SQL text (%s), got %d", fn, manifest->key,
		                      int64_t(manifest->params.size()), want.empty() ? "none" : want, int64_t(resolved->inputs.size() - 1));
	}
	for (idx_t i = 0; i < manifest->params.size(); i++) {
		bind->params.push_back(EncodeParam(manifest->params[i], resolved->inputs[i + 1]));
	}
	bind->literals = ParamLiterals(*manifest, resolved->inputs);
	for (auto &c : manifest->outputs) {
		return_types.push_back(c.type);
		names.push_back(c.name);
	}
	auto &st = GetState(context);
	{
		std::lock_guard<std::mutex> guard(st.lock); // the result LemmaQueryBindReplace computed for exactly this call (route on)
		if (st.pending.result && st.pending.signature == RunSignature(*manifest, bind->params)) {
			bind->precomputed = st.pending.result;
			bind->precomputed_scan_us = st.pending.scan_us;
			bind->precomputed_cache = st.pending.cache;
			bind->precomputed_cache_bytes = st.pending.cache_bytes;
			st.pending = PendingRun();
		}
		bind->note = st.gen_note;
	}
	bind->via = fn + "()" + (resolved->via_template ? ", " + TemplateVia(*resolved) : std::string());
	bind->manifest = std::shared_ptr<Manifest>(manifest.release());
	bind->sql = sql;
	return std::move(bind);
}

unique_ptr<GlobalTableFunctionState> LemmaQueryInit(ClientContext &context, TableFunctionInitInput &input) {
	auto &bind = input.bind_data->Cast<LemmaBindData>();
	auto start = std::chrono::steady_clock::now();
	auto state = make_uniq<LemmaGlobalState>();
	int64_t scan_us;
	LastQuery lq;
	if (bind.precomputed) {
		state->result = bind.precomputed;
		scan_us = bind.precomputed_scan_us;
		lq.cache = bind.precomputed_cache;
		lq.cache_bytes = bind.precomputed_cache_bytes;
	} else {
		auto run = ScanAndRun(context, *bind.manifest, bind.params, bind.literals);
		state->result = run.first;
		scan_us = run.second;
		lq.cache = run.cache;
		lq.cache_bytes = run.cache_bytes;
	}
	lq.key = bind.manifest->key;
	lq.sql = bind.sql;
	lq.scan_us = scan_us;
	LabelRun(lq, *state->result);
	if (state->result->declined) {
		// lemma_route_unproved is off (with it on, the decline was routed before this plan existed): an error, and no rows from anyone.
		lq.engine = "none";
		lq.reason = "declined: " + state->result->decline_reason;
		lq.total_us = MicrosSince(start);
		GetState(context).Record(lq);
		throw InvalidInputException("Lemma: declined: %s (executor %s; SET lemma_route_unproved = true lets DuckDB answer, "
		                            "labelled engine=duckdb)",
		                            state->result->decline_reason, bind.manifest->key);
	}
	lq.engine = "lemma";
	lq.reason = std::string("proved executor (") + bind.manifest->proof + ", git " + bind.manifest->git_sha + ") via " + bind.via +
	            bind.note;
	lq.load_us = state->result->load_us;
	lq.run_us = state->result->run_us;
	lq.rows = int64_t(state->result->rows);
	lq.total_us = MicrosSince(start);
	GetState(context).Record(lq);
	RecordUse(*bind.manifest, lq.cache);
	return std::move(state);
}

void LemmaQueryFunction(ClientContext &context, TableFunctionInput &data, DataChunk &output) {
	auto &bind = data.bind_data->Cast<LemmaBindData>();
	auto &state = data.global_state->Cast<LemmaGlobalState>();
	auto &r = *state.result;
	idx_t count = 0;
	while (state.next < r.rows && count < STANDARD_VECTOR_SIZE) {
		for (idx_t c = 0; c < bind.manifest->outputs.size(); c++) {
			WriteCell(output.data[c], count, bind.manifest->outputs[c], r.cols[c], r.bytes, state.next);
		}
		state.next++;
		count++;
	}
	output.SetCardinality(count);
}

InsertionOrderPreservingMap<string> LemmaQueryToString(TableFunctionToStringInput &input) {
	InsertionOrderPreservingMap<string> out;
	auto &bind = input.bind_data->Cast<LemmaBindData>();
	out["engine"] = "lemma";
	out["executor"] = bind.manifest->key.substr(0, 16);
	out["proof"] = bind.manifest->proof;
	if (!bind.params.empty()) {
		out["params"] = std::to_string(bind.params.size());
	}
	return out;
}

// lemma(sql [, values...] [, regenerate := true]) and its older name lemma_query(sql [, values...]). Both answer with the proved executor
// (exact key, then a stored template); only lemma(...) generates a missing one (lemma_generate) and takes regenerate.
TableFunction LemmaQueryFunctionDef(const std::string &name = "lemma_query") {
	TableFunction f(name, {LogicalType::VARCHAR}, LemmaQueryFunction, LemmaQueryBind, LemmaQueryInit);
	f.varargs = LogicalType::ANY; // a query template's parameter values
	f.bind_replace = LemmaQueryBindReplace; // generation (lemma only); with lemma_route_unproved a decline becomes DuckDB's plan
	f.to_string = LemmaQueryToString;
	if (name == "lemma") {
		f.named_parameters["regenerate"] = LogicalType::BOOLEAN;
	}
	return f;
}

// ---------------------------------------------------------------- lemma_scan_inputs(sql): the bytes handed to an executor

// One row per executor input of `sql`: what lemma_query would pass to lemma_run (the cells of an owned input up to n), from the
// same scan, in the caller's transaction. The executor does not run. For tests of the scan (thread counts, snapshots).
struct ScanInputsState : public GlobalTableFunctionState {
	std::vector<std::tuple<int64_t, std::string, std::string, uint64_t, std::string>> rows;
	size_t next = 0;
};

unique_ptr<FunctionData> ScanInputsBind(ClientContext &context, TableFunctionBindInput &input, vector<LogicalType> &types,
                                        vector<string> &names) {
	if (input.inputs.size() != 1 || input.inputs[0].IsNull()) {
		throw BinderException("lemma_scan_inputs takes the SQL text");
	}
	auto sql = StringValue::Get(input.inputs[0]);
	auto manifest = FindExecutor(context, sql);
	if (!manifest) {
		ThrowMiss(context, sql);
	}
	if (manifest->stream) {
		throw InvalidInputException("Lemma: executor %s is a streaming executor (ABI 6): it takes DuckDB's chunks in place and has "
		                            "no input buffers to show",
		                            manifest->key);
	}
	names = {"input", "name", "role", "n", "data"};
	types = {LogicalType::BIGINT, LogicalType::VARCHAR, LogicalType::VARCHAR, LogicalType::UBIGINT, LogicalType::BLOB};
	auto bind = make_uniq<LemmaBindData>();
	bind->manifest = std::shared_ptr<Manifest>(manifest.release());
	bind->sql = sql;
	return std::move(bind);
}

unique_ptr<GlobalTableFunctionState> ScanInputsInit(ClientContext &context, TableFunctionInitInput &input) {
	auto &bind = input.bind_data->Cast<LemmaBindData>();
	const Manifest &m = *bind.manifest;
	auto preps = PrepareInputs(context, m, {}); // fixed SQL only: a template's pushed predicate without its values is an error
	auto scan = ScanPrepared(context, m, preps); // always a scan: the input cache is not consulted
	auto state = make_uniq<ScanInputsState>();
	for (size_t k = 0; k < m.inputs.size(); k++) {
		const InEntry &e = m.inputs[k];
		const LemmaCol &c = scan.cols[k];
		std::string data;
		if (scan.owned[k]) {
			data.assign(reinterpret_cast<const char *>(c.data), size_t(c.n * scan.owned[k]->width));
		} else if (c.len) {
			data.assign(reinterpret_cast<const char *>(c.data), size_t(c.len));
		}
		state->rows.emplace_back(int64_t(k), e.rows ? e.table : e.table + "." + e.field, e.rows ? "rows" : e.role, c.n,
		                         std::move(data));
	}
	return std::move(state); // the owned buffers go back to the library with `scan`
}

void ScanInputsFunction(ClientContext &, TableFunctionInput &data, DataChunk &output) {
	auto &st = data.global_state->Cast<ScanInputsState>();
	idx_t count = 0;
	while (st.next < st.rows.size() && count < STANDARD_VECTOR_SIZE) {
		auto &r = st.rows[st.next++];
		output.SetValue(0, count, Value::BIGINT(std::get<0>(r)));
		output.SetValue(1, count, Value(std::get<1>(r)));
		output.SetValue(2, count, Value(std::get<2>(r)));
		output.SetValue(3, count, Value::UBIGINT(std::get<3>(r)));
		output.SetValue(4, count, Value::BLOB(const_data_ptr_cast(std::get<4>(r).data()), std::get<4>(r).size()));
		count++;
	}
	output.SetCardinality(count);
}

// ---------------------------------------------------------------- lemma_last_query()

struct LastBind : public TableFunctionData {
	LastQuery last;
};

struct LastState : public GlobalTableFunctionState {
	bool done = false;
};

unique_ptr<FunctionData> LastQueryBind(ClientContext &context, TableFunctionBindInput &input, vector<LogicalType> &types,
                                       vector<string> &names) {
	names = {"engine", "reason", "query_key", "sql", "scan_us", "load_us", "run_us", "total_us", "rows", "cache", "cache_bytes",
	         "mode", "chunks", "threads"};
	types = {LogicalType::VARCHAR, LogicalType::VARCHAR, LogicalType::VARCHAR, LogicalType::VARCHAR, LogicalType::BIGINT,
	         LogicalType::BIGINT,  LogicalType::BIGINT,  LogicalType::BIGINT,  LogicalType::BIGINT,  LogicalType::VARCHAR,
	         LogicalType::BIGINT,  LogicalType::VARCHAR, LogicalType::BIGINT,  LogicalType::BIGINT};
	auto bind = make_uniq<LastBind>();
	auto &st = GetState(context);
	std::lock_guard<std::mutex> guard(st.lock);
	bind->last = st.last;
	return std::move(bind);
}

unique_ptr<GlobalTableFunctionState> LastQueryInit(ClientContext &, TableFunctionInitInput &) {
	return make_uniq<LastState>();
}

void LastQueryFunction(ClientContext &, TableFunctionInput &data, DataChunk &output) {
	auto &st = data.global_state->Cast<LastState>();
	auto &q = data.bind_data->Cast<LastBind>().last;
	if (st.done || !q.set) {
		output.SetCardinality(0);
		return;
	}
	st.done = true;
	auto num = [](int64_t v) { return v < 0 ? Value(LogicalType::BIGINT) : Value::BIGINT(v); };
	output.SetValue(0, 0, Value(q.engine));
	output.SetValue(1, 0, Value(q.reason));
	output.SetValue(2, 0, q.key.empty() ? Value(LogicalType::VARCHAR) : Value(q.key));
	output.SetValue(3, 0, Value(q.sql));
	output.SetValue(4, 0, num(q.scan_us));
	output.SetValue(5, 0, num(q.load_us));
	output.SetValue(6, 0, num(q.run_us));
	output.SetValue(7, 0, num(q.total_us));
	output.SetValue(8, 0, num(q.rows));
	output.SetValue(9, 0, q.cache.empty() ? Value(LogicalType::VARCHAR) : Value(q.cache));
	output.SetValue(10, 0, num(q.cache_bytes));
	output.SetValue(11, 0, q.mode.empty() ? Value(LogicalType::VARCHAR) : Value(q.mode));
	output.SetValue(12, 0, num(q.chunks));
	output.SetValue(13, 0, num(q.threads));
	output.SetCardinality(1);
}

// ---------------------------------------------------------------- lemma_cache_stats(), lemma_cache_clear()

struct CacheStatsBind : public TableFunctionData {
	std::vector<Value> row;
};

unique_ptr<FunctionData> CacheStatsBindFn(ClientContext &context, TableFunctionBindInput &, vector<LogicalType> &types,
                                         vector<string> &names) {
	names = {"enabled", "entries", "bytes", "max_bytes", "hits", "misses", "stores", "evictions", "skips", "data_epoch",
	         "copies", "copy_bytes"};
	types = {LogicalType::BOOLEAN, LogicalType::BIGINT, LogicalType::BIGINT, LogicalType::BIGINT,
	         LogicalType::BIGINT,  LogicalType::BIGINT, LogicalType::BIGINT, LogicalType::BIGINT,
	         LogicalType::BIGINT,  LogicalType::BIGINT, LogicalType::BIGINT, LogicalType::BIGINT};
	auto bind = make_uniq<CacheStatsBind>();
	uint64_t epoch;
	{
		auto &v = Version();
		std::lock_guard<std::mutex> guard(v.lock);
		epoch = v.epoch;
	}
	auto &c = Cache();
	std::lock_guard<std::mutex> guard(c.lock);
	auto big = [](uint64_t x) { return Value::BIGINT(int64_t(x)); };
	bind->row = {Value::BOOLEAN(BoolSetting(context, "lemma_cache")), big(c.map.size()), big(c.bytes),
	             big(CacheCapBytes(context)), big(c.hits), big(c.misses), big(c.stores), big(c.evictions), big(c.skips),
	             big(epoch), big(c.copies), big(c.copy_bytes)};
	return std::move(bind);
}

// lemma_cache_clear(): drop every entry (calls holding one keep it until they finish); one row: entries and bytes dropped.
unique_ptr<FunctionData> CacheClearBind(ClientContext &, TableFunctionBindInput &, vector<LogicalType> &types,
                                        vector<string> &names) {
	names = {"entries", "bytes"};
	types = {LogicalType::BIGINT, LogicalType::BIGINT};
	auto bind = make_uniq<CacheStatsBind>();
	auto &c = Cache();
	std::lock_guard<std::mutex> guard(c.lock);
	bind->row = {Value::BIGINT(int64_t(c.map.size())), Value::BIGINT(int64_t(c.bytes))};
	c.map.clear();
	c.lru.clear();
	c.bytes = 0;
	return std::move(bind);
}

void OneRowFunction(ClientContext &, TableFunctionInput &data, DataChunk &output) {
	auto &st = data.global_state->Cast<LastState>();
	if (st.done) {
		output.SetCardinality(0);
		return;
	}
	st.done = true;
	auto &row = data.bind_data->Cast<CacheStatsBind>().row;
	for (idx_t i = 0; i < row.size(); i++) {
		output.SetValue(i, 0, row[i]);
	}
	output.SetCardinality(1);
}

// ---------------------------------------------------------------- lemma_mode: the optimizer hook

bool ReadsTable(LogicalOperator &op) {
	if (op.type == LogicalOperatorType::LOGICAL_GET && op.Cast<LogicalGet>().GetTable()) {
		return true;
	}
	for (auto &child : op.children) {
		if (ReadsTable(*child)) {
			return true;
		}
	}
	return false;
}

bool IsWrite(LogicalOperatorType t) {
	switch (t) {
	case LogicalOperatorType::LOGICAL_INSERT:
	case LogicalOperatorType::LOGICAL_DELETE:
	case LogicalOperatorType::LOGICAL_UPDATE:
	case LogicalOperatorType::LOGICAL_MERGE_INTO:
	case LogicalOperatorType::LOGICAL_CREATE_TABLE:
	case LogicalOperatorType::LOGICAL_CREATE_INDEX:
	case LogicalOperatorType::LOGICAL_COPY_TO_FILE:
	case LogicalOperatorType::LOGICAL_EXPORT:
		return true;
	default:
		return false;
	}
}

std::string StripExplain(const std::string &normalized) {
	std::string s = normalized;
	auto drop = [&](const char *word) {
		size_t len = std::strlen(word);
		if (s.size() > len && StringUtil::CIEquals(s.substr(0, len), word) && s[len] == ' ') {
			s = s.substr(len + 1);
			return true;
		}
		return false;
	};
	drop("EXPLAIN");
	drop("ANALYZE");
	return s;
}

void LemmaOptimize(OptimizerExtensionInput &input, unique_ptr<LogicalOperator> &plan) {
	auto &context = input.context;
	unique_ptr<LogicalOperator> *target = &plan;
	bool explain = plan->type == LogicalOperatorType::LOGICAL_EXPLAIN;
	if (explain) {
		target = &plan->children[0];
	}
	if (IsWrite((*target)->type) || !ReadsTable(**target)) {
		return; // DDL/DML and queries that read no table (SET, table functions, constants) are not Lemma's to answer
	}
	auto &state = GetState(context);
	std::string sql;
	{
		std::lock_guard<std::mutex> guard(state.lock);
		if (state.routed_decline) {
			return; // lemma_query declined and DuckDB answers its SQL (labelled at bind); this plan is that answer
		}
		if (state.in_query) {
			sql = state.query;
		}
	}
	bool lemma_mode = BoolSetting(context, "lemma_mode");
	LastQuery lq;
	lq.sql = sql;
	if (!lemma_mode) {
		lq.engine = "duckdb";
		lq.reason = "lemma_mode is off";
		state.Record(lq);
		return;
	}
	if (sql.empty()) {
		throw InvalidInputException("Lemma: lemma_mode cannot see the text of this statement (an explicit PREPARE); run it "
		                            "as a plain query or with lemma_mode off");
	}
	std::string query_sql = explain ? StripExplain(lemma::NormalizeSql(sql)) : sql;
	lq.sql = query_sql;
	lq.key = lemma::Sha256Hex(lemma::NormalizeSql(query_sql));
	vector<Value> inputs {Value(query_sql)};
	auto resolved = Resolve(context, inputs); // the exact key, then a stored template whose instance this text is
	if (!resolved) {
		if (BoolSetting(context, "lemma_route_unproved")) {
			EnqueueMiss(context, query_sql);
			lq.engine = "duckdb";
			lq.reason = "no proved executor; routed to DuckDB (lemma_route_unproved = true)";
			state.Record(lq);
			return;
		}
		lq.engine = "none";
		lq.reason = std::string(MISS_MESSAGE);
		state.Record(lq);
		ThrowMiss(context, query_sql);
	}
	auto &manifest = resolved->manifest;
	if (!resolved->via_template && !manifest->params.empty()) {
		lq.engine = "none";
		lq.reason = "a query template: lemma_mode cannot see its parameter values";
		state.Record(lq);
		throw InvalidInputException("Lemma: executor %s is a query template; lemma_mode cannot see its parameter values, call "
		                            "lemma_query('<sql>', <values>...)",
		                            manifest->key);
	}
	(*target)->ResolveOperatorTypes();
	auto &want = (*target)->types;
	if (want.size() != manifest->outputs.size()) {
		throw InvalidInputException("Lemma: the plan returns %d columns, executor %s returns %d", int64_t(want.size()),
		                            manifest->key, int64_t(manifest->outputs.size()));
	}
	vector<LogicalType> types;
	vector<string> names;
	for (idx_t i = 0; i < want.size(); i++) {
		if (want[i] != manifest->outputs[i].type) {
			throw InvalidInputException("Lemma: result column %d is %s in the plan, %s in executor %s", int64_t(i),
			                            want[i].ToString(), manifest->outputs[i].type.ToString(), manifest->key);
		}
		types.push_back(manifest->outputs[i].type);
		names.push_back(manifest->outputs[i].name);
	}
	auto bind = make_uniq<LemmaBindData>();
	for (idx_t i = 0; i < manifest->params.size(); i++) {
		bind->params.push_back(EncodeParam(manifest->params[i], resolved->inputs[i + 1]));
	}
	bind->literals = ParamLiterals(*manifest, resolved->inputs);
	if (BoolSetting(context, "lemma_route_unproved")) {
		// Run now, while DuckDB's own plan is still here: a decline keeps that plan (labelled), anything else is the answer.
		auto start = std::chrono::steady_clock::now();
		auto run = ScanAndRun(context, *manifest, bind->params, bind->literals);
		if (run.first->declined) {
			lq.engine = "duckdb";
			lq.reason = DeclinedRouteReason(run.first->decline_reason);
			LabelRun(lq, *run.first);
			lq.scan_us = run.second;
			lq.cache = run.cache;
			lq.cache_bytes = run.cache_bytes;
			lq.total_us = MicrosSince(start);
			state.Record(lq);
			return;
		}
		bind->precomputed = run.first;
		bind->precomputed_scan_us = run.second;
		bind->precomputed_cache = run.cache;
		bind->precomputed_cache_bytes = run.cache_bytes;
	}
	bind->via = "lemma_mode" + (resolved->via_template ? ", " + TemplateVia(*resolved) : std::string());
	bind->manifest = std::shared_ptr<Manifest>(manifest.release());
	bind->sql = query_sql;
	bind->from_optimizer = true;
	auto get = make_uniq<LogicalGet>(input.optimizer.binder.GenerateTableIndex(), LemmaQueryFunctionDef(), std::move(bind),
	                                 types, names);
	for (idx_t i = 0; i < types.size(); i++) {
		get->AddColumnId(i);
	}
	get->ResolveOperatorTypes();
	*target = std::move(get);
	lq.engine = "lemma";
	lq.reason = "planned: proved executor replaces the DuckDB plan (lemma_mode)";
	state.Record(lq);
}

// ---------------------------------------------------------------- lemma_list(), lemma_remove(key_or_prefix), lemma_jobs()
//
// The same store as the `lemma` CLI (`lemma list`, `lemma remove`): ${lemma_home}/executors/<key>/ and the template index.

struct RowsBind : public TableFunctionData {
	std::vector<std::vector<Value>> rows;
};

struct RowsState : public GlobalTableFunctionState {
	size_t next = 0;
};

unique_ptr<GlobalTableFunctionState> RowsInit(ClientContext &, TableFunctionInitInput &) {
	return make_uniq<RowsState>();
}

void RowsFunction(ClientContext &, TableFunctionInput &data, DataChunk &output) {
	auto &st = data.global_state->Cast<RowsState>();
	auto &rows = data.bind_data->Cast<RowsBind>().rows;
	idx_t count = 0;
	while (st.next < rows.size() && count < STANDARD_VECTOR_SIZE) {
		auto &row = rows[st.next++];
		for (idx_t c = 0; c < row.size(); c++) {
			output.SetValue(c, count, row[c]);
		}
		count++;
	}
	output.SetCardinality(count);
}

Value TextOrNull(const std::string &s) {
	return s.empty() ? Value(LogicalType::VARCHAR) : Value(s);
}

std::vector<std::string> ExecutorKeys(const std::string &home) {
	std::vector<std::string> keys;
	std::string root = home + "/executors";
	DIR *d = opendir(root.c_str());
	if (!d) {
		return keys;
	}
	while (auto *e = readdir(d)) {
		std::string name = e->d_name;
		if (name[0] != '.' && FileExists(root + "/" + name + "/manifest.json")) {
			keys.push_back(name);
		}
	}
	closedir(d);
	std::sort(keys.begin(), keys.end());
	return keys;
}

std::string ParamsText(const lemma::Json &manifest) {
	std::string out;
	for (auto &p : manifest.At("params").Arr()) {
		out += (out.empty() ? "" : ", ") + p.At("name").Str() + " " + p.At("sql_type").Str();
	}
	return out;
}

unique_ptr<FunctionData> ListBind(ClientContext &context, TableFunctionBindInput &, vector<LogicalType> &types,
                                  vector<string> &names) {
	names = {"key", "kind", "sql", "params", "proof", "created", "size_bytes", "last_used", "runs", "cache_hits", "dir"};
	types = {LogicalType::VARCHAR, LogicalType::VARCHAR, LogicalType::VARCHAR, LogicalType::VARCHAR,
	         LogicalType::VARCHAR, LogicalType::VARCHAR, LogicalType::BIGINT,  LogicalType::VARCHAR,
	         LogicalType::BIGINT,  LogicalType::BIGINT,  LogicalType::VARCHAR};
	auto bind = make_uniq<RowsBind>();
	std::string home = HomeSetting(context);
	for (auto &key : ExecutorKeys(home)) {
		std::string dir = home + "/executors/" + key;
		std::string kind = "unreadable", sql, params, proof, created = MtimeIso(dir + "/manifest.json");
		try {
			auto j = lemma::ParseJson(ReadFile(dir + "/manifest.json"));
			sql = j.At("sql").Str();
			proof = j.Has("proof") ? j.At("proof").Str() : "";
			if (j.Has("params")) {
				params = ParamsText(j);
				kind = params.empty() ? "query" : "template";
			} else {
				kind = "query";
			}
			if (FileExists(dir + "/optimize.json")) {
				auto made = lemma::ParseJson(ReadFile(dir + "/optimize.json"));
				if (made.Has("installed_at") && made.At("installed_at").kind == lemma::Json::Kind::String) {
					created = made.At("installed_at").Str();
				}
			}
		} catch (std::exception &) {
			// listed as unreadable: lemma_remove still removes it
		}
		int64_t runs = 0, hits = 0;
		{
			std::lock_guard<std::mutex> guard(usage_lock);
			auto it = usage.find(dir);
			if (it != usage.end()) {
				runs = it->second.runs;
				hits = it->second.cache_hits;
			}
		}
		int64_t size = FileSize(dir + "/lib.so");
		bind->rows.push_back({Value(key), Value(kind), TextOrNull(sql), TextOrNull(params), TextOrNull(proof), TextOrNull(created),
		                      size < 0 ? Value(LogicalType::BIGINT) : Value::BIGINT(size), TextOrNull(MtimeIso(dir + "/last_used")),
		                      Value::BIGINT(runs), Value::BIGINT(hits), Value(dir)});
	}
	return std::move(bind);
}

// The installed executor whose key is `key` or starts with it (at least 6 hex digits; ambiguous or unknown is an error), as
// lemma_cli/cache.py resolve.
std::string ResolveKey(const std::string &home, const std::string &prefix) {
	static const std::regex hex("^[0-9a-f]{6,64}$");
	if (!std::regex_match(prefix, hex)) {
		throw InvalidInputException("Lemma: '%s' is not an executor key: give at least 6 hex characters of it (SELECT key FROM lemma_list())",
		                            prefix);
	}
	std::vector<std::string> hits;
	for (auto &key : ExecutorKeys(home)) {
		if (key.compare(0, prefix.size(), prefix) == 0) {
			hits.push_back(key);
		}
	}
	if (hits.empty()) {
		throw InvalidInputException("Lemma: no installed executor with key %s* in %s/executors (SELECT * FROM lemma_list())", prefix, home);
	}
	if (hits.size() > 1) {
		std::string all;
		for (auto &h : hits) {
			all += (all.empty() ? "" : ", ") + h.substr(0, 16);
		}
		throw InvalidInputException("Lemma: key %s is ambiguous: %s", prefix, all);
	}
	return hits[0];
}

// The template index key of an executor's SQL text (empty for fixed SQL): research_loop/in_duckdb.py template_index_key.
std::string TemplateIndexKey(const std::string &sql) {
	return lemma::Sha256Hex(lemma::TemplateSkeleton(lemma::NormalizeSql(TemplateBody(sql), true)));
}

// lemma_remove(key_or_prefix): delete one installed executor (its directory and its template index entry). An already loaded
// library stays loaded in this process (executors are never unloaded) but is no longer found. One row: key, sql, dir.
unique_ptr<FunctionData> RemoveBind(ClientContext &context, TableFunctionBindInput &input, vector<LogicalType> &types,
                                    vector<string> &names) {
	if (input.inputs.size() != 1 || input.inputs[0].IsNull()) {
		throw BinderException("lemma_remove takes an executor key or a prefix of it (at least 6 hex characters)");
	}
	names = {"key", "sql", "dir"};
	types = {LogicalType::VARCHAR, LogicalType::VARCHAR, LogicalType::VARCHAR};
	std::string home = HomeSetting(context);
	std::string key = ResolveKey(home, StringValue::Get(input.inputs[0]));
	std::string dir = home + "/executors/" + key;
	std::string sql;
	try {
		sql = lemma::ParseJson(ReadFile(dir + "/manifest.json")).At("sql").Str();
	} catch (std::exception &) {
	}
	if (!sql.empty()) {
		std::string index = home + "/templates/" + TemplateIndexKey(sql);
		std::remove((index + "/" + key).c_str());
		rmdir(index.c_str()); // only when empty
	}
	std::string doomed = home + "/executors/.removed-" + key + "-" + std::to_string(getpid());
	if (std::rename(dir.c_str(), doomed.c_str()) != 0) {
		throw IOException("Lemma: cannot remove %s", dir);
	}
	RemoveTree(doomed);
	{
		std::lock_guard<std::mutex> guard(usage_lock);
		usage.erase(dir);
	}
	auto bind = make_uniq<RowsBind>();
	bind->rows.push_back({Value(key), TextOrNull(sql), Value(dir)});
	return std::move(bind);
}

unique_ptr<FunctionData> JobsBind(ClientContext &context, TableFunctionBindInput &, vector<LogicalType> &types,
                                  vector<string> &names) {
	names = {"job_id", "status", "query_key", "sql", "mode", "regenerate", "created", "finished", "exit_code", "installed_key",
	         "snapshot_bytes", "log", "error"};
	types = {LogicalType::VARCHAR, LogicalType::VARCHAR, LogicalType::VARCHAR, LogicalType::VARCHAR, LogicalType::VARCHAR,
	         LogicalType::BOOLEAN, LogicalType::VARCHAR, LogicalType::VARCHAR, LogicalType::BIGINT,  LogicalType::VARCHAR,
	         LogicalType::BIGINT,  LogicalType::VARCHAR, LogicalType::VARCHAR};
	auto bind = make_uniq<RowsBind>();
	for (auto &j : ListJobs(HomeSetting(context))) {
		bind->rows.push_back({Value(j.id), Value(j.status), Value(j.key), Value(j.sql), Value(j.mode), Value::BOOLEAN(j.regenerate),
		                      Value(j.created), TextOrNull(j.finished),
		                      j.exit_code < 0 ? Value(LogicalType::BIGINT) : Value::BIGINT(j.exit_code), TextOrNull(j.installed),
		                      Value::BIGINT(j.snapshot_bytes), Value(j.log), TextOrNull(j.error)});
	}
	return std::move(bind);
}

// lemma_template_skeleton(sql): the text the template index is keyed by (tests: equal to research_loop/in_duckdb.py's).
void SkeletonScalar(DataChunk &args, ExpressionState &, Vector &result) {
	UnaryExecutor::Execute<string_t, string_t>(args.data[0], result, args.size(), [&](string_t s) {
		return StringVector::AddString(result, lemma::TemplateSkeleton(lemma::NormalizeSql(TemplateBody(s.GetString()), true)));
	});
}

// lemma_match_template(template_sql, sql): the literal of each parameter (`name=literal`, in declaration order) when `sql` is the
// template instantiated with them (the matcher lemma(...) uses, without the range check), else NULL. For tests.
void MatchScalar(DataChunk &args, ExpressionState &, Vector &result) {
	static const std::regex decl("\\s*([A-Za-z_][A-Za-z0-9_]*)\\s+(BIGINT|DATE|VARCHAR|DECIMAL\\s*\\(\\s*\\d+\\s*,\\s*\\d+\\s*\\))\\s*(,|$)",
	                             std::regex::icase);
	for (idx_t i = 0; i < args.size(); i++) {
		auto t = args.data[0].GetValue(i), q = args.data[1].GetValue(i);
		if (t.IsNull() || q.IsNull()) {
			result.SetValue(i, Value(LogicalType::LIST(LogicalType::VARCHAR)));
			continue;
		}
		std::string tmpl = StringValue::Get(t);
		std::string body = TemplateBody(tmpl);
		size_t colon = tmpl.find(':');
		std::string list = colon == std::string::npos ? "" : tmpl.substr(colon + 1, tmpl.find('\n', colon) - colon - 1);
		std::map<std::string, lemma::LiteralKind> kinds;
		std::vector<std::string> order;
		for (std::sregex_iterator it(list.begin(), list.end(), decl), end; it != end; ++it) {
			std::string type = StringUtil::Upper((*it)[2].str());
			kinds[(*it)[1].str()] = type == "VARCHAR" ? lemma::LiteralKind::String
			                        : type == "DATE" ? lemma::LiteralKind::Date
			                                         : lemma::LiteralKind::Number;
			order.push_back((*it)[1].str());
		}
		std::map<std::string, std::string> bound;
		if (!lemma::MatchTemplate(lemma::NormalizeSql(body, true), lemma::NormalizeSql(StringValue::Get(q)), kinds, bound)) {
			result.SetValue(i, Value(LogicalType::LIST(LogicalType::VARCHAR)));
			continue;
		}
		vector<Value> out;
		for (auto &name : order) {
			out.push_back(Value(name + "=" + bound[name]));
		}
		result.SetValue(i, Value::LIST(LogicalType::VARCHAR, out));
	}
}

// ---------------------------------------------------------------- scalar helpers

void NormalizeSqlScalar(DataChunk &args, ExpressionState &, Vector &result) {
	UnaryExecutor::Execute<string_t, string_t>(args.data[0], result, args.size(), [&](string_t s) {
		return StringVector::AddString(result, lemma::NormalizeSql(s.GetString()));
	});
}

void SqlKeyScalar(DataChunk &args, ExpressionState &, Vector &result) {
	UnaryExecutor::Execute<string_t, string_t>(args.data[0], result, args.size(), [&](string_t s) {
		return StringVector::AddString(result, lemma::Sha256Hex(lemma::NormalizeSql(s.GetString())));
	});
}

void LoadInternal(ExtensionLoader &loader) {
	auto &db = loader.GetDatabaseInstance();
	auto &config = DBConfig::GetConfig(db);
	config.AddExtensionOption("lemma_mode",
	                          "Answer every table-reading SELECT with its proved Lemma executor (error or labelled DuckDB "
	                          "route when there is none, see lemma_route_unproved)",
	                          LogicalType::BOOLEAN, Value::BOOLEAN(false));
	config.AddExtensionOption("lemma_route_unproved",
	                          "In lemma_mode, run a query without a proved executor on DuckDB, and (lemma_mode and lemma_query) "
	                          "let DuckDB answer a query whose proved executor declined; both labelled engine=duckdb in "
	                          "lemma_last_query(), instead of raising an error",
	                          LogicalType::BOOLEAN, Value::BOOLEAN(false));
	config.AddExtensionOption("lemma_enqueue_misses",
	                          "Write the SQL of a miss to ${lemma_home}/queue/<key>.sql for the offline `lemma optimize`",
	                          LogicalType::BOOLEAN, Value::BOOLEAN(false));
	config.AddExtensionOption("lemma_scan_threads",
	                          "Threads of the in-DuckDB scan that hands the columns to a proved executor (0: DuckDB's threads "
	                          "setting). The rows are the same for every value",
	                          LogicalType::BIGINT, Value::BIGINT(0));
	config.AddExtensionOption("lemma_cache",
	                          "Keep the converted input buffers of a proved executor call and reuse them for a repeated call whose "
	                          "snapshot reads the same data (README: input cache); false: every call scans",
	                          LogicalType::BOOLEAN, Value::BOOLEAN(true));
	config.AddExtensionOption("lemma_cache_max_mb",
	                          "Size cap of the input cache in MB (fractions allowed), least recently used entries evicted first; "
	                          "-1 (default): a quarter of memory_limit",
	                          LogicalType::DOUBLE, Value::DOUBLE(-1));
	config.AddExtensionOption("lemma_stream_fault",
	                          "TEST ONLY: inject a scheduling bug into a streaming executor's run ('drop' a chunk, 'duplicate' one, "
	                          "'shift' one's offset, a wrong row 'count'); the proved runtime must answer ERROR, never rows. '' = none",
	                          LogicalType::VARCHAR, Value(""));
	config.AddExtensionOption("lemma_home", "Lemma's directory: executors/<key>/{lib.so,manifest.json,query.sql}, queue/",
	                          LogicalType::VARCHAR, Value(DefaultHome()));
	config.AddExtensionOption("lemma_generate",
	                          "What lemma(...) does for a query without a proved executor: 'block' (default: run the generator "
	                          "and wait, its log on stderr, Ctrl-C cancels), 'background' (start it and raise 'generating', or "
	                          "with lemma_route_unproved answer with DuckDB, labelled) or 'off' (an error)",
	                          LogicalType::VARCHAR, Value("block"));
	{
		// The generator command: from the environment at LOAD, fixed for this database; NOT a setting (a SQL user must not choose
		// what shell command runs).
		const char *gen_env = std::getenv("LEMMA_GENERATOR");
		std::lock_guard<std::mutex> guard(generator_lock);
		generators[&db] = gen_env && *gen_env ? gen_env : "lemma generate";
	}
	config.AddExtensionOption("lemma_lift_constants",
	                          "Generate a query template: the generator lifts the literal constants of WHERE/HAVING comparisons "
	                          "into typed parameters, so the executor answers every query that differs only in them",
	                          LogicalType::BOOLEAN, Value::BOOLEAN(true));
	loader.RegisterFunction(LemmaQueryFunctionDef());
	loader.RegisterFunction(LemmaQueryFunctionDef("lemma"));
	loader.RegisterFunction(TableFunction("lemma_list", {}, RowsFunction, ListBind, RowsInit));
	loader.RegisterFunction(TableFunction("lemma_remove", {LogicalType::VARCHAR}, RowsFunction, RemoveBind, RowsInit));
	loader.RegisterFunction(TableFunction("lemma_jobs", {}, RowsFunction, JobsBind, RowsInit));
	loader.RegisterFunction(
	    ScalarFunction("lemma_template_skeleton", {LogicalType::VARCHAR}, LogicalType::VARCHAR, SkeletonScalar));
	loader.RegisterFunction(ScalarFunction("lemma_match_template", {LogicalType::VARCHAR, LogicalType::VARCHAR},
	                                       LogicalType::LIST(LogicalType::VARCHAR), MatchScalar));
	TableFunction last("lemma_last_query", {}, LastQueryFunction, LastQueryBind, LastQueryInit);
	loader.RegisterFunction(last);
	loader.RegisterFunction(
	    TableFunction("lemma_scan_inputs", {LogicalType::VARCHAR}, ScanInputsFunction, ScanInputsBind, ScanInputsInit));
	loader.RegisterFunction(TableFunction("lemma_cache_stats", {}, OneRowFunction, CacheStatsBindFn, LastQueryInit));
	loader.RegisterFunction(TableFunction("lemma_cache_clear", {}, OneRowFunction, CacheClearBind, LastQueryInit));
	loader.RegisterFunction(
	    ScalarFunction("lemma_normalize_sql", {LogicalType::VARCHAR}, LogicalType::VARCHAR, NormalizeSqlScalar));
	loader.RegisterFunction(ScalarFunction("lemma_sql_key", {LogicalType::VARCHAR}, LogicalType::VARCHAR, SqlKeyScalar));
	OptimizerExtension ext;
	ext.optimize_function = LemmaOptimize;
	OptimizerExtension::Register(config, ext);
	ExtensionCallback::Register(config, make_shared_ptr<LemmaConnectionCallback>());
	for (auto &connection : ConnectionManager::Get(db).GetConnectionList()) {
		// Connections opened before LOAD (including the one running it): their transaction may have begun unseen, so each counts
		// as open, at an unknown epoch, until its next commit or rollback (the input cache stays unused until then).
		GetState(*connection).MarkOpenUnknown();
	}
	loader.SetDescription("Lemma: proved query executors (Verus-verified run_query) inside DuckDB");
}

} // namespace

void LemmaExtension::Load(ExtensionLoader &loader) {
	LoadInternal(loader);
}
std::string LemmaExtension::Name() {
	return "lemma";
}
std::string LemmaExtension::Version() const {
#ifdef EXT_VERSION_LEMMA
	return EXT_VERSION_LEMMA;
#else
	return "";
#endif
}

} // namespace duckdb

extern "C" {
DUCKDB_CPP_EXTENSION_ENTRY(lemma, loader) {
	duckdb::LoadInternal(loader);
}
}
