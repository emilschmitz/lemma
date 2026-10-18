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
#include "duckdb/optimizer/optimizer.hpp"
#include "duckdb/optimizer/optimizer_extension.hpp"
#include "duckdb/parallel/task_scheduler.hpp"
#include "duckdb/parser/parser.hpp"
#include "duckdb/parser/statement/select_statement.hpp"
#include "duckdb/parser/tableref/subqueryref.hpp"
#include "duckdb/planner/binder.hpp"
#include "duckdb/planner/extension_callback.hpp"
#include "duckdb/planner/operator/logical_get.hpp"
#include "duckdb/storage/data_table.hpp"
#include "duckdb/storage/table/row_group.hpp"
#include "duckdb/storage/table/row_group_collection.hpp"
#include "duckdb/storage/table/scan_state.hpp"
#include "duckdb/transaction/duck_transaction.hpp"
#include "duckdb/transaction/local_storage.hpp"

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
#include <mutex>
#include <regex>
#include <sstream>
#include <sys/stat.h>
#include <unistd.h>
#include <unordered_map>

static_assert(__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__, "the executor ABI is little-endian");

namespace duckdb {

namespace {

using i128 = __int128;

constexpr uint32_t ABI_VERSION = 4;
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
};

struct RunResult;

// What the route-on bind of lemma_query computed for the bind that follows it (lemma_route_unproved, see LemmaQueryBindReplace).
struct PendingRun {
	std::string signature; // executor key + encoded parameters
	std::shared_ptr<RunResult> result;
	int64_t scan_us = 0;
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

	void QueryBegin(ClientContext &context) override {
		std::lock_guard<std::mutex> guard(lock);
		in_query = true;
		query = context.GetCurrentQuery();
		routed_decline = false;
		pending = PendingRun();
	}
	void QueryEnd(ClientContext &context) override {
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
};

// One query-template parameter (manifest "params"): its SQL type decides how a lemma_query argument is encoded.
struct ParamSpec {
	std::string name, sql_type, rust_type;
	int scale = 0;
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
};

struct Manifest {
	std::string dir, key, sql, normalized_sql, proof, lib_sha256, git_sha;
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
	if (inner == "f64") {
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
                                      const std::string &param_layout) {
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
	exec->run = reinterpret_cast<lemma_run_fn>(sym("lemma_run"));
	exec->free_out = reinterpret_cast<lemma_free_out_fn>(sym("lemma_free_out"));
	exec->alloc_input = reinterpret_cast<lemma_alloc_input_fn>(sym("lemma_alloc_input"));
	exec->free_input = reinterpret_cast<lemma_free_input_fn>(sym("lemma_free_input"));
	if (abi() != ABI_VERSION) {
		throw InvalidInputException("Lemma: executor ABI version %d, this extension speaks %d", int(abi()), int(ABI_VERSION));
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

// The executor for `sql`, or nullptr on a miss. Every check that fails on a PRESENT executor is an error, never a miss.
std::unique_ptr<Manifest> FindExecutor(ClientContext &context, const std::string &sql) {
	std::string normalized = lemma::NormalizeSql(sql);
	std::string key = lemma::Sha256Hex(normalized);
	std::string dir = HomeSetting(context) + "/executors/" + key;
	struct stat st;
	if (stat((dir + "/manifest.json").c_str(), &st) != 0) {
		return nullptr;
	}
	lemma::Json j;
	try {
		j = lemma::ParseJson(ReadFile(dir + "/manifest.json"));
	} catch (std::runtime_error &e) {
		throw InvalidInputException("Lemma: %s/manifest.json: %s", dir, std::string(e.what()));
	}
	auto m = make_uniq<Manifest>();
	try {
		m->dir = dir;
		m->key = j.At("key").Str();
		m->sql = j.At("sql").Str();
		m->normalized_sql = j.At("normalized_sql").Str();
		m->proof = j.At("proof").Str();
		m->lib_sha256 = j.At("lib_sha256").Str();
		m->git_sha = j.At("git_sha").Str();
		if (j.At("format").Int() != 1 || j.At("abi_version").Int() != ABI_VERSION) {
			throw InvalidInputException("Lemma: %s: manifest format/ABI not understood by this extension", dir);
		}
		if (!j.At("in_duckdb").Bool()) {
			throw InvalidInputException("Lemma: %s was not installed for in-DuckDB execution (in_duckdb is false)", dir);
		}
		if (m->key != key || m->normalized_sql != normalized) {
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
		m->exec = LoadLibrary(*m, JoinLines(j.At("input_layout").Arr()), JoinLines(j.At("output_layout").Arr()),
		                      JoinLines(j.At("param_layout").Arr()));
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
	uint8_t *out = p.dest ? p.dest + p.width * row : nullptr;
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

struct ScanResult {
	std::vector<std::string> buffers;                // borrowed byte inputs: strings, dictionaries
	std::vector<std::vector<uint8_t>> bytes;         // borrowed one-byte inputs: bool, validity
	std::vector<std::unique_ptr<OwnedBuffer>> owned; // owned inputs (null where an input is not owned)
	std::vector<LemmaCol> cols;
	int64_t scan_us = 0;

	// lemma_run takes the owned buffers whatever it returns: from here on they are the library's.
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
uint64_t ScanTable(ClientContext &context, DuckTransaction &transaction, DataTable &storage, const vector<StorageIndex> &ids,
                   const vector<LogicalType> &types, std::vector<ColPlan> &plans, const std::shared_ptr<Executor> &exec,
                   ScanResult &res, idx_t want_threads) {
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
			res.owned[p.k] = make_uniq<OwnedBuffer>(exec, p.k, upper, p.width);
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
	auto worker = [&]() {
		try {
			TableScanState ts;
			ts.Initialize(ids, &context, nullptr);
			DataChunk chunk;
			chunk.Initialize(Allocator::Get(context), types);
			for (auto &src : sources) {
				CollectionScanState &cs = src->local ? ts.local_state : ts.table_state;
				while (!stop.load() && src->collection->NextParallelScan(context, src->state, cs)) {
					uint64_t start = cs.row_group->GetRowStart() + cs.vector_index * STANDARD_VECTOR_SIZE;
					if (start < src->base || cs.max_row < start || cs.max_row - src->base > src->upper) {
						throw InternalException("Lemma: a scan task outside its table (%d..%d)", int64_t(start),
						                        int64_t(cs.max_row));
					}
					auto t = make_uniq<TaskOut>();
					t->offset = src->offset + (start - src->base);
					uint64_t range = cs.max_row - start;
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
						for (auto &p : plans) {
							DecodeChunk(p, chunk.data[p.chunk_col], chunk.size(), *t);
						}
						t->count += chunk.size();
					}
					std::lock_guard<std::mutex> guard(out_lock);
					tasks.push_back(std::move(t));
				}
			}
		} catch (...) {
			std::lock_guard<std::mutex> guard(out_lock);
			if (!error) {
				error = std::current_exception();
			}
			stop = true;
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
	// Row order: tasks by position; pack fixed-width cells toward the front where a task left a gap.
	std::sort(tasks.begin(), tasks.end(),
	          [](const std::unique_ptr<TaskOut> &a, const std::unique_ptr<TaskOut> &b) { return a->offset < b->offset; });
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

// Scan exactly the columns the manifest names, table by table, in the caller's transaction (its snapshot, its own uncommitted
// changes included), on lemma_scan_threads threads (default: DuckDB's `threads`), in single-threaded row order. Fixed-width
// integer and f64 fields are decoded once, straight into buffers of the executor library (owned inputs, ABI 3); bool and
// validity into byte buffers; strings and dictionaries into byte strings.
ScanResult ScanInputs(ClientContext &context, const Manifest &m) {
	auto start = std::chrono::steady_clock::now();
	ScanResult res;
	res.buffers.resize(m.inputs.size());
	res.bytes.resize(m.inputs.size());
	res.owned.resize(m.inputs.size());
	res.cols.resize(m.inputs.size());
	idx_t want_threads = ScanThreads(context);
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
		}
		for (auto &p : plans) {
			if (p.role == Role::Code && dict_of_codes.count(p.k)) {
				p.dict_k = dict_of_codes[p.k];
			}
		}
		uint64_t total = ScanTable(context, transaction, storage, ids, types, plans, m.exec, res, want_threads);
		res.cols[i] = LemmaCol {nullptr, 0, total};
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
		i = end;
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

RunResult RunExecutor(const Manifest &m, ScanResult &in, const std::vector<ParamBytes> &params) {
	LemmaOut out {nullptr, 0, 0};
	std::vector<LemmaParam> abi_params;
	for (auto &p : params) {
		abi_params.push_back(
		    LemmaParam {p.kind, reinterpret_cast<const uint8_t *>(p.bytes.data()), uint64_t(p.bytes.size())});
	}
	in.ReleaseOwned(); // lemma_run takes every owned input buffer, whatever it returns (lemma_abi.h)
	int32_t code = m.exec->run(in.cols.data(), in.cols.size(), abi_params.data(), abi_params.size(), &out);
	std::string bytes(reinterpret_cast<const char *>(out.ptr), size_t(out.len));
	m.exec->free_out(&out);
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

// ---------------------------------------------------------------- the executor table function

struct LemmaBindData : public TableFunctionData {
	std::shared_ptr<Manifest> manifest;
	std::string sql;
	std::vector<ParamBytes> params; // a query template's values, encoded for the executor
	bool from_optimizer = false;     // lemma_mode replaced the plan of a plain SELECT
	// lemma_route_unproved: the executor already ran (at bind or plan time, to be able to route a decline); Init uses this result.
	std::shared_ptr<RunResult> precomputed;
	int64_t precomputed_scan_us = 0;

	unique_ptr<FunctionData> Copy() const override {
		auto c = make_uniq<LemmaBindData>();
		c->manifest = manifest;
		c->sql = sql;
		c->params = params;
		c->from_optimizer = from_optimizer;
		c->precomputed = precomputed;
		c->precomputed_scan_us = precomputed_scan_us;
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

// Scan in the caller's transaction and run the executor once: (result, scan_us).
std::pair<std::shared_ptr<RunResult>, int64_t> ScanAndRun(ClientContext &context, const Manifest &m,
                                                          const std::vector<ParamBytes> &params) {
	auto scan = ScanInputs(context, m);
	auto result = std::make_shared<RunResult>(RunExecutor(m, scan, params));
	return {result, scan.scan_us};
}

std::string DeclinedRouteReason(const std::string &reason) {
	return "declined: " + reason + "; answered by DuckDB (lemma_route_unproved = true), not by the proved executor";
}

// The SQL DuckDB runs for a declined query when lemma_route_unproved is on: the text itself, with each `$name` placeholder of a
// query template (outside quotes and comments) replaced by the SQL literal of the value lemma_query was given.
std::string InstantiateForDuckdb(const Manifest &m, const std::string &sql, const vector<Value> &inputs) {
	if (m.params.empty()) {
		return sql;
	}
	std::unordered_map<std::string, std::string> literal;
	for (idx_t i = 0; i < m.params.size(); i++) {
		auto &p = m.params[i];
		LogicalType type = p.sql_type == "VARCHAR" ? LogicalType::VARCHAR : ParseDuckType(p.sql_type);
		literal[p.name] = "(" + inputs[i + 1].DefaultCastAs(type).ToSQLString() + ")";
	}
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

// lemma_route_unproved = true: run the executor while lemma_query is bound, so a DECLINE can still become DuckDB's own plan of the
// same SQL (a subquery, in the caller's transaction), labelled engine=duckdb. Otherwise (route off, a miss, a wrong argument count)
// nothing happens here and LemmaQueryBind decides; a result that did not decline is handed to that bind (PendingRun).
unique_ptr<TableRef> LemmaQueryBindReplace(ClientContext &context, TableFunctionBindInput &input) {
	if (!BoolSetting(context, "lemma_route_unproved") || input.inputs.empty() || input.inputs[0].IsNull() ||
	    input.inputs[0].type().id() != LogicalTypeId::VARCHAR) {
		return nullptr;
	}
	auto sql = StringValue::Get(input.inputs[0]);
	auto manifest = FindExecutor(context, sql);
	if (!manifest || input.inputs.size() != 1 + manifest->params.size()) {
		return nullptr;
	}
	std::vector<ParamBytes> params;
	for (idx_t i = 0; i < manifest->params.size(); i++) {
		params.push_back(EncodeParam(manifest->params[i], input.inputs[i + 1]));
	}
	auto start = std::chrono::steady_clock::now();
	auto run = ScanAndRun(context, *manifest, params);
	auto &state = GetState(context);
	if (!run.first->declined) {
		std::lock_guard<std::mutex> guard(state.lock);
		state.pending.signature = RunSignature(*manifest, params);
		state.pending.result = run.first;
		state.pending.scan_us = run.second;
		return nullptr;
	}
	Parser parser(context.GetParserOptions());
	parser.ParseQuery(InstantiateForDuckdb(*manifest, sql, input.inputs));
	if (parser.statements.size() != 1 || parser.statements[0]->type != StatementType::SELECT_STATEMENT) {
		throw InvalidInputException("Lemma: declined (%s), and the SQL of executor %s is not one SELECT DuckDB could answer",
		                            run.first->decline_reason, manifest->key);
	}
	LastQuery lq;
	lq.engine = "duckdb";
	lq.reason = DeclinedRouteReason(run.first->decline_reason);
	lq.key = manifest->key;
	lq.sql = sql;
	lq.scan_us = run.second;
	lq.total_us = MicrosSince(start);
	state.Record(lq);
	{
		std::lock_guard<std::mutex> guard(state.lock);
		state.routed_decline = true;
	}
	auto select = unique_ptr_cast<SQLStatement, SelectStatement>(std::move(parser.statements[0]));
	return make_uniq<SubqueryRef>(std::move(select));
}

unique_ptr<FunctionData> LemmaQueryBind(ClientContext &context, TableFunctionBindInput &input,
                                        vector<LogicalType> &return_types, vector<string> &names) {
	if (input.inputs.empty() || input.inputs[0].IsNull() || input.inputs[0].type().id() != LogicalTypeId::VARCHAR) {
		throw BinderException("lemma_query takes a non-NULL VARCHAR, the SQL text, then a query template's parameter values");
	}
	auto sql = StringValue::Get(input.inputs[0]);
	auto manifest = FindExecutor(context, sql);
	if (!manifest) {
		LastQuery lq;
		lq.engine = "none";
		lq.reason = std::string(MISS_MESSAGE);
		lq.key = lemma::Sha256Hex(lemma::NormalizeSql(sql));
		lq.sql = sql;
		GetState(context).Record(lq);
		ThrowMiss(context, sql);
	}
	auto bind = make_uniq<LemmaBindData>();
	if (input.inputs.size() != 1 + manifest->params.size()) {
		std::string want;
		for (auto &p : manifest->params) {
			want += (want.empty() ? "" : ", ") + p.name + " " + p.sql_type;
		}
		throw BinderException("lemma_query: executor %s takes %d parameter value(s) after the SQL text (%s), got %d",
		                      manifest->key, int64_t(manifest->params.size()), want.empty() ? "none" : want,
		                      int64_t(input.inputs.size() - 1));
	}
	for (idx_t i = 0; i < manifest->params.size(); i++) {
		bind->params.push_back(EncodeParam(manifest->params[i], input.inputs[i + 1]));
	}
	for (auto &c : manifest->outputs) {
		return_types.push_back(c.type);
		names.push_back(c.name);
	}
	{
		auto &st = GetState(context); // the result LemmaQueryBindReplace computed for exactly this call (route on)
		std::lock_guard<std::mutex> guard(st.lock);
		if (st.pending.result && st.pending.signature == RunSignature(*manifest, bind->params)) {
			bind->precomputed = st.pending.result;
			bind->precomputed_scan_us = st.pending.scan_us;
			st.pending = PendingRun();
		}
	}
	bind->manifest = std::shared_ptr<Manifest>(manifest.release());
	bind->sql = sql;
	return std::move(bind);
}

unique_ptr<GlobalTableFunctionState> LemmaQueryInit(ClientContext &context, TableFunctionInitInput &input) {
	auto &bind = input.bind_data->Cast<LemmaBindData>();
	auto start = std::chrono::steady_clock::now();
	auto state = make_uniq<LemmaGlobalState>();
	int64_t scan_us;
	if (bind.precomputed) {
		state->result = bind.precomputed;
		scan_us = bind.precomputed_scan_us;
	} else {
		auto run = ScanAndRun(context, *bind.manifest, bind.params);
		state->result = run.first;
		scan_us = run.second;
	}
	LastQuery lq;
	lq.key = bind.manifest->key;
	lq.sql = bind.sql;
	lq.scan_us = scan_us;
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
	lq.reason = std::string("proved executor (") + bind.manifest->proof + ", git " + bind.manifest->git_sha + ")" +
	            (bind.from_optimizer ? " via lemma_mode" : " via lemma_query()");
	lq.load_us = state->result->load_us;
	lq.run_us = state->result->run_us;
	lq.rows = int64_t(state->result->rows);
	lq.total_us = MicrosSince(start);
	GetState(context).Record(lq);
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

TableFunction LemmaQueryFunctionDef() {
	TableFunction f("lemma_query", {LogicalType::VARCHAR}, LemmaQueryFunction, LemmaQueryBind, LemmaQueryInit);
	f.varargs = LogicalType::ANY; // a query template's parameter values
	f.bind_replace = LemmaQueryBindReplace; // only acts with lemma_route_unproved = true (a decline becomes DuckDB's plan)
	f.to_string = LemmaQueryToString;
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
	auto scan = ScanInputs(context, m);
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
	names = {"engine", "reason", "query_key", "sql", "scan_us", "load_us", "run_us", "total_us", "rows"};
	types = {LogicalType::VARCHAR, LogicalType::VARCHAR, LogicalType::VARCHAR, LogicalType::VARCHAR, LogicalType::BIGINT,
	         LogicalType::BIGINT,  LogicalType::BIGINT,  LogicalType::BIGINT,  LogicalType::BIGINT};
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
	auto manifest = FindExecutor(context, query_sql);
	if (!manifest) {
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
	if (!manifest->params.empty()) {
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
	if (BoolSetting(context, "lemma_route_unproved")) {
		// Run now, while DuckDB's own plan is still here: a decline keeps that plan (labelled), anything else is the answer.
		auto start = std::chrono::steady_clock::now();
		auto run = ScanAndRun(context, *manifest, {});
		if (run.first->declined) {
			lq.engine = "duckdb";
			lq.reason = DeclinedRouteReason(run.first->decline_reason);
			lq.scan_us = run.second;
			lq.total_us = MicrosSince(start);
			state.Record(lq);
			return;
		}
		bind->precomputed = run.first;
		bind->precomputed_scan_us = run.second;
	}
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
	config.AddExtensionOption("lemma_home", "Lemma's directory: executors/<key>/{lib.so,manifest.json,query.sql}, queue/",
	                          LogicalType::VARCHAR, Value(DefaultHome()));
	loader.RegisterFunction(LemmaQueryFunctionDef());
	TableFunction last("lemma_last_query", {}, LastQueryFunction, LastQueryBind, LastQueryInit);
	loader.RegisterFunction(last);
	loader.RegisterFunction(
	    TableFunction("lemma_scan_inputs", {LogicalType::VARCHAR}, ScanInputsFunction, ScanInputsBind, ScanInputsInit));
	loader.RegisterFunction(
	    ScalarFunction("lemma_normalize_sql", {LogicalType::VARCHAR}, LogicalType::VARCHAR, NormalizeSqlScalar));
	loader.RegisterFunction(ScalarFunction("lemma_sql_key", {LogicalType::VARCHAR}, LogicalType::VARCHAR, SqlKeyScalar));
	OptimizerExtension ext;
	ext.optimize_function = LemmaOptimize;
	OptimizerExtension::Register(config, ext);
	ExtensionCallback::Register(config, make_shared_ptr<LemmaConnectionCallback>());
	for (auto &connection : ConnectionManager::Get(db).GetConnectionList()) {
		GetState(*connection); // connections opened before LOAD (including the one running it)
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
