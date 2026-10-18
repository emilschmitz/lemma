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
#include "duckdb/planner/binder.hpp"
#include "duckdb/planner/extension_callback.hpp"
#include "duckdb/planner/operator/logical_get.hpp"
#include "duckdb/storage/data_table.hpp"
#include "duckdb/storage/table/scan_state.hpp"
#include "duckdb/transaction/duck_transaction.hpp"

#include <cerrno>
#include <chrono>
#include <cstdlib>
#include <deque>
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

constexpr uint32_t ABI_VERSION = 2;
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

class LemmaState : public ClientContextState {
public:
	std::mutex lock;
	LastQuery last;
	bool in_query = false;
	std::string query; // the statement text of the running query (set in QueryBegin)

	void QueryBegin(ClientContext &context) override {
		std::lock_guard<std::mutex> guard(lock);
		in_query = true;
		query = context.GetCurrentQuery();
	}
	void QueryEnd(ClientContext &context) override {
		std::lock_guard<std::mutex> guard(lock);
		in_query = false;
		query.clear();
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

struct Encoder {
	InEntry e;
	std::string label;
	IntTarget target;
	i128 mul = 1;              // decimal: 10^(scale - source_scale)
	bool decimal_wide = false; // f64 from DECIMAL: the exporter's HUGEINT path (else BIGINT)
	std::string bytes;
	uint64_t n = 0;
	bool null_seen = false;
	uint64_t code_limit = 0;

	void PutInt(i128 v) {
		if (v < target.lo || v > target.hi) {
			throw InvalidInputException("Lemma: cannot pack %s as %s (%s)", I128String(v), e.rust_type, label);
		}
		char buf[16];
		std::memcpy(buf, &v, 16);
		bytes.append(buf, size_t(target.width));
	}
	static void PutStr(std::string &out, const char *data, size_t len) {
		if (len > 0xFFFFFFFFull) {
			throw InvalidInputException("Lemma: a string is longer than u32");
		}
		uint32_t l = uint32_t(len);
		out.append(reinterpret_cast<const char *>(&l), 4);
		out.append(data, len);
	}
	void NullCell() {
		if (!e.nullable) {
			throw InvalidInputException("Lemma: %s has NULLs; the catalog does not declare the column nullable", label);
		}
	}

	// The integer value of a cell of an integer, DATE or DECIMAL column (unscaled for DECIMAL).
	static i128 IntOf(const LogicalType &t, const UnifiedVectorFormat &f, idx_t idx, const std::string &label) {
		switch (t.id()) {
		case LogicalTypeId::TINYINT:
			return UnifiedVectorFormat::GetData<int8_t>(f)[idx];
		case LogicalTypeId::SMALLINT:
			return UnifiedVectorFormat::GetData<int16_t>(f)[idx];
		case LogicalTypeId::INTEGER:
			return UnifiedVectorFormat::GetData<int32_t>(f)[idx];
		case LogicalTypeId::BIGINT:
			return UnifiedVectorFormat::GetData<int64_t>(f)[idx];
		case LogicalTypeId::UTINYINT:
			return UnifiedVectorFormat::GetData<uint8_t>(f)[idx];
		case LogicalTypeId::USMALLINT:
			return UnifiedVectorFormat::GetData<uint16_t>(f)[idx];
		case LogicalTypeId::UINTEGER:
			return UnifiedVectorFormat::GetData<uint32_t>(f)[idx];
		case LogicalTypeId::UBIGINT:
			return UnifiedVectorFormat::GetData<uint64_t>(f)[idx];
		case LogicalTypeId::HUGEINT: {
			auto h = UnifiedVectorFormat::GetData<hugeint_t>(f)[idx];
			return (i128(h.upper) << 64) | i128(h.lower);
		}
		case LogicalTypeId::DATE:
			return UnifiedVectorFormat::GetData<date_t>(f)[idx].days;
		case LogicalTypeId::DECIMAL:
			switch (t.InternalType()) {
			case PhysicalType::INT16:
				return UnifiedVectorFormat::GetData<int16_t>(f)[idx];
			case PhysicalType::INT32:
				return UnifiedVectorFormat::GetData<int32_t>(f)[idx];
			case PhysicalType::INT64:
				return UnifiedVectorFormat::GetData<int64_t>(f)[idx];
			case PhysicalType::INT128: {
				auto h = UnifiedVectorFormat::GetData<hugeint_t>(f)[idx];
				return (i128(h.upper) << 64) | i128(h.lower);
			}
			default:
				break;
			}
			break;
		default:
			break;
		}
		throw InvalidInputException("Lemma: %s: DuckDB type %s is not loadable as an integer", label, t.ToString());
	}

	i128 Scaled(i128 v) {
		i128 out;
		if (__builtin_mul_overflow(v, mul, &out)) {
			throw InvalidInputException("Lemma: %s: value out of range at scale %d", label, e.scale);
		}
		return out;
	}

	enum class Role { Valid, Int, Date, Decimal, F64, Bool, String, Code };
	Role role = Role::Int;

	void SetRole() {
		static const std::unordered_map<std::string, Role> roles = {
		    {"valid", Role::Valid}, {"int", Role::Int},       {"date", Role::Date},     {"decimal", Role::Decimal},
		    {"f64", Role::F64},     {"bool", Role::Bool},     {"string", Role::String}, {"code", Role::Code}};
		auto it = roles.find(e.role);
		if (it == roles.end()) {
			throw InvalidInputException("Lemma: %s: unknown input role %s", label, e.role);
		}
		role = it->second;
	}

	// Integer cells (INT*, UINT*, HUGEINT, DATE, DECIMAL) of one chunk: typed loop, scale, range check, `width` LE bytes each.
	template <class SRC, class TO_I128>
	void AppendInts(const UnifiedVectorFormat &f, idx_t count, TO_I128 to_i128) {
		auto data = UnifiedVectorFormat::GetData<SRC>(f);
		size_t w = size_t(target.width);
		size_t at = bytes.size();
		bytes.resize(at + w * count);
		char *out = &bytes[at];
		bool all_valid = f.validity.AllValid();
		for (idx_t r = 0; r < count; r++) {
			idx_t idx = f.sel->get_index(r);
			i128 v = 0;
			if (all_valid || f.validity.RowIsValid(idx)) {
				v = to_i128(data[idx]);
				if (role == Role::Decimal && mul != 1) {
					v = Scaled(v);
				}
			} else {
				NullCell();
			}
			if (v < target.lo || v > target.hi) {
				throw InvalidInputException("Lemma: cannot pack %s as %s (%s)", I128String(v), e.rust_type, label);
			}
			std::memcpy(out + w * r, &v, w);
		}
	}

	void AppendIntegers(const LogicalType &t, const UnifiedVectorFormat &f, idx_t count) {
		auto huge = [](hugeint_t h) { return (i128(h.upper) << 64) | i128(h.lower); };
		auto same = [](int64_t v) { return i128(v); };
		PhysicalType p = t.InternalType();
		switch (t.id()) {
		case LogicalTypeId::DATE:
			return AppendInts<date_t>(f, count, [](date_t d) { return i128(d.days); });
		case LogicalTypeId::UBIGINT:
			return AppendInts<uint64_t>(f, count, [](uint64_t v) { return i128(v); });
		case LogicalTypeId::UINTEGER:
			return AppendInts<uint32_t>(f, count, same);
		case LogicalTypeId::USMALLINT:
			return AppendInts<uint16_t>(f, count, same);
		case LogicalTypeId::UTINYINT:
			return AppendInts<uint8_t>(f, count, same);
		case LogicalTypeId::TINYINT:
		case LogicalTypeId::SMALLINT:
		case LogicalTypeId::INTEGER:
		case LogicalTypeId::BIGINT:
		case LogicalTypeId::HUGEINT:
		case LogicalTypeId::DECIMAL:
			switch (p) {
			case PhysicalType::INT8:
				return AppendInts<int8_t>(f, count, same);
			case PhysicalType::INT16:
				return AppendInts<int16_t>(f, count, same);
			case PhysicalType::INT32:
				return AppendInts<int32_t>(f, count, same);
			case PhysicalType::INT64:
				return AppendInts<int64_t>(f, count, same);
			case PhysicalType::INT128:
				return AppendInts<hugeint_t>(f, count, huge);
			default:
				break;
			}
			break;
		default:
			break;
		}
		throw InvalidInputException("Lemma: %s: DuckDB type %s is not loadable as an integer", label, t.ToString());
	}

	// Dictionary codes: distinct non-NULL strings numbered in order of first appearance. Keys point into `entries` (a deque:
	// its elements never move, so the string_t keys stay valid).
	string_map_t<uint32_t> codes;
	std::deque<std::string> entries;

	uint32_t CodeOf(const string_t &s) {
		auto it = codes.find(s);
		if (it != codes.end()) {
			return it->second;
		}
		if (std::memchr(s.GetData(), 0, s.GetSize()) != nullptr) {
			throw InvalidInputException("Lemma: %s: a NUL byte in a dictionary string", label);
		}
		if (entries.size() >= code_limit) {
			throw InvalidInputException("Lemma: cannot pack code %d as %s (%s)", int64_t(entries.size()), e.rust_type, label);
		}
		uint32_t code = uint32_t(entries.size());
		entries.emplace_back(s.GetData(), s.GetSize());
		const std::string &kept = entries.back();
		codes.emplace(string_t(kept.data(), uint32_t(kept.size())), code);
		return code;
	}

	// A DuckDB dictionary vector: the same index is the same string, so look each index up once per chunk.
	std::vector<int64_t> memo;
	void AppendDictionaryCodes(const UnifiedVectorFormat &f, idx_t count) {
		auto data = UnifiedVectorFormat::GetData<string_t>(f);
		idx_t max_idx = 0;
		for (idx_t r = 0; r < count; r++) {
			max_idx = MaxValue<idx_t>(max_idx, f.sel->get_index(r));
		}
		memo.assign(max_idx + 1, -1);
		for (idx_t r = 0; r < count; r++) {
			idx_t idx = f.sel->get_index(r);
			uint32_t code = 0;
			if (!f.validity.RowIsValid(idx)) {
				NullCell();
				null_seen = true;
			} else if (memo[idx] >= 0) {
				code = uint32_t(memo[idx]);
			} else {
				code = CodeOf(data[idx]);
				memo[idx] = code;
			}
			PutInt(code);
		}
	}

	void Append(const LogicalType &t, Vector &vec, idx_t count) {
		UnifiedVectorFormat f;
		vec.ToUnifiedFormat(count, f);
		n += count;
		switch (role) {
		case Role::Int:
		case Role::Date:
		case Role::Decimal:
			return AppendIntegers(t, f, count);
		case Role::Code:
			if (vec.GetVectorType() == VectorType::DICTIONARY_VECTOR) {
				return AppendDictionaryCodes(f, count);
			}
			break;
		default:
			break;
		}
		for (idx_t r = 0; r < count; r++) {
			idx_t idx = f.sel->get_index(r);
			bool valid = f.validity.RowIsValid(idx);
			if (role == Role::Valid) {
				bytes.push_back(valid ? 1 : 0);
				continue;
			}
			if (!valid) {
				NullCell();
			}
			switch (role) {
			case Role::F64: {
				double d = 0.0;
				if (valid) {
					if (t.id() == LogicalTypeId::DOUBLE) {
						d = UnifiedVectorFormat::GetData<double>(f)[idx];
					} else if (t.id() == LogicalTypeId::FLOAT) {
						d = UnifiedVectorFormat::GetData<float>(f)[idx];
					} else if (t.id() == LogicalTypeId::DECIMAL) {
						i128 sv = Scaled(IntOf(t, f, idx, label));
						d = decimal_wide ? HugeToDouble(sv) : double(int64_t(sv));
					} else if (t.id() == LogicalTypeId::HUGEINT) {
						d = HugeToDouble(IntOf(t, f, idx, label));
					} else {
						i128 sv = IntOf(t, f, idx, label);
						d = t.id() == LogicalTypeId::UBIGINT ? double(uint64_t(sv)) : double(int64_t(sv));
					}
				}
				bytes.append(reinterpret_cast<const char *>(&d), 8);
				break;
			}
			case Role::Bool:
				bytes.push_back(valid && UnifiedVectorFormat::GetData<bool>(f)[idx] ? 1 : 0);
				break;
			case Role::String:
				if (valid) {
					auto sv = UnifiedVectorFormat::GetData<string_t>(f)[idx];
					PutStr(bytes, sv.GetData(), sv.GetSize());
				} else {
					PutStr(bytes, "", 0);
				}
				break;
			case Role::Code: {
				uint32_t code = 0;
				if (!valid) {
					null_seen = true;
				} else {
					code = CodeOf(UnifiedVectorFormat::GetData<string_t>(f)[idx]);
				}
				PutInt(code);
				break;
			}
			default:
				throw InternalException("Lemma: role %s in a scan", e.role);
			}
		}
	}
};

struct ScanResult {
	std::vector<std::string> buffers; // one per input entry (empty for rows entries)
	std::vector<LemmaCol> cols;
	int64_t scan_us = 0;
};

// Scan exactly the columns the manifest names, table by table, in the caller's transaction (its snapshot, its own uncommitted
// changes included: DataTable::Scan reads the transaction-local storage after the committed row groups), one thread, in row order.
ScanResult ScanInputs(ClientContext &context, const Manifest &m) {
	auto start = std::chrono::steady_clock::now();
	ScanResult res;
	res.buffers.resize(m.inputs.size());
	res.cols.resize(m.inputs.size());
	std::vector<std::unique_ptr<Encoder>> enc(m.inputs.size());
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
			auto en = make_uniq<Encoder>();
			en->e = e;
			en->label = rows.table + "." + e.column;
			if (e.role != "dict") {
				en->SetRole();
			}
			if (e.role == "dict") {
				continue; // filled from its codes field after the scan
			}
			if (e.role == "code") {
				en->target = TargetOf(e.rust_type);
				en->code_limit = e.rust_type == "u8" ? 256ull : e.rust_type == "u16" ? 65536ull : 4294967296ull;
			} else if (e.role == "int" || e.role == "date" || e.role == "decimal") {
				en->target = TargetOf(e.rust_type);
			}
			if (e.role == "decimal" || (e.role == "f64" && col.Type().id() == LogicalTypeId::DECIMAL)) {
				if (e.source_scale > e.scale) {
					throw InvalidInputException("Lemma: %s has more than %d fractional digits", en->label, e.scale);
				}
				en->mul = Pow10(e.scale - e.source_scale);
				en->decimal_wide = DecimalType::GetWidth(col.Type()) + (e.scale - e.source_scale) > 18;
			}
			enc[k] = std::move(en);
		}
		uint64_t total = 0;
		if (!ids.empty()) {
			TableScanState state;
			storage.InitializeScan(context, transaction, state, ids);
			DataChunk chunk;
			chunk.Initialize(Allocator::Get(context), types);
			while (true) {
				chunk.Reset();
				storage.Scan(transaction, chunk, state);
				if (chunk.size() == 0) {
					break;
				}
				total += chunk.size();
				for (size_t k = i + 1; k < end; k++) {
					if (enc[k]) {
						idx_t c = pos[entry.GetColumn(m.inputs[k].column).Name()];
						enc[k]->Append(types[c], chunk.data[c], chunk.size());
					}
				}
			}
		} else {
			// No column is read (e.g. COUNT(*)): count the rows visible to this transaction with a scan of the first column.
			auto &first = entry.GetColumns().GetColumn(PhysicalIndex(0));
			ids.emplace_back(first.StorageOid());
			TableScanState state;
			storage.InitializeScan(context, transaction, state, ids);
			DataChunk chunk;
			chunk.Initialize(Allocator::Get(context), {first.Type()});
			while (true) {
				chunk.Reset();
				storage.Scan(transaction, chunk, state);
				if (chunk.size() == 0) {
					break;
				}
				total += chunk.size();
			}
		}
		res.cols[i] = LemmaCol {nullptr, 0, total};
		for (size_t k = i + 1; k < end; k++) {
			const InEntry &e = m.inputs[k];
			if (e.role == "dict") {
				if (e.codes_of < 0 || size_t(e.codes_of) >= m.inputs.size() || !enc[size_t(e.codes_of)] ||
				    enc[size_t(e.codes_of)]->e.role != "code") {
					throw InvalidInputException("Lemma: %s.%s: the dictionary names no codes field", rows.table, e.column);
				}
				auto &src = *enc[size_t(e.codes_of)];
				std::vector<std::string> entries(src.entries.begin(), src.entries.end());
				if (entries.empty() && src.null_seen) {
					entries.emplace_back(""); // every cell is NULL: code 0 still has to index an entry
				}
				std::string out;
				for (auto &s : entries) {
					Encoder::PutStr(out, s.data(), s.size());
				}
				res.buffers[k] = std::move(out);
				res.cols[k] = LemmaCol {nullptr, 0, entries.size()};
			} else {
				res.buffers[k] = std::move(enc[k]->bytes);
				res.cols[k] = LemmaCol {nullptr, 0, enc[k]->n};
			}
		}
		i = end;
	}
	for (size_t k = 0; k < res.cols.size(); k++) {
		res.cols[k].data = reinterpret_cast<const uint8_t *>(res.buffers[k].data());
		res.cols[k].len = res.buffers[k].size();
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
	int32_t code = m.exec->run(in.cols.data(), in.cols.size(), abi_params.data(), abi_params.size(), &out);
	std::string bytes(reinterpret_cast<const char *>(out.ptr), size_t(out.len));
	m.exec->free_out(&out);
	if (code != 0) {
		throw InvalidInputException("Lemma: the proved executor refused the data (no rows returned): %s", bytes);
	}
	RunResult r;
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

	unique_ptr<FunctionData> Copy() const override {
		auto c = make_uniq<LemmaBindData>();
		c->manifest = manifest;
		c->sql = sql;
		c->params = params;
		c->from_optimizer = from_optimizer;
		return std::move(c);
	}
	bool Equals(const FunctionData &other) const override {
		auto &o = other.Cast<LemmaBindData>();
		if (manifest != o.manifest || sql != o.sql || params.size() != o.params.size()) {
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
	RunResult result;
	uint64_t next = 0;
};

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
	bind->manifest = std::shared_ptr<Manifest>(manifest.release());
	bind->sql = sql;
	return std::move(bind);
}

unique_ptr<GlobalTableFunctionState> LemmaQueryInit(ClientContext &context, TableFunctionInitInput &input) {
	auto &bind = input.bind_data->Cast<LemmaBindData>();
	auto start = std::chrono::steady_clock::now();
	auto scan = ScanInputs(context, *bind.manifest);
	auto state = make_uniq<LemmaGlobalState>();
	state->result = RunExecutor(*bind.manifest, scan, bind.params);
	LastQuery lq;
	lq.engine = "lemma";
	lq.reason = std::string("proved executor (") + bind.manifest->proof + ", git " + bind.manifest->git_sha + ")" +
	            (bind.from_optimizer ? " via lemma_mode" : " via lemma_query()");
	lq.key = bind.manifest->key;
	lq.sql = bind.sql;
	lq.scan_us = scan.scan_us;
	lq.load_us = state->result.load_us;
	lq.run_us = state->result.run_us;
	lq.rows = int64_t(state->result.rows);
	lq.total_us = MicrosSince(start);
	GetState(context).Record(lq);
	return std::move(state);
}

void LemmaQueryFunction(ClientContext &context, TableFunctionInput &data, DataChunk &output) {
	auto &bind = data.bind_data->Cast<LemmaBindData>();
	auto &state = data.global_state->Cast<LemmaGlobalState>();
	auto &r = state.result;
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
	f.to_string = LemmaQueryToString;
	return f;
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
	                          "In lemma_mode, run a query without a proved executor on DuckDB (labelled engine=duckdb in "
	                          "lemma_last_query()) instead of raising an error",
	                          LogicalType::BOOLEAN, Value::BOOLEAN(false));
	config.AddExtensionOption("lemma_enqueue_misses",
	                          "Write the SQL of a miss to ${lemma_home}/queue/<key>.sql for the offline `lemma optimize`",
	                          LogicalType::BOOLEAN, Value::BOOLEAN(false));
	config.AddExtensionOption("lemma_home", "Lemma's directory: executors/<key>/{lib.so,manifest.json,query.sql}, queue/",
	                          LogicalType::VARCHAR, Value(DefaultHome()));
	loader.RegisterFunction(LemmaQueryFunctionDef());
	TableFunction last("lemma_last_query", {}, LastQueryFunction, LastQueryBind, LastQueryInit);
	loader.RegisterFunction(last);
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
