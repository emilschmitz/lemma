// MEASUREMENT SPIKE, not product code (never linked into the extension, never on the default path).
//
// Question: how fast is "DuckDB's own parallel row-group scan (zone maps, pushed table filters, MVCC) + each DataChunk handed IN
// PLACE to a native kernel" against DuckDB's whole query, on fresh data (no Lemma input cache)?
//
// StreamTable below is the worker loop of lemma_extension.cpp ScanTable (same sources: committed row groups + transaction-local
// storage, same TableScanState, same pushed TableFilterSet and residual from a copy of PlanPushdown), minus every destination:
// no buffers, no staging, no packing, no dictionary renumbering. Per chunk the kernel reads the vectors through
// UnifiedVectorFormat / DictionaryVector and folds them into per-thread state; states are merged after the scan.
//
// Kernels are hand-written C++ (what a generated, proved kernel would compute; nothing here is proved):
//   q1 / q1k   TPC-H Q1 (pushed shipdate filter / filter evaluated branch-free in the kernel)
//   q6 / q6k   TPC-H Q6 (pushed filters / in-kernel)
//   uom, tag   SEC num: SELECT <key>, COUNT(*), SUM(value) FROM num GROUP BY <key>
//   scan_*     the same scan (columns, filters) with a trivial kernel: the pure scan floor
//   stats_*    vector types handed by DuckDB per column, dictionary memo efficacy
//
//   stream_spike <db> first <task>              one fresh DatabaseInstance, the task once (first touch of the buffer pool)
//   stream_spike <db> warm <reps> <task>...     every task once (warm + result check), then <reps> interleaved rounds
// Tasks: duck:<q> (DuckDB's SQL), stream:<q>, scan:<q>, stats:<q>. Settings: threads=8, memory_limit=8GB (lemma.toml measure).
#include "duckdb.hpp"
#include "duckdb/catalog/catalog.hpp"
#include "duckdb/catalog/catalog_entry/duck_table_entry.hpp"
#include "duckdb/catalog/catalog_entry/table_catalog_entry.hpp"
#include "duckdb/common/types/decimal.hpp"
#include "duckdb/common/types/hugeint.hpp"
#include "duckdb/common/operator/decimal_cast_operators.hpp"
#include "duckdb/storage/statistics/numeric_stats.hpp"
#include "duckdb/execution/expression_executor.hpp"
#include "duckdb/main/client_context.hpp"
#include "duckdb/optimizer/filter_pushdown.hpp"
#include "duckdb/optimizer/optimizer.hpp"
#include "duckdb/parser/keyword_helper.hpp"
#include "duckdb/parser/parser.hpp"
#include "duckdb/planner/binder.hpp"
#include "duckdb/planner/expression/bound_columnref_expression.hpp"
#include "duckdb/planner/expression/bound_conjunction_expression.hpp"
#include "duckdb/planner/expression/bound_reference_expression.hpp"
#include "duckdb/planner/expression_iterator.hpp"
#include "duckdb/planner/operator/logical_filter.hpp"
#include "duckdb/planner/operator/logical_get.hpp"
#include "duckdb/planner/table_filter.hpp"
#include "duckdb/storage/data_table.hpp"
#include "duckdb/storage/table/row_group.hpp"
#include "duckdb/storage/table/row_group_collection.hpp"
#include "duckdb/storage/table/scan_state.hpp"
#include "duckdb/transaction/duck_transaction.hpp"
#include "duckdb/transaction/local_storage.hpp"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <deque>
#include <functional>
#include <map>
#include <mutex>
#include <thread>
#include <unordered_map>

using namespace duckdb;
using i128 = __int128;

static const idx_t THREADS = 8;

// Profiling aid (no perf on this box): SPIKE_PART=1/2/3 stops the Q1 kernel after the key coding / the dense gather and slot
// list / the per-row products; in KeyAgg's dictionary path 2 = before the entry lookups, 1 = after them, 3 / 4 = hash only /
// nothing per entry. Results then differ from DuckDB's. Unset = the whole kernel.
static int SpikePart() {
	static const int part = getenv("SPIKE_PART") ? atoi(getenv("SPIKE_PART")) : 0;
	return part;
}

// ------------------------------------------------------------------------------------------------ pushed predicate (copy)

struct PushedScan {
	vector<StorageIndex> ids;
	vector<LogicalType> types;
	std::unordered_map<std::string, idx_t> pos;
	unique_ptr<TableFilterSet> filters;
	unique_ptr<Expression> residual;
	bool empty = false;
};

static unique_ptr<Expression> ToChunkRefs(unique_ptr<Expression> e, const std::map<std::pair<idx_t, idx_t>, idx_t> &chunk_col) {
	if (e->GetExpressionClass() == ExpressionClass::BOUND_COLUMN_REF) {
		auto &ref = e->Cast<BoundColumnRefExpression>();
		auto it = chunk_col.find({ref.binding.table_index, ref.binding.column_index});
		if (it == chunk_col.end()) {
			throw InternalException("spike: a pushed filter reads a column the scan does not produce");
		}
		return make_uniq<BoundReferenceExpression>(ref.return_type, it->second);
	}
	ExpressionIterator::EnumerateChildren(*e, [&](unique_ptr<Expression> &child) { child = ToChunkRefs(std::move(child), chunk_col); });
	return e;
}

// lemma_extension.cpp PlanPushdown, verbatim in substance; with an empty `where` the plain column list.
static PushedScan PlanScan(ClientContext &context, TableCatalogEntry &entry, const std::string &table,
                           const std::vector<std::string> &cols, const std::string &where) {
	PushedScan out;
	if (where.empty()) {
		for (auto &c : cols) {
			auto &col = entry.GetColumn(c);
			out.pos[c] = out.ids.size();
			out.ids.emplace_back(col.StorageOid());
			out.types.push_back(col.Type());
		}
		return out;
	}
	std::string q = "SELECT ";
	for (size_t i = 0; i < cols.size(); i++) {
		q += (i ? ", " : "") + KeywordHelper::WriteQuoted(cols[i], '"');
	}
	q += " FROM " + KeywordHelper::WriteQuoted(table, '"') + " WHERE " + where;
	Parser parser(context.GetParserOptions());
	parser.ParseQuery(q);
	auto binder = Binder::CreateBinder(context);
	auto bound = binder->Bind(*parser.statements[0]);
	Optimizer optimizer(*binder, context);
	optimizer.rewriter.VisitOperator(*bound.plan);
	FilterPushdown pushdown(optimizer);
	auto plan = pushdown.Rewrite(std::move(bound.plan));
	vector<unique_ptr<Expression>> kept;
	LogicalOperator *op = plan.get();
	while (op->type != LogicalOperatorType::LOGICAL_GET) {
		if (op->type == LogicalOperatorType::LOGICAL_EMPTY_RESULT) {
			out.empty = true;
			return out;
		}
		if (op->type == LogicalOperatorType::LOGICAL_FILTER) {
			for (auto &e : op->expressions) {
				kept.push_back(e->Copy());
			}
		} else if (op->type != LogicalOperatorType::LOGICAL_PROJECTION) {
			throw InvalidInputException("spike: unexpected plan %s", LogicalOperatorToString(op->type));
		}
		op = op->children[0].get();
	}
	auto &get = op->Cast<LogicalGet>();
	auto &column_ids = get.GetColumnIds();
	for (idx_t i = 0; i < column_ids.size(); i++) {
		auto &col = entry.GetColumn(LogicalIndex(column_ids[i].GetPrimaryIndex()));
		out.ids.emplace_back(col.StorageOid());
		out.types.push_back(col.Type());
		out.pos[col.Name()] = i;
	}
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

// ------------------------------------------------------------------------------------------------ StreamTable

struct Source {
	RowGroupCollection *collection = nullptr;
	ParallelCollectionScanState state;
	bool local = false;
};

// ScanTable's worker loop with the destinations removed: each worker owns a kernel `K` (a copy of `proto`), every chunk of every
// task it is handed goes to K::Chunk in place; the kernels are merged into `proto` after the join.
template <class K>
void StreamTable(ClientContext &context, DuckTransaction &transaction, DataTable &storage, PushedScan &ps, K &proto) {
	std::vector<std::unique_ptr<Source>> sources;
	auto committed = make_uniq<Source>();
	committed->collection = storage.GetRowGroupCollection().get();
	committed->collection->InitializeParallelScan(committed->state);
	uint64_t upper = committed->state.max_row - committed->state.row_groups->GetBaseRowId();
	sources.push_back(std::move(committed));
	auto local_storage = LocalStorage::Get(transaction).GetStorage(storage);
	if (local_storage && local_storage->GetCollection().GetTotalRows() > 0) {
		auto local = make_uniq<Source>();
		local->collection = &local_storage->GetCollection();
		local->local = true;
		local->collection->InitializeParallelScan(local->state);
		sources.push_back(std::move(local));
	}
	if (ps.empty) {
		return;
	}
	idx_t row_group_rows = MaxValue<idx_t>(1, storage.GetRowGroupSize());
	idx_t nthreads = MaxValue<idx_t>(1, MinValue<idx_t>(THREADS, upper / row_group_rows + sources.size()));
	std::vector<K> kernels(nthreads, proto);
	std::mutex err_lock;
	std::exception_ptr error;
	std::atomic<bool> stop {false};
	TableFilterSet *filters = ps.filters && !ps.filters->filters.empty() ? ps.filters.get() : nullptr;
	auto worker = [&](idx_t w) {
		try {
			K &k = kernels[w];
			TableScanState ts;
			ts.Initialize(ps.ids, &context, filters);
			DataChunk chunk;
			chunk.Initialize(Allocator::Get(context), ps.types);
			unique_ptr<ExpressionExecutor> keep;
			SelectionVector sel(STANDARD_VECTOR_SIZE);
			if (ps.residual) {
				keep = make_uniq<ExpressionExecutor>(context, *ps.residual);
			}
			for (auto &src : sources) {
				CollectionScanState &cs = src->local ? ts.local_state : ts.table_state;
				while (!stop.load() && src->collection->NextParallelScan(context, src->state, cs)) {
					while (true) {
						chunk.Reset();
						if (!cs.Scan(transaction, chunk) || chunk.size() == 0) {
							break;
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
						k.Chunk(chunk);
					}
				}
			}
		} catch (...) {
			std::lock_guard<std::mutex> g(err_lock);
			if (!error) {
				error = std::current_exception();
			}
			stop = true;
		}
	};
	std::vector<std::thread> pool;
	for (idx_t i = 1; i < nthreads; i++) {
		pool.emplace_back(worker, i);
	}
	worker(0);
	for (auto &t : pool) {
		t.join();
	}
	if (error) {
		std::rethrow_exception(error);
	}
	auto merge_start = std::chrono::steady_clock::now();
	K::MergeAll(proto, kernels);
	if (getenv("SPIKE_VERBOSE")) {
		fprintf(stderr, "  merge of %d thread states: %.2f ms\n", int(nthreads),
		        std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - merge_start).count());
	}
}

// ------------------------------------------------------------------------------------------------ helpers

static std::string DecStr(i128 v, int scale) {
	hugeint_t h;
	h.lower = uint64_t(v);
	h.upper = int64_t(v >> 64);
	return Decimal::ToString(h, 38, uint8_t(scale));
}

static std::string AvgStr(i128 sum, uint64_t count, int scale) { // DuckDB's IntegerAverageOperationHugeint::Finalize
	hugeint_t h;
	h.lower = uint64_t(sum);
	h.upper = int64_t(sum >> 64);
	long double v;
	Hugeint::TryCast(h, v);
	long double div = (long double)count;
	for (int i = 0; i < scale; i++) {
		div *= 10;
	}
	return Value::DOUBLE(double(v / div)).ToString();
}

// Fixed-width column of a chunk as a dense local array (the in-place pointer when flat, a gather through the selection else).
template <class T>
static const T *Dense(Vector &v, idx_t n, T *tmp) {
	if (v.GetVectorType() == VectorType::FLAT_VECTOR) {
		return FlatVector::GetData<T>(v);
	}
	UnifiedVectorFormat f;
	v.ToUnifiedFormat(n, f);
	auto d = UnifiedVectorFormat::GetData<T>(f);
	for (idx_t r = 0; r < n; r++) {
		tmp[r] = d[f.sel->get_index(r)];
	}
	return tmp;
}

static bool AllValid(Vector &v, idx_t n) {
	UnifiedVectorFormat f;
	v.ToUnifiedFormat(n, f);
	return f.validity.AllValid();
}

static inline uint64_t Mix(uint64_t h) {
	h ^= h >> 33;
	h *= 0xff51afd7ed558ccdULL;
	h ^= h >> 33;
	h *= 0xc4ceb3fe1a85ec53ULL;
	h ^= h >> 33;
	return h;
}

static inline uint64_t HashStr(const string_t &s) {
	uint32_t len = s.GetSize();
	if (s.IsInlined()) {
		uint64_t a, b;
		std::memcpy(&a, &s, 8);
		std::memcpy(&b, reinterpret_cast<const char *>(&s) + 8, 8);
		return Mix(a * 0x9E3779B97F4A7C15ULL ^ b);
	}
	const char *p = s.GetData();
	uint64_t h = len * 0x9E3779B97F4A7C15ULL;
	uint32_t i = 0;
	for (; i + 8 <= len; i += 8) {
		uint64_t w;
		std::memcpy(&w, p + i, 8);
		h = (h ^ Mix(w)) * 0x9E3779B97F4A7C15ULL;
	}
	if (i < len) {
		uint64_t w = 0;
		std::memcpy(&w, p + i, len - i);
		h = (h ^ Mix(w)) * 0x9E3779B97F4A7C15ULL;
	}
	return Mix(h);
}

static inline bool EqStr(const string_t &a, const string_t &b) {
	if (a.IsInlined()) {
		return std::memcmp(&a, &b, 16) == 0;
	}
	return std::memcmp(&a, &b, 8) == 0 && std::memcmp(a.GetData(), b.GetData(), a.GetSize()) == 0;
}

// String -> dense slot (0..n-1), per thread. NULL has its own slot. Long keys are copied into `arena` (deque: never moves).
struct StrTable {
	struct E {
		string_t key;
		uint64_t hash;
		int32_t slot;
	};
	std::vector<E> tab;
	uint64_t mask = 0;
	std::deque<std::string> arena;
	std::vector<string_t> keys; // slot -> key
	std::vector<uint64_t> hashes; // slot -> hash (0 for NULL)
	int32_t null_slot = -1;
	std::vector<bool> is_null;

	StrTable() {
		tab.assign(64, E {string_t(), 0, -1});
		mask = 63;
	}
	int32_t Size() const {
		return int32_t(keys.size());
	}
	int32_t Null() {
		if (null_slot < 0) {
			null_slot = Size();
			keys.emplace_back();
			hashes.push_back(0);
			is_null.push_back(true);
		}
		return null_slot;
	}
	void Grow() {
		std::vector<E> old;
		old.swap(tab);
		tab.assign(old.size() * 2, E {string_t(), 0, -1});
		mask = tab.size() - 1;
		for (auto &e : old) {
			if (e.slot >= 0) {
				uint64_t i = e.hash & mask;
				while (tab[i].slot >= 0) {
					i = (i + 1) & mask;
				}
				tab[i] = e;
			}
		}
	}
	int32_t Find(const string_t &s) {
		return Find(s, HashStr(s));
	}
	int32_t Lookup(const string_t &s) const { // read-only: the slot, or -1
		uint64_t h = HashStr(s);
		for (uint64_t i = h & mask;; i = (i + 1) & mask) {
			const E &e = tab[i];
			if (e.slot < 0) {
				return -1;
			}
			if (e.hash == h && EqStr(e.key, s)) {
				return e.slot;
			}
		}
	}
	int32_t Find(const string_t &s, uint64_t h) {
		uint64_t i = h & mask;
		while (true) {
			E &e = tab[i];
			if (e.slot < 0) {
				break;
			}
			if (e.hash == h && EqStr(e.key, s)) {
				return e.slot;
			}
			i = (i + 1) & mask;
		}
		string_t key = s;
		if (!s.IsInlined()) {
			arena.emplace_back(s.GetData(), s.GetSize());
			key = string_t(arena.back().data(), uint32_t(arena.back().size()));
		}
		int32_t slot = Size();
		tab[i] = E {key, h, slot};
		keys.push_back(key);
		hashes.push_back(h);
		is_null.push_back(false);
		if (uint64_t(keys.size()) * 2 > tab.size()) {
			Grow();
		}
		return slot;
	}
	std::string KeyStr(int32_t slot) const {
		return is_null[slot] ? std::string("NULL") : keys[slot].GetString();
	}
};

// Per-chunk codes of a VARCHAR column. DICTIONARY vector with a known size: each dictionary entry is looked up once (memo,
// reused across chunks with the same dictionary id and size); else a lookup per row with a previous-row shortcut.
struct StrCoder {
	StrTable table;
	std::vector<int32_t> memo;
	std::string memo_id;
	idx_t memo_size = 0;
	bool memo_full = false;
	uint64_t lookups = 0, rows = 0;

	void Code(Vector &v, idx_t n, int32_t *out) {
		rows += n;
		if (v.GetVectorType() == VectorType::DICTIONARY_VECTOR && DictionaryVector::DictionarySize(v).IsValid() &&
		    DictionaryVector::Child(v).GetVectorType() == VectorType::FLAT_VECTOR) {
			idx_t dsize = DictionaryVector::DictionarySize(v).GetIndex();
			auto &id = DictionaryVector::DictionaryId(v);
			auto &child = DictionaryVector::Child(v);
			auto data = FlatVector::GetData<string_t>(child);
			auto &valid = FlatVector::Validity(child);
			auto &sel = DictionaryVector::SelVector(v);
			if (id.empty() || id != memo_id || dsize != memo_size) {
				memo.assign(dsize, -1);
				memo_id = id;
				memo_size = dsize;
				memo_full = dsize <= n; // a small dictionary: code every entry now, then the rows are a plain gather
				if (memo_full) {
					for (idx_t i = 0; i < dsize; i++) {
						lookups++;
						memo[i] = valid.RowIsValid(i) ? table.Find(data[i]) : table.Null();
					}
				}
			}
			if (memo_full) {
				const int32_t *m = memo.data();
				if (sel.IsSet()) {
					const sel_t *s = sel.data();
					for (idx_t r = 0; r < n; r++) {
						out[r] = m[s[r]];
					}
				} else {
					std::memcpy(out, m, n * sizeof(int32_t));
				}
				return;
			}
			for (idx_t r = 0; r < n; r++) {
				idx_t i = sel.get_index(r);
				int32_t c = memo[i];
				if (c < 0) {
					lookups++;
					c = memo[i] = valid.RowIsValid(i) ? table.Find(data[i]) : table.Null();
				}
				out[r] = c;
			}
			return;
		}
		memo_size = 0;
		memo_id.clear();
		if (v.GetVectorType() == VectorType::CONSTANT_VECTOR) {
			lookups++;
			int32_t c = ConstantVector::IsNull(v) ? table.Null() : table.Find(ConstantVector::GetData<string_t>(v)[0]);
			for (idx_t r = 0; r < n; r++) {
				out[r] = c;
			}
			return;
		}
		UnifiedVectorFormat f;
		v.ToUnifiedFormat(n, f);
		auto data = UnifiedVectorFormat::GetData<string_t>(f);
		string_t prev;
		int32_t prev_c = -1;
		for (idx_t r = 0; r < n; r++) {
			idx_t i = f.sel->get_index(r);
			if (!f.validity.RowIsValid(i)) {
				out[r] = table.Null();
				continue;
			}
			const string_t &s = data[i];
			if (prev_c >= 0 && EqStr(prev, s)) {
				out[r] = prev_c;
				continue;
			}
			lookups++;
			prev = s;
			prev_c = out[r] = table.Find(s);
		}
	}
};

// ------------------------------------------------------------------------------------------------ kernels

template <class K>
struct SerialMerge {
	static void MergeAll(K &proto, std::vector<K> &ks) {
		for (auto &k : ks) {
			proto.Merge(k);
		}
	}
};

// TPC-H Q1. Inputs DECIMAL(15,2) (int64, scale 2). disc_price = p*(100-d) (scale 4), charge = p*(100-d)*(100+t) (scale 6):
// one row's values fit int64 for these types' TPC-H domain only per chunk sums; per-chunk int64 partials (2048 rows) are flushed
// into int128 per chunk, with an overflow check on the per-row product range.
struct Q1 : SerialMerge<Q1> {
	static constexpr int MAXG = 16;
	bool kernel_filter = false;
	int32_t cutoff = 0; // l_shipdate <= cutoff (days), kernel_filter only
	idx_t c_rf = 0, c_ls = 0, c_q = 0, c_p = 0, c_d = 0, c_t = 0, c_sd = 0;
	StrCoder rf, ls;
	struct Acc {
		i128 q = 0, p = 0, d = 0, dp = 0, ch = 0;
		uint64_t n = 0;
	} acc[MAXG * MAXG];
	uint64_t slow_chunks = 0;

	void Chunk(DataChunk &c) {
		idx_t n = c.size();
		int32_t a[STANDARD_VECTOR_SIZE], b[STANDARD_VECTOR_SIZE];
		int64_t tq[STANDARD_VECTOR_SIZE], tp[STANDARD_VECTOR_SIZE], td[STANDARD_VECTOR_SIZE], tt[STANDARD_VECTOR_SIZE];
		int32_t tsd[STANDARD_VECTOR_SIZE];
		uint8_t slot[STANDARD_VECTOR_SIZE];
		rf.Code(c.data[c_rf], n, a);
		ls.Code(c.data[c_ls], n, b);
		if (SpikePart() == 1) {
			return;
		}
		if (!AllValid(c.data[c_q], n) || !AllValid(c.data[c_p], n) || !AllValid(c.data[c_d], n) || !AllValid(c.data[c_t], n)) {
			throw InvalidInputException("spike Q1: NULL input");
		}
		const int64_t *q = Dense<int64_t>(c.data[c_q], n, tq);
		const int64_t *p = Dense<int64_t>(c.data[c_p], n, tp);
		const int64_t *d = Dense<int64_t>(c.data[c_d], n, td);
		const int64_t *t = Dense<int64_t>(c.data[c_t], n, tt);
		const int32_t *sd = kernel_filter ? reinterpret_cast<const int32_t *>(Dense<date_t>(c.data[c_sd], n, reinterpret_cast<date_t *>(tsd))) : nullptr;
		uint8_t list[MAXG * MAXG];
		int nlist = 0;
		for (idx_t r = 0; r < n; r++) {
			if (a[r] >= MAXG || b[r] >= MAXG) {
				throw InvalidInputException("spike Q1: more than 16 distinct keys");
			}
			slot[r] = uint8_t(a[r] * MAXG + b[r]);
		}
		// distinct slots of the chunk (few: one masked pass per slot, branch-free and vectorizable)
		static thread_local bool mark[MAXG * MAXG];
		for (idx_t r = 0; r < n; r++) {
			if (!mark[slot[r]]) {
				mark[slot[r]] = true;
				list[nlist++] = slot[r];
			}
		}
		for (int i = 0; i < nlist; i++) {
			mark[list[i]] = false;
		}
		// Per-chunk range check, no catalog assumption: with 0 <= q, p < 2^32 / 100 and 0 <= d, t <= 100 every product below is
		// exact in 32 x 32 -> 64-bit unsigned arithmetic (AVX2 vpmuludq) and a chunk's sums fit 64 bits. Else the exact int128 path.
		if (SpikePart() == 2) {
			return;
		}
		// (an OR of compares, not min/max: AVX2 has no 64-bit min/max, and GCC does not vectorize that reduction)
		int64_t bad = 0;
		for (idx_t r = 0; r < n; r++) {
			bad |= (q[r] < 0) | (q[r] >= 42949672) | (p[r] < 0) | (p[r] >= 42949672) | (d[r] < 0) | (d[r] > 100) | (t[r] < 0) |
			       (t[r] > 100);
		}
		if (bad) {
			slow_chunks++;
			for (idx_t r = 0; r < n; r++) {
				if (kernel_filter && sd[r] > cutoff) {
					continue;
				}
				Acc &x = acc[slot[r]];
				i128 dp = i128(p[r]) * (100 - i128(d[r]));
				x.q += q[r], x.p += p[r], x.d += d[r], x.dp += dp, x.ch += dp * (100 + i128(t[r])), x.n++;
			}
			return;
		}
		uint64_t dp[STANDARD_VECTOR_SIZE], ch[STANDARD_VECTOR_SIZE], keep[STANDARD_VECTOR_SIZE];
		for (idx_t r = 0; r < n; r++) {
			uint32_t v = uint32_t(p[r]) * uint32_t(100 - d[r]);
			dp[r] = v;
			ch[r] = uint64_t(v) * uint64_t(uint32_t(100 + t[r]));
			keep[r] = kernel_filter ? uint64_t(0) - uint64_t(sd[r] <= cutoff) : ~uint64_t(0);
		}
		if (SpikePart() == 3) {
			return;
		}
		for (int i = 0; i < nlist; i++) {
			uint8_t s = list[i];
			uint64_t sq = 0, sp = 0, sdisc = 0, sdp = 0, sch = 0, cnt = 0;
			for (idx_t r = 0; r < n; r++) {
				uint64_t m = keep[r] & (uint64_t(0) - uint64_t(slot[r] == s));
				sq += uint64_t(q[r]) & m;
				sp += uint64_t(p[r]) & m;
				sdisc += uint64_t(d[r]) & m;
				sdp += dp[r] & m;
				sch += ch[r] & m;
				cnt += m & 1;
			}
			Acc &x = acc[s];
			x.q += sq, x.p += sp, x.d += sdisc, x.dp += sdp, x.ch += sch, x.n += cnt;
		}
	}
	void Merge(Q1 &o) {
		// remap o's slots through this kernel's tables
		for (int i = 0; i < MAXG * MAXG; i++) {
			Acc &x = o.acc[i];
			if (x.n == 0) {
				continue;
			}
			int32_t ga = o.rf.table.is_null[i / MAXG] ? rf.table.Null() : rf.table.Find(o.rf.table.keys[i / MAXG]);
			int32_t gb = o.ls.table.is_null[i % MAXG] ? ls.table.Null() : ls.table.Find(o.ls.table.keys[i % MAXG]);
			Acc &y = acc[ga * MAXG + gb];
			y.q += x.q;
			y.p += x.p;
			y.d += x.d;
			y.dp += x.dp;
			y.ch += x.ch;
			y.n += x.n;
		}
	}
	std::vector<std::string> Rows() {
		std::vector<std::string> out;
		for (int i = 0; i < MAXG * MAXG; i++) {
			Acc &x = acc[i];
			if (x.n == 0) {
				continue;
			}
			out.push_back(rf.table.KeyStr(i / MAXG) + "|" + ls.table.KeyStr(i % MAXG) + "|" + DecStr(x.q, 2) + "|" + DecStr(x.p, 2) +
			              "|" + DecStr(x.dp, 4) + "|" + DecStr(x.ch, 6) + "|" + AvgStr(x.q, x.n, 2) + "|" + AvgStr(x.p, x.n, 2) + "|" +
			              AvgStr(x.d, x.n, 2) + "|" + std::to_string(x.n));
		}
		return out;
	}
};

// TPC-H Q6: SUM(price * disc), scale 4. kernel_filter: the four predicates branch-free in the kernel; else DuckDB's scan applied
// them (pushed table filters) and every handed row qualifies.
struct Q6 : SerialMerge<Q6> {
	bool kernel_filter = false;
	int32_t lo = 0, hi = 0; // shipdate in [lo, hi)
	uint64_t slow_chunks = 0;
	idx_t c_p = 0, c_d = 0, c_q = 0, c_sd = 0;
	i128 sum = 0;
	void Chunk(DataChunk &c) {
		idx_t n = c.size();
		int64_t tp[STANDARD_VECTOR_SIZE], td[STANDARD_VECTOR_SIZE], tq[STANDARD_VECTOR_SIZE];
		int32_t tsd[STANDARD_VECTOR_SIZE];
		if (!AllValid(c.data[c_p], n) || !AllValid(c.data[c_d], n)) {
			throw InvalidInputException("spike Q6: NULL input");
		}
		const int64_t *p = Dense<int64_t>(c.data[c_p], n, tp);
		const int64_t *d = Dense<int64_t>(c.data[c_d], n, td);
		// Per-chunk range check (no catalog assumption): 0 <= p, d < 2^26 makes p * d exact in 32 x 32 -> 64 bits (vpmuludq)
		// and a chunk's sum of 2048 products < 2^63. Else the exact int128 path.
		int64_t bad = 0;
		for (idx_t r = 0; r < n; r++) {
			bad |= (p[r] < 0) | (p[r] >= (int64_t(1) << 26)) | (d[r] < 0) | (d[r] >= (int64_t(1) << 26));
		}
		const int64_t *q = nullptr;
		const int32_t *sd = nullptr;
		if (kernel_filter) {
			q = Dense<int64_t>(c.data[c_q], n, tq);
			sd = reinterpret_cast<const int32_t *>(Dense<date_t>(c.data[c_sd], n, reinterpret_cast<date_t *>(tsd)));
		}
		if (bad) {
			slow_chunks++;
			for (idx_t r = 0; r < n; r++) {
				if (!kernel_filter || ((sd[r] >= lo) & (sd[r] < hi) & (d[r] >= 5) & (d[r] <= 7) & (q[r] < 2400))) {
					sum += i128(p[r]) * d[r];
				}
			}
			return;
		}
		uint64_t s = 0;
		if (kernel_filter) {
			for (idx_t r = 0; r < n; r++) {
				uint64_t m = uint64_t(0) - uint64_t((sd[r] >= lo) & (sd[r] < hi) & (d[r] >= 5) & (d[r] <= 7) & (q[r] < 2400));
				s += (uint64_t(uint32_t(p[r])) * uint64_t(uint32_t(d[r]))) & m;
			}
		} else {
			for (idx_t r = 0; r < n; r++) {
				s += uint64_t(uint32_t(p[r])) * uint64_t(uint32_t(d[r]));
			}
		}
		sum += s;
	}
	void Merge(Q6 &o) {
		sum += o.sum;
	}
	std::vector<std::string> Rows() {
		return {DecStr(sum, 4)};
	}
};

// SELECT key, COUNT(*), SUM(value) FROM num GROUP BY key; value DECIMAL(38,4) (int128). Two phases, as DuckDB's radix hash
// aggregate, but fed by dictionary entries instead of rows:
//  1. per thread, per DICTIONARY vector (DuckDB hands one per dictionary-compressed segment, the same dictionary id for all the
//     segment's chunks): rows are aggregated per dictionary entry in small local arrays (L2-resident). The first time an entry is
//     touched its string is hashed and copied into one of 64 radix partitions (by hash) as a record; when the dictionary changes the
//     entry totals are written into their records. A non-dictionary vector: one record per run of equal keys.
//  2. after the scan, the 64 partitions are aggregated in parallel, each into a small hash table (about 1/64 of the keys).
struct KeyAgg {
	static constexpr int RBITS = 6, NPART = 1 << RBITS;
	static constexpr uint32_t NULL_LEN = UINT32_MAX;
	idx_t c_k = 0, c_v = 0;
	struct Rec {
		uint64_t hash;
		uint32_t len, off; // the key's bytes in the bucket's arena; len NULL_LEN: the NULL key
		int64_t cnt;
		uint64_t nn;
		i128 sum;
	};
	struct Bucket {
		std::vector<Rec> recs;
		std::vector<char> bytes;
	};
	std::vector<Bucket> buckets;
	// the current dictionary
	std::string cur_id;
	idx_t cur_size = 0;
	std::vector<uint32_t> memo; // entry -> (partition << 26 | record index) + 1, 0 = untouched
	std::vector<int64_t> lcnt;
	std::vector<i128> lsum;
	std::vector<uint64_t> lnn;
	std::vector<uint32_t> touched;
	uint64_t lookups = 0;

	KeyAgg() : buckets(NPART) {
	}
	static void Add(i128 &acc, i128 x) {
		if (__builtin_add_overflow(acc, x, &acc)) {
			throw InvalidInputException("spike: SUM overflow");
		}
	}
	static i128 Of(const hugeint_t &h) {
		return (i128(h.upper) << 64) | i128(h.lower);
	}
	uint32_t NewRec(const string_t *s) {
		lookups++;
		uint64_t h = s ? HashStr(*s) : 0;
		uint32_t p = uint32_t(h >> (64 - RBITS));
		Bucket &b = buckets[p];
		Rec r {h, NULL_LEN, 0, 0, 0, 0};
		if (s) {
			r.len = s->GetSize();
			r.off = uint32_t(b.bytes.size());
			b.bytes.insert(b.bytes.end(), s->GetData(), s->GetData() + r.len);
		}
		if (b.recs.size() >= (1u << 26) || b.bytes.size() >= UINT32_MAX) {
			throw InvalidInputException("spike: radix bucket full");
		}
		b.recs.push_back(r);
		return (p << 26 | uint32_t(b.recs.size() - 1)) + 1;
	}
	Rec &RecOf(uint32_t m) {
		m--;
		return buckets[m >> 26].recs[m & ((1u << 26) - 1)];
	}
	void Flush() {
		for (auto i : touched) {
			Rec &r = RecOf(memo[i]);
			r.cnt += lcnt[i];
			r.nn += lnn[i];
			Add(r.sum, lsum[i]);
			lcnt[i] = 0, lnn[i] = 0, lsum[i] = 0;
		}
		touched.clear();
		cur_size = 0;
		cur_id.clear();
	}
	void Chunk(DataChunk &c) {
		idx_t n = c.size();
		Vector &kv = c.data[c_k];
		Vector &vv = c.data[c_v];
		UnifiedVectorFormat f;
		vv.ToUnifiedFormat(n, f);
		auto v = UnifiedVectorFormat::GetData<hugeint_t>(f);
		bool all_valid = f.validity.AllValid();
		if (kv.GetVectorType() == VectorType::DICTIONARY_VECTOR && DictionaryVector::DictionarySize(kv).IsValid() &&
		    !DictionaryVector::DictionaryId(kv).empty() && DictionaryVector::Child(kv).GetVectorType() == VectorType::FLAT_VECTOR) {
			idx_t dsize = DictionaryVector::DictionarySize(kv).GetIndex();
			auto &id = DictionaryVector::DictionaryId(kv);
			if (id != cur_id || dsize != cur_size) {
				Flush();
				cur_id = id;
				cur_size = dsize;
				memo.assign(dsize, 0);
				if (lcnt.size() < dsize) {
					lcnt.resize(dsize, 0), lsum.resize(dsize, 0), lnn.resize(dsize, 0);
				}
			}
			auto &child = DictionaryVector::Child(kv);
			auto data = FlatVector::GetData<string_t>(child);
			auto &valid = FlatVector::Validity(child);
			auto &sel = DictionaryVector::SelVector(kv);
			if (SpikePart() == 2) {
				return;
			}
			for (idx_t r = 0; r < n; r++) {
				idx_t i = sel.get_index(r);
				if (memo[i] == 0) {
					if (SpikePart() >= 3) {
						memo[i] = 1 + (SpikePart() == 3 ? uint32_t(HashStr(data[i]) & 1) : 0);
						continue;
					}
					memo[i] = NewRec(valid.RowIsValid(i) ? &data[i] : nullptr);
					touched.push_back(uint32_t(i));
				}
			}
			if (SpikePart() >= 1) {
				return;
			}
			for (idx_t r = 0; r < n; r++) {
				idx_t i = sel.get_index(r);
				idx_t vi = f.sel->get_index(r);
				lcnt[i]++;
				if (all_valid || f.validity.RowIsValid(vi)) {
					lnn[i]++;
					Add(lsum[i], Of(v[vi]));
				}
			}
			return;
		}
		Flush();
		UnifiedVectorFormat kf;
		kv.ToUnifiedFormat(n, kf);
		auto keys = UnifiedVectorFormat::GetData<string_t>(kf);
		Rec *cur = nullptr;
		const string_t *prev = nullptr;
		for (idx_t r = 0; r < n; r++) {
			idx_t ki = kf.sel->get_index(r);
			const string_t *k = kf.validity.RowIsValid(ki) ? &keys[ki] : nullptr;
			bool same = cur && ((k == nullptr && prev == nullptr) || (k && prev && EqStr(*k, *prev)));
			if (!same) {
				cur = &RecOf(NewRec(k)); // (a bucket's vector may grow on a later NewRec: cur is re-taken every new run)
				prev = k;
			}
			idx_t vi = f.sel->get_index(r);
			cur->cnt++;
			if (f.validity.RowIsValid(vi)) {
				cur->nn++;
				Add(cur->sum, Of(v[vi]));
			}
		}
	}
	struct Part {
		StrTable table;
		std::vector<int64_t> cnt;
		std::vector<i128> sum;
		std::vector<uint64_t> nonnull;
	};
	std::vector<Part> parts;
	static void MergeAll(KeyAgg &proto, std::vector<KeyAgg> &ks) {
		for (auto &k : ks) {
			k.Flush();
		}
		proto.parts.resize(NPART);
		std::atomic<int> next {0};
		auto merge = [&]() {
			for (int p = next++; p < NPART; p = next++) {
				Part &out = proto.parts[p];
				for (auto &k : ks) {
					Bucket &b = k.buckets[p];
					for (auto &r : b.recs) {
						if (r.cnt == 0) {
							continue;
						}
						int32_t g = r.len == NULL_LEN ? out.table.Null()
						                              : out.table.Find(string_t(b.bytes.data() + r.off, r.len), r.hash);
						if (out.cnt.size() <= idx_t(g)) {
							out.cnt.resize(g + 1, 0), out.sum.resize(g + 1, 0), out.nonnull.resize(g + 1, 0);
						}
						out.cnt[g] += r.cnt;
						out.nonnull[g] += r.nn;
						Add(out.sum[g], r.sum);
					}
				}
			}
		};
		std::vector<std::thread> pool;
		std::exception_ptr error;
		std::mutex lock;
		for (size_t t = 0; t < THREADS; t++) {
			pool.emplace_back([&]() {
				try {
					merge();
				} catch (...) {
					std::lock_guard<std::mutex> g(lock);
					error = std::current_exception();
				}
			});
		}
		for (auto &t : pool) {
			t.join();
		}
		if (error) {
			std::rethrow_exception(error);
		}
	}
	std::vector<std::string> Rows() {
		std::vector<std::string> out;
		for (auto &p : parts) {
			for (int32_t s = 0; s < p.table.Size(); s++) {
				out.push_back(p.table.KeyStr(s) + "|" + std::to_string(p.cnt[s]) + "|" + (p.nonnull[s] ? DecStr(p.sum[s], 4) : "NULL"));
			}
		}
		return out;
	}
};

// Scan floor: the same scan; per chunk every column's unified format is taken and one fixed-width column is summed.
struct ScanOnly : SerialMerge<ScanOnly> {
	std::vector<idx_t> cols;
	idx_t c_sum = 0;
	bool huge = false, small = false; // hugeint / int32 checksum column (else int64)
	int64_t sum = 0;
	uint64_t rows = 0;
	void Chunk(DataChunk &c) {
		idx_t n = c.size();
		rows += n;
		for (auto ci : cols) {
			UnifiedVectorFormat f;
			c.data[ci].ToUnifiedFormat(n, f);
		}
		UnifiedVectorFormat f;
		c.data[c_sum].ToUnifiedFormat(n, f);
		int64_t s = 0;
		if (huge) {
			auto d = UnifiedVectorFormat::GetData<hugeint_t>(f);
			for (idx_t r = 0; r < n; r++) {
				s += int64_t(d[f.sel->get_index(r)].lower);
			}
		} else if (small) {
			auto d = UnifiedVectorFormat::GetData<int32_t>(f);
			for (idx_t r = 0; r < n; r++) {
				s += d[f.sel->get_index(r)];
			}
		} else {
			auto d = UnifiedVectorFormat::GetData<int64_t>(f);
			for (idx_t r = 0; r < n; r++) {
				s += d[f.sel->get_index(r)];
			}
		}
		sum += s;
	}
	void Merge(ScanOnly &o) {
		sum += o.sum;
		rows += o.rows;
	}
	std::vector<std::string> Rows() {
		return {std::to_string(rows) + " rows, checksum " + std::to_string(sum)};
	}
};

// Vector types per column.
struct Stats : SerialMerge<Stats> {
	std::vector<idx_t> cols;
	std::vector<std::string> names;
	struct Col {
		uint64_t flat = 0, fsst = 0, constant = 0, dict = 0, dict_sized = 0, dict_id = 0, dict_same_id = 0, sequence = 0;
		uint64_t dict_size_sum = 0, rows_dict = 0, rows = 0;
		std::string last_id;
		StrCoder coder;
	};
	std::vector<Col> st;
	uint64_t chunks = 0;
	void Chunk(DataChunk &c) {
		chunks++;
		if (st.size() < cols.size()) {
			st.resize(cols.size());
		}
		idx_t n = c.size();
		for (size_t i = 0; i < cols.size(); i++) {
			Vector &v = c.data[cols[i]];
			Col &s = st[i];
			s.rows += n;
			switch (v.GetVectorType()) {
			case VectorType::FLAT_VECTOR:
				s.flat++;
				break;
			case VectorType::FSST_VECTOR:
				s.fsst++;
				break;
			case VectorType::CONSTANT_VECTOR:
				s.constant++;
				break;
			case VectorType::SEQUENCE_VECTOR:
				s.sequence++;
				break;
			case VectorType::DICTIONARY_VECTOR: {
				s.dict++;
				s.rows_dict += n;
				auto size = DictionaryVector::DictionarySize(v);
				if (size.IsValid()) {
					s.dict_sized++;
					s.dict_size_sum += size.GetIndex();
				}
				auto &id = DictionaryVector::DictionaryId(v);
				if (!id.empty()) {
					s.dict_id++;
					if (id == s.last_id) {
						s.dict_same_id++;
					}
					s.last_id = id;
				}
				break;
			}
			}
			if (v.GetType().id() == LogicalTypeId::VARCHAR) {
				int32_t out[STANDARD_VECTOR_SIZE];
				s.coder.Code(v, n, out);
			}
		}
	}
	void Merge(Stats &o) {
		chunks += o.chunks;
		if (st.size() < o.st.size()) {
			st.resize(o.st.size());
		}
		for (size_t i = 0; i < o.st.size(); i++) {
			Col &a = st[i], &b = o.st[i];
			a.flat += b.flat, a.fsst += b.fsst, a.constant += b.constant, a.dict += b.dict, a.dict_sized += b.dict_sized;
			a.dict_id += b.dict_id, a.dict_same_id += b.dict_same_id, a.sequence += b.sequence, a.dict_size_sum += b.dict_size_sum;
			a.rows_dict += b.rows_dict, a.rows += b.rows;
			a.coder.lookups += b.coder.lookups, a.coder.rows += b.coder.rows;
		}
	}
	std::vector<std::string> Rows() {
		std::vector<std::string> out;
		for (size_t i = 0; i < st.size(); i++) {
			Col &s = st[i];
			char buf[512];
			snprintf(buf, sizeof buf,
			         "%s: chunks flat=%llu fsst=%llu constant=%llu dictionary=%llu (with size %llu, avg size %.1f, with id %llu, id "
			         "same as previous chunk %llu) sequence=%llu; rows=%llu; string lookups with memo=%llu (%.4f per row)",
			         names[i].c_str(), (unsigned long long)s.flat, (unsigned long long)s.fsst, (unsigned long long)s.constant,
			         (unsigned long long)s.dict, (unsigned long long)s.dict_sized,
			         s.dict_sized ? double(s.dict_size_sum) / s.dict_sized : 0.0, (unsigned long long)s.dict_id,
			         (unsigned long long)s.dict_same_id, (unsigned long long)s.sequence, (unsigned long long)s.rows,
			         (unsigned long long)s.coder.lookups, s.coder.rows ? double(s.coder.lookups) / s.coder.rows : 0.0);
			out.push_back(buf);
		}
		return out;
	}
};

// ------------------------------------------------------------------------------------------------ joins (build + streamed probe)

// Per-chunk int32 code of a VARCHAR column through `fn` (NULL -> null_code). A DICTIONARY vector is coded once per dictionary
// entry, the memo carried across chunks with the same dictionary id and size; other vectors per row with a previous-row shortcut.
struct StrMap {
	std::function<int32_t(const string_t &)> fn;
	int32_t null_code = -1;
	std::vector<int32_t> memo;
	std::string id;
	idx_t size = 0;
	uint64_t calls = 0, rows = 0, dict_chunks = 0, chunks = 0;
	void Code(Vector &v, idx_t n, int32_t *out) {
		rows += n;
		chunks++;
		if (v.GetVectorType() == VectorType::DICTIONARY_VECTOR && DictionaryVector::DictionarySize(v).IsValid() &&
		    DictionaryVector::Child(v).GetVectorType() == VectorType::FLAT_VECTOR) {
			dict_chunks++;
			idx_t dsize = DictionaryVector::DictionarySize(v).GetIndex();
			auto &did = DictionaryVector::DictionaryId(v);
			if (did.empty() || did != id || dsize != size) {
				memo.assign(dsize, INT32_MIN);
				id = did;
				size = dsize;
			}
			auto &child = DictionaryVector::Child(v);
			auto data = FlatVector::GetData<string_t>(child);
			auto &valid = FlatVector::Validity(child);
			auto &sel = DictionaryVector::SelVector(v);
			for (idx_t r = 0; r < n; r++) {
				idx_t i = sel.get_index(r);
				int32_t c = memo[i];
				if (c == INT32_MIN) {
					calls++;
					c = memo[i] = valid.RowIsValid(i) ? fn(data[i]) : null_code;
				}
				out[r] = c;
			}
			return;
		}
		size = 0;
		id.clear();
		if (v.GetVectorType() == VectorType::CONSTANT_VECTOR) {
			calls++;
			int32_t c = ConstantVector::IsNull(v) ? null_code : fn(ConstantVector::GetData<string_t>(v)[0]);
			for (idx_t r = 0; r < n; r++) {
				out[r] = c;
			}
			return;
		}
		UnifiedVectorFormat f;
		v.ToUnifiedFormat(n, f);
		auto data = UnifiedVectorFormat::GetData<string_t>(f);
		const string_t *prev = nullptr;
		int32_t prev_c = 0;
		for (idx_t r = 0; r < n; r++) {
			idx_t i = f.sel->get_index(r);
			if (!f.validity.RowIsValid(i)) {
				out[r] = null_code;
				continue;
			}
			if (prev && EqStr(*prev, data[i])) {
				out[r] = prev_c;
				continue;
			}
			calls++;
			prev = &data[i];
			prev_c = out[r] = fn(data[i]);
		}
	}
};

static bool StrIs(const string_t &s, const char *lit) {
	size_t len = strlen(lit);
	return s.GetSize() == len && std::memcmp(s.GetData(), lit, len) == 0;
}

// Two 4-bit counters per integer key (a = low nibble, b = high nibble), exact up to 15 rows per key and counter (more: loud
// failure). Dense: a byte per key over the key range DuckDB's column statistics give (a bound of every stored value), filled by
// all build threads at once with byte CAS. Hash: open addressing over the collected build rows, built by one thread.
struct DenseNibbles {
	int64_t min = 0;
	uint64_t range = 0;
	std::vector<uint8_t> cells;
	void Add(int64_t key, int which) {
		uint64_t o = uint64_t(key) - uint64_t(min);
		if (key < min || o >= range) {
			throw InvalidInputException("spike: build key %d outside the column statistics' range", key);
		}
		uint8_t *c = &cells[o];
		uint8_t old = __atomic_load_n(c, __ATOMIC_RELAXED), nw;
		do {
			uint8_t nib = which ? old >> 4 : old & 15;
			if (nib == 15) {
				throw InvalidInputException("spike: more than 15 build rows for one key");
			}
			nw = uint8_t(old + (which ? 16 : 1));
		} while (!__atomic_compare_exchange_n(c, &old, nw, true, __ATOMIC_RELAXED, __ATOMIC_RELAXED));
	}
	inline uint8_t Get(int64_t key) const {
		uint64_t o = uint64_t(key) - uint64_t(min);
		return o < range ? cells[o] : 0;
	}
};

struct HashNibbles {
	std::vector<int64_t> keys;
	std::vector<uint8_t> vals; // 0 = empty slot (an inserted key always has a nonzero count)
	uint64_t mask = 0;
	void Build(const std::vector<std::pair<int64_t, uint8_t>> &rows) {
		uint64_t cap = 16;
		while (cap < rows.size() * 2) {
			cap *= 2;
		}
		keys.assign(cap, 0);
		vals.assign(cap, 0);
		mask = cap - 1;
		for (auto &kv : rows) {
			uint64_t i = Mix(uint64_t(kv.first)) & mask;
			while (vals[i] && keys[i] != kv.first) {
				i = (i + 1) & mask;
			}
			keys[i] = kv.first;
			uint8_t nib = kv.second ? vals[i] >> 4 : vals[i] & 15;
			if (nib == 15) {
				throw InvalidInputException("spike: more than 15 build rows for one key");
			}
			vals[i] = uint8_t(vals[i] + (kv.second ? 16 : 1));
		}
	}
	inline uint8_t Get(int64_t key) const {
		for (uint64_t i = Mix(uint64_t(key)) & mask;; i = (i + 1) & mask) {
			uint8_t v = vals[i];
			if (!v || keys[i] == key) {
				return v;
			}
		}
	}
};

static DenseNibbles DenseFromStats(ClientContext &context, TableCatalogEntry &entry, const std::string &col) {
	auto &c = entry.GetColumn(col);
	auto stats = entry.GetStorage().GetStatistics(context, StorageIndex(c.StorageOid()));
	if (!stats || !NumericStats::HasMinMax(*stats)) {
		throw InvalidInputException("spike: no min/max statistics for %s", col);
	}
	DenseNibbles d;
	d.min = NumericStats::Min(*stats).GetValue<int64_t>();
	int64_t max = NumericStats::Max(*stats).GetValue<int64_t>();
	d.range = uint64_t(max - d.min) + 1;
	if (d.range > (uint64_t(1) << 31)) {
		throw InvalidInputException("spike: key range too large for a dense table");
	}
	d.cells.assign(d.range, 0);
	return d;
}

// Q12 lineitem side: l_orderkey, l_shipmode, l_commitdate, l_receiptdate, l_shipdate with the filter in the kernel (branch-free
// mask, then the few qualifying rows). mode: 0 MAIL, 1 SHIP. Either collects (orderkey, mode) or probes an orders table.
template <class T>
struct Q12Line : SerialMerge<Q12Line<T>> {
	idx_t c_k = 0, c_m = 0, c_c = 0, c_r = 0, c_s = 0;
	int32_t lo = 0, hi = 0;
	StrMap mode;
	DenseNibbles *dense_build = nullptr;            // build into (direction A, dense)
	std::vector<std::pair<int64_t, uint8_t>> pairs; // build into (direction A, hash)
	bool collect = false;
	const T *probe = nullptr; // probe (direction B): nibbles = (low, high) priority counts per orderkey
	uint64_t high[2] = {0, 0}, low[2] = {0, 0}, joined[2] = {0, 0};
	Q12Line() {
		mode.fn = [](const string_t &s) { return StrIs(s, "MAIL") ? 0 : StrIs(s, "SHIP") ? 1 : -1; };
	}
	void Chunk(DataChunk &c) {
		idx_t n = c.size();
		int32_t m[STANDARD_VECTOR_SIZE];
		int64_t tk[STANDARD_VECTOR_SIZE];
		int32_t tc[STANDARD_VECTOR_SIZE], tr[STANDARD_VECTOR_SIZE], ts[STANDARD_VECTOR_SIZE];
		uint8_t keep[STANDARD_VECTOR_SIZE];
		mode.Code(c.data[c_m], n, m);
		if (!AllValid(c.data[c_k], n) || !AllValid(c.data[c_c], n) || !AllValid(c.data[c_r], n) || !AllValid(c.data[c_s], n)) {
			throw InvalidInputException("spike Q12: NULL input");
		}
		const int64_t *k = Dense<int64_t>(c.data[c_k], n, tk);
		auto cd = reinterpret_cast<const int32_t *>(Dense<date_t>(c.data[c_c], n, reinterpret_cast<date_t *>(tc)));
		auto rd = reinterpret_cast<const int32_t *>(Dense<date_t>(c.data[c_r], n, reinterpret_cast<date_t *>(tr)));
		auto sd = reinterpret_cast<const int32_t *>(Dense<date_t>(c.data[c_s], n, reinterpret_cast<date_t *>(ts)));
		for (idx_t r = 0; r < n; r++) {
			keep[r] = (m[r] >= 0) & (cd[r] < rd[r]) & (sd[r] < cd[r]) & (rd[r] >= lo) & (rd[r] < hi);
		}
		for (idx_t r = 0; r < n; r++) {
			if (!keep[r]) {
				continue;
			}
			if (probe) {
				uint8_t v = probe->Get(k[r]);
				low[m[r]] += v & 15;
				high[m[r]] += v >> 4;
				joined[m[r]] += (v != 0);
			} else if (collect) {
				pairs.emplace_back(k[r], uint8_t(m[r]));
			} else {
				dense_build->Add(k[r], m[r]);
			}
		}
	}
	void Merge(Q12Line &o) {
		pairs.insert(pairs.end(), o.pairs.begin(), o.pairs.end());
		for (int i = 0; i < 2; i++) {
			high[i] += o.high[i], low[i] += o.low[i], joined[i] += o.joined[i];
		}
	}
};

// Q12 orders side: o_orderkey, o_orderpriority (1 = '1-URGENT' or '2-HIGH', 0 = other, -1 = NULL: in neither CASE).
template <class T>
struct Q12Orders : SerialMerge<Q12Orders<T>> {
	idx_t c_k = 0, c_p = 0;
	StrMap prio;
	DenseNibbles *dense_build = nullptr; // build (direction B): nibbles (low, high)
	const T *probe = nullptr;            // probe (direction A): nibbles (MAIL, SHIP) line counts per orderkey
	uint64_t high[2] = {0, 0}, low[2] = {0, 0}, joined[2] = {0, 0};
	Q12Orders() {
		prio.fn = [](const string_t &s) { return StrIs(s, "1-URGENT") || StrIs(s, "2-HIGH") ? 1 : 0; };
		prio.null_code = -1;
	}
	void Chunk(DataChunk &c) {
		idx_t n = c.size();
		int32_t p[STANDARD_VECTOR_SIZE];
		int64_t tk[STANDARD_VECTOR_SIZE];
		prio.Code(c.data[c_p], n, p);
		if (!AllValid(c.data[c_k], n)) {
			throw InvalidInputException("spike Q12: NULL o_orderkey");
		}
		const int64_t *k = Dense<int64_t>(c.data[c_k], n, tk);
		if (dense_build) {
			for (idx_t r = 0; r < n; r++) {
				if (p[r] >= 0) {
					dense_build->Add(k[r], p[r]);
				}
			}
			return;
		}
		uint64_t hm = 0, lm = 0, hs = 0, ls = 0, jm = 0, js = 0;
		for (idx_t r = 0; r < n; r++) {
			uint8_t v = probe->Get(k[r]);
			uint64_t a = v & 15, b = v >> 4;
			uint64_t ishigh = p[r] == 1, islow = p[r] == 0;
			hm += a * ishigh, lm += a * islow, hs += b * ishigh, ls += b * islow;
			jm += a, js += b;
		}
		high[0] += hm, low[0] += lm, high[1] += hs, low[1] += ls, joined[0] += jm, joined[1] += js;
	}
	void Merge(Q12Orders &o) {
		for (int i = 0; i < 2; i++) {
			high[i] += o.high[i], low[i] += o.low[i], joined[i] += o.joined[i];
		}
	}
};

static std::vector<std::string> Q12Rows(const uint64_t *high, const uint64_t *low, const uint64_t *joined) {
	std::vector<std::string> out;
	const char *names[2] = {"MAIL", "SHIP"};
	for (int i = 0; i < 2; i++) {
		if (joined[i]) {
			out.push_back(std::string(names[i]) + "|" + std::to_string(high[i]) + "|" + std::to_string(low[i]));
		}
	}
	return out;
}

// SEC q3 build side: sub WHERE fy = 2022 (pushed: the table is small), rows (adsh, cik, name) collected per thread.
struct Q3Sub : SerialMerge<Q3Sub> {
	idx_t c_a = 0, c_c = 0, c_n = 0;
	struct Row {
		std::string adsh, name;
		bool adsh_null, name_null, cik_null;
		int32_t cik;
	};
	std::vector<Row> rows;
	void Chunk(DataChunk &c) {
		idx_t n = c.size();
		UnifiedVectorFormat fa, fc, fn;
		c.data[c_a].ToUnifiedFormat(n, fa);
		c.data[c_c].ToUnifiedFormat(n, fc);
		c.data[c_n].ToUnifiedFormat(n, fn);
		auto a = UnifiedVectorFormat::GetData<string_t>(fa);
		auto ck = UnifiedVectorFormat::GetData<int32_t>(fc);
		auto nm = UnifiedVectorFormat::GetData<string_t>(fn);
		for (idx_t r = 0; r < n; r++) {
			idx_t ia = fa.sel->get_index(r), ic = fc.sel->get_index(r), in = fn.sel->get_index(r);
			Row row;
			row.adsh_null = !fa.validity.RowIsValid(ia);
			row.name_null = !fn.validity.RowIsValid(in);
			row.cik_null = !fc.validity.RowIsValid(ic);
			if (!row.adsh_null) {
				row.adsh = a[ia].GetString();
			}
			if (!row.name_null) {
				row.name = nm[in].GetString();
			}
			row.cik = row.cik_null ? 0 : ck[ic];
			rows.push_back(std::move(row));
		}
	}
	void Merge(Q3Sub &o) {
		for (auto &r : o.rows) {
			rows.push_back(std::move(r));
		}
	}
};

// The build: adsh -> group (name, cik), groups numbered densely.
struct Q3Build {
	StrTable adsh;              // slot = index into gid_of
	std::vector<int32_t> gid_of; // adsh slot -> group
	std::vector<const Q3Sub::Row *> group_row; // a row of each group (its name, cik)
	void Build(const Q3Sub &s) {
		std::unordered_map<std::string, int32_t> groups;
		for (auto &r : s.rows) {
			if (r.adsh_null) {
				continue; // never equal to anything
			}
			std::string gk = (r.name_null ? std::string("\1") : "\0" + r.name) + "|" + (r.cik_null ? "N" : std::to_string(r.cik));
			auto it = groups.find(gk);
			int32_t g;
			if (it == groups.end()) {
				g = int32_t(group_row.size());
				groups.emplace(std::move(gk), g);
				group_row.push_back(&r);
			} else {
				g = it->second;
			}
			int32_t before = adsh.Size();
			int32_t slot = adsh.Find(string_t(r.adsh.data(), uint32_t(r.adsh.size())));
			if (slot < before) {
				throw InvalidInputException("spike q3: duplicate adsh on the build side (a multi-match join is not implemented)");
			}
			gid_of.push_back(g);
		}
	}
};

// SEC q3 probe side: num adsh, uom, value. adsh codes through the dictionary memo straight to the build's group (-1: no match).
struct Q3Num : SerialMerge<Q3Num> {
	idx_t c_a = 0, c_u = 0, c_v = 0;
	const Q3Build *build = nullptr;
	StrMap adsh, usd;
	std::vector<i128> sum;
	std::vector<uint64_t> cnt;
	void Init(const Q3Build *b) {
		build = b;
		adsh.fn = [b](const string_t &s) {
			int32_t slot = b->adsh.Lookup(s);
			return slot < 0 ? -1 : b->gid_of[slot];
		};
		adsh.null_code = -1;
		usd.fn = [](const string_t &s) { return StrIs(s, "USD") ? 1 : 0; };
		usd.null_code = 0;
		sum.assign(b->group_row.size(), 0);
		cnt.assign(b->group_row.size(), 0);
	}
	void Chunk(DataChunk &c) {
		idx_t n = c.size();
		int32_t g[STANDARD_VECTOR_SIZE], u[STANDARD_VECTOR_SIZE];
		usd.Code(c.data[c_u], n, u);
		adsh.Code(c.data[c_a], n, g);
		UnifiedVectorFormat f;
		c.data[c_v].ToUnifiedFormat(n, f);
		auto v = UnifiedVectorFormat::GetData<hugeint_t>(f);
		for (idx_t r = 0; r < n; r++) {
			if (g[r] < 0 || !u[r]) {
				continue;
			}
			idx_t vi = f.sel->get_index(r);
			if (!f.validity.RowIsValid(vi)) {
				continue;
			}
			i128 x = (i128(v[vi].upper) << 64) | i128(v[vi].lower);
			if (__builtin_add_overflow(sum[g[r]], x, &sum[g[r]])) {
				throw InvalidInputException("spike: SUM overflow");
			}
			cnt[g[r]]++;
		}
	}
	void Merge(Q3Num &o) {
		for (size_t i = 0; i < sum.size(); i++) {
			if (__builtin_add_overflow(sum[i], o.sum[i], &sum[i])) {
				throw InvalidInputException("spike: SUM overflow");
			}
			cnt[i] += o.cnt[i];
		}
		adsh.calls += o.adsh.calls, adsh.rows += o.adsh.rows, adsh.dict_chunks += o.adsh.dict_chunks, adsh.chunks += o.adsh.chunks;
	}
	// HAVING SUM(value) > AVG(per-cik SUM(value)) (DuckDB: DECIMAL(38,4) -> DOUBLE for the comparison, AVG of the hugeint sums in
	// long double), ORDER BY total DESC LIMIT 100.
	std::vector<std::string> Rows() {
		std::map<std::pair<bool, int32_t>, i128> per_cik;
		for (size_t i = 0; i < sum.size(); i++) {
			if (cnt[i]) {
				auto *row = build->group_row[i];
				per_cik[{row->cik_null, row->cik}] += sum[i];
			}
		}
		i128 total = 0;
		for (auto &kv : per_cik) {
			if (__builtin_add_overflow(total, kv.second, &total)) {
				throw InvalidInputException("spike: SUM overflow");
			}
		}
		hugeint_t ht;
		ht.lower = uint64_t(total), ht.upper = int64_t(total >> 64);
		long double lt;
		Hugeint::TryCast(ht, lt);
		double avg = double(lt / ((long double)per_cik.size() * 10000.0L));
		std::vector<std::pair<i128, size_t>> keep;
		for (size_t i = 0; i < sum.size(); i++) {
			if (!cnt[i]) {
				continue;
			}
			hugeint_t h;
			h.lower = uint64_t(sum[i]), h.upper = int64_t(sum[i] >> 64);
			double d;
			CastParameters params;
			TryCastFromDecimal::Operation(h, d, params, 38, 4);
			if (d > avg) {
				keep.emplace_back(sum[i], i);
			}
		}
		std::sort(keep.begin(), keep.end(), [](const std::pair<i128, size_t> &a, const std::pair<i128, size_t> &b) { return a.first > b.first; });
		std::vector<std::string> out;
		for (size_t j = 0; j < keep.size() && j < 100; j++) {
			auto *row = build->group_row[keep[j].second];
			out.push_back((row->name_null ? std::string("NULL") : row->name) + "|" + (row->cik_null ? "NULL" : std::to_string(row->cik)) +
			              "|" + DecStr(keep[j].first, 4));
		}
		if (keep.size() > 100 && keep[99].first == keep[100].first) {
			fprintf(stderr, "  q3: a tie at the LIMIT boundary; DuckDB may pick another row\n");
		}
		return out;
	}
};

static const char *Q12_SQL =
    "SELECT l_shipmode, sum(CASE WHEN o_orderpriority = '1-URGENT' OR o_orderpriority = '2-HIGH' THEN 1 ELSE 0 END) AS "
    "high_line_count, sum(CASE WHEN o_orderpriority <> '1-URGENT' AND o_orderpriority <> '2-HIGH' THEN 1 ELSE 0 END) AS "
    "low_line_count FROM orders, lineitem WHERE o_orderkey = l_orderkey AND l_shipmode IN ('MAIL', 'SHIP') AND l_commitdate < "
    "l_receiptdate AND l_shipdate < l_commitdate AND l_receiptdate >= CAST('1994-01-01' AS date) AND l_receiptdate < "
    "CAST('1995-01-01' AS date) GROUP BY l_shipmode ORDER BY l_shipmode";
static const char *Q3_SQL =
    "SELECT s.name, s.cik, SUM(n.value) AS total_value FROM num n JOIN sub s ON n.adsh = s.adsh WHERE n.uom = 'USD' AND s.fy = "
    "2022 AND n.value IS NOT NULL GROUP BY s.name, s.cik HAVING SUM(n.value) > (SELECT AVG(sub_total) FROM (SELECT SUM(n2.value) "
    "AS sub_total FROM num n2 JOIN sub s2 ON n2.adsh = s2.adsh WHERE n2.uom = 'USD' AND s2.fy = 2022 AND n2.value IS NOT NULL "
    "GROUP BY s2.cik) avg_sub) ORDER BY total_value DESC LIMIT 100";

static double g_build_ms = -1; // the last join task's build phase (scan of the build side + table), ms

struct Tab {
	TableCatalogEntry *entry;
	DataTable *storage;
	DuckTransaction *transaction;
};
static Tab TabOf(ClientContext &context, const std::string &name) {
	auto &entry = Catalog::GetEntry<TableCatalogEntry>(context, INVALID_CATALOG, INVALID_SCHEMA, name);
	return {&entry, &entry.GetStorage(), &DuckTransaction::Get(context, entry.ParentCatalog())};
}

// Join tasks: q12a (build filtered lineitem -> hash on l_orderkey, stream orders), q12ad (the same with a dense table over
// l_orderkey's statistics range), q12b (build orders -> dense on o_orderkey, stream lineitem), q3 (build sub fy=2022, stream num);
// scan:<q> scans both sides' columns with the scan-only kernel.
static std::vector<std::string> RunJoin(Connection &con, const std::string &kind, const std::string &q, int32_t lo, int32_t hi) {
	auto &context = *con.context;
	std::vector<std::string> rows;
	auto b0 = std::chrono::steady_clock::now();
	auto build_done = [&]() { g_build_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - b0).count(); };
	if (q.substr(0, 3) == "q12") {
		Tab li = TabOf(context, "lineitem"), od = TabOf(context, "orders");
		std::vector<std::string> lcols = {"l_orderkey", "l_shipmode", "l_commitdate", "l_receiptdate", "l_shipdate"};
		std::vector<std::string> ocols = {"o_orderkey", "o_orderpriority"};
		PushedScan lps = PlanScan(context, *li.entry, "lineitem", lcols, "");
		PushedScan ops = PlanScan(context, *od.entry, "orders", ocols, "");
		if (kind == "scan") {
			ScanOnly a, b;
			for (auto &c : lcols) {
				a.cols.push_back(lps.pos.at(c));
			}
			a.c_sum = lps.pos.at("l_orderkey");
			for (auto &c : ocols) {
				b.cols.push_back(ops.pos.at(c));
			}
			b.c_sum = ops.pos.at("o_orderkey");
			StreamTable(context, *li.transaction, *li.storage, lps, a);
			StreamTable(context, *od.transaction, *od.storage, ops, b);
			return {a.Rows()[0], b.Rows()[0]};
		}
		auto line_cols = [&](auto &k) {
			k.c_k = lps.pos.at("l_orderkey"), k.c_m = lps.pos.at("l_shipmode"), k.c_c = lps.pos.at("l_commitdate");
			k.c_r = lps.pos.at("l_receiptdate"), k.c_s = lps.pos.at("l_shipdate");
			k.lo = lo, k.hi = hi;
		};
		auto ord_cols = [&](auto &k) { k.c_k = ops.pos.at("o_orderkey"), k.c_p = ops.pos.at("o_orderpriority"); };
		if (q == "q12a") {
			Q12Line<HashNibbles> b;
			line_cols(b);
			b.collect = true;
			StreamTable(context, *li.transaction, *li.storage, lps, b);
			HashNibbles table;
			table.Build(b.pairs);
			build_done();
			Q12Orders<HashNibbles> p;
			ord_cols(p);
			p.probe = &table;
			StreamTable(context, *od.transaction, *od.storage, ops, p);
			return Q12Rows(p.high, p.low, p.joined);
		}
		if (q == "q12ad") {
			DenseNibbles table = DenseFromStats(context, *li.entry, "l_orderkey");
			Q12Line<DenseNibbles> b;
			line_cols(b);
			b.dense_build = &table;
			StreamTable(context, *li.transaction, *li.storage, lps, b);
			build_done();
			Q12Orders<DenseNibbles> p;
			ord_cols(p);
			p.probe = &table;
			StreamTable(context, *od.transaction, *od.storage, ops, p);
			return Q12Rows(p.high, p.low, p.joined);
		}
		if (q == "q12b") {
			DenseNibbles table = DenseFromStats(context, *od.entry, "o_orderkey");
			Q12Orders<DenseNibbles> b;
			ord_cols(b);
			b.dense_build = &table;
			StreamTable(context, *od.transaction, *od.storage, ops, b);
			build_done();
			Q12Line<DenseNibbles> p;
			line_cols(p);
			p.probe = &table;
			StreamTable(context, *li.transaction, *li.storage, lps, p);
			return Q12Rows(p.high, p.low, p.joined);
		}
		throw InvalidInputException("unknown join %s", q);
	}
	// q3
	Tab su = TabOf(context, "sub"), nu = TabOf(context, "num");
	std::vector<std::string> scols = {"adsh", "cik", "name"};
	std::vector<std::string> ncols = {"adsh", "uom", "value"};
	PushedScan sps = PlanScan(context, *su.entry, "sub", scols, "fy = 2022");
	PushedScan nps = PlanScan(context, *nu.entry, "num", ncols, "");
	if (kind == "scan") {
		ScanOnly a, b;
		for (auto &c : scols) {
			a.cols.push_back(sps.pos.at(c));
		}
		a.c_sum = sps.pos.at("cik");
		a.small = true;
		for (auto &c : ncols) {
			b.cols.push_back(nps.pos.at(c));
		}
		b.c_sum = nps.pos.at("value");
		b.huge = true;
		StreamTable(context, *su.transaction, *su.storage, sps, a);
		StreamTable(context, *nu.transaction, *nu.storage, nps, b);
		return {a.Rows()[0], b.Rows()[0]};
	}
	Q3Sub s;
	s.c_a = sps.pos.at("adsh"), s.c_c = sps.pos.at("cik"), s.c_n = sps.pos.at("name");
	StreamTable(context, *su.transaction, *su.storage, sps, s);
	Q3Build build;
	build.Build(s);
	build_done();
	Q3Num p;
	p.c_a = nps.pos.at("adsh"), p.c_u = nps.pos.at("uom"), p.c_v = nps.pos.at("value");
	p.Init(&build);
	StreamTable(context, *nu.transaction, *nu.storage, nps, p);
	if (getenv("SPIKE_VERBOSE")) {
		fprintf(stderr, "  q3: build %zu sub rows, %zu groups; num.adsh: %llu of %llu chunks dictionary, %llu lookups for %llu rows\n",
		        s.rows.size(), build.group_row.size(), (unsigned long long)p.adsh.dict_chunks, (unsigned long long)p.adsh.chunks,
		        (unsigned long long)p.adsh.calls, (unsigned long long)p.adsh.rows);
	}
	return p.Rows();
}

// ------------------------------------------------------------------------------------------------ queries

static const char *Q1_SQL =
    "SELECT l_returnflag, l_linestatus, sum(l_quantity), sum(l_extendedprice), sum(l_extendedprice * (1 - l_discount)), "
    "sum(l_extendedprice * (1 - l_discount) * (1 + l_tax)), avg(l_quantity), avg(l_extendedprice), avg(l_discount), count(*) "
    "FROM lineitem WHERE l_shipdate <= DATE '1998-09-02' GROUP BY l_returnflag, l_linestatus";
static const char *Q1_WHERE = "l_shipdate <= DATE '1998-09-02'";
static const char *Q6_SQL = "SELECT sum(l_extendedprice * l_discount) FROM lineitem WHERE l_shipdate >= DATE '1994-01-01' AND "
                            "l_shipdate < DATE '1995-01-01' AND l_discount BETWEEN 0.05 AND 0.07 AND l_quantity < 24";
static const char *Q6_WHERE = "l_shipdate >= DATE '1994-01-01' AND l_shipdate < DATE '1995-01-01' AND l_discount BETWEEN 0.05 AND "
                              "0.07 AND l_quantity < 24";

struct Def {
	std::string sql, table, where;
	std::vector<std::string> cols; // the kernel's columns (pushed variant: without the filter-only columns)
};

static Def DefOf(const std::string &q) {
	if (q == "q1") {
		return {Q1_SQL, "lineitem", Q1_WHERE, {"l_returnflag", "l_linestatus", "l_quantity", "l_extendedprice", "l_discount", "l_tax"}};
	}
	if (q == "q1k") {
		return {Q1_SQL, "lineitem", "", {"l_returnflag", "l_linestatus", "l_quantity", "l_extendedprice", "l_discount", "l_tax", "l_shipdate"}};
	}
	if (q == "q6") {
		return {Q6_SQL, "lineitem", Q6_WHERE, {"l_extendedprice", "l_discount"}};
	}
	if (q == "q6k") {
		return {Q6_SQL, "lineitem", "", {"l_extendedprice", "l_discount", "l_quantity", "l_shipdate"}};
	}
	if (q == "uom" || q == "tag") {
		return {"SELECT " + q + ", COUNT(*), SUM(value) FROM num GROUP BY " + q, "num", "", {q, "value"}};
	}
	throw InvalidInputException("unknown query %s", q);
}

static std::vector<std::string> DuckRows(Connection &con, const std::string &sql) {
	auto res = con.Query(sql);
	if (res->HasError()) {
		throw InvalidInputException(res->GetError());
	}
	std::vector<std::string> out;
	for (idx_t r = 0; r < res->RowCount(); r++) {
		std::string s;
		for (idx_t c = 0; c < res->ColumnCount(); c++) {
			s += (c ? "|" : "") + res->GetValue(c, r).ToString();
		}
		out.push_back(s);
	}
	return out;
}

static int32_t Days(Connection &con, const char *lit) {
	auto r = con.Query(std::string("SELECT CAST(") + lit + " - DATE '1970-01-01' AS INTEGER)");
	if (r->HasError()) {
		throw InvalidInputException(r->GetError());
	}
	return r->GetValue(0, 0).GetValue<int32_t>();
}

// One task, timed end to end (catalog lookup, predicate planning, scan, merge, result rows).
static std::vector<std::string> RunTask(Connection &con, const std::string &task, double &ms) {
	auto colon = task.find(':');
	std::string kind = task.substr(0, colon), q = task.substr(colon + 1);
	bool join = q.substr(0, 3) == "q12" || q == "q3";
	// q3j (duck: only): q3's join + GROUP BY once, without the HAVING subquery that DuckDB answers with a second join
	static const std::string Q3J_SQL = "SELECT s.name, s.cik, SUM(n.value) AS total_value FROM num n JOIN sub s ON n.adsh = s.adsh "
	                                   "WHERE n.uom = 'USD' AND s.fy = 2022 AND n.value IS NOT NULL GROUP BY s.name, s.cik";
	Def def = q == "q3j" ? Def {Q3J_SQL, "", "", {}} : join ? Def {q == "q3" ? Q3_SQL : Q12_SQL, "", "", {}} : DefOf(q);
	auto t0 = std::chrono::steady_clock::now();
	std::vector<std::string> rows;
	g_build_ms = -1;
	if (kind == "duck") {
		rows = DuckRows(con, def.sql);
	} else if (join) {
		int32_t lo = Days(con, "DATE '1994-01-01'"), hi = Days(con, "DATE '1995-01-01'");
		t0 = std::chrono::steady_clock::now();
		con.BeginTransaction();
		rows = RunJoin(con, kind, q, lo, hi);
		con.Commit();
	} else {
		int32_t q1_cut = 0, q6_lo = 0, q6_hi = 0;
		if (q == "q1k") {
			q1_cut = Days(con, "DATE '1998-09-02'");
		}
		if (q == "q6k") {
			q6_lo = Days(con, "DATE '1994-01-01'");
			q6_hi = Days(con, "DATE '1995-01-01'");
		}
		t0 = std::chrono::steady_clock::now(); // the date constants above are the kernel's compile-time literals
		con.BeginTransaction();
		auto &context = *con.context;
		auto &entry = Catalog::GetEntry<TableCatalogEntry>(context, INVALID_CATALOG, INVALID_SCHEMA, def.table);
		auto &storage = entry.GetStorage();
		auto &transaction = DuckTransaction::Get(context, entry.ParentCatalog());
		PushedScan ps = PlanScan(context, entry, def.table, def.cols, def.where);
		auto at = [&](const std::string &c) { return ps.pos.at(c); };
		if (kind == "scan") {
			ScanOnly k;
			for (auto &c : def.cols) {
				k.cols.push_back(at(c));
			}
			k.c_sum = at(def.cols[q == "uom" || q == "tag" ? 1 : 0 + (q.substr(0, 2) == "q1" ? 2 : 0)]);
			k.huge = q == "uom" || q == "tag";
			StreamTable(context, transaction, storage, ps, k);
			rows = k.Rows();
		} else if (kind == "stats") {
			Stats k;
			for (auto &c : def.cols) {
				k.cols.push_back(at(c));
				k.names.push_back(c);
			}
			StreamTable(context, transaction, storage, ps, k);
			rows = k.Rows();
		} else if (q == "q1" || q == "q1k") {
			auto k = make_uniq<Q1>();
			k->kernel_filter = q == "q1k";
			k->cutoff = q1_cut;
			k->c_rf = at("l_returnflag"), k->c_ls = at("l_linestatus"), k->c_q = at("l_quantity"), k->c_p = at("l_extendedprice");
			k->c_d = at("l_discount"), k->c_t = at("l_tax");
			if (k->kernel_filter) {
				k->c_sd = at("l_shipdate");
			}
			StreamTable(context, transaction, storage, ps, *k);
			rows = k->Rows();
		} else if (q == "q6" || q == "q6k") {
			Q6 k;
			k.kernel_filter = q == "q6k";
			k.lo = q6_lo, k.hi = q6_hi;
			k.c_p = at("l_extendedprice"), k.c_d = at("l_discount");
			if (k.kernel_filter) {
				k.c_q = at("l_quantity"), k.c_sd = at("l_shipdate");
			}
			StreamTable(context, transaction, storage, ps, k);
			rows = k.Rows();
		} else {
			KeyAgg k;
			k.c_k = at(q), k.c_v = at("value");
			StreamTable(context, transaction, storage, ps, k);
			rows = k.Rows();
		}
		con.Commit();
	}
	ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
	std::sort(rows.begin(), rows.end());
	return rows;
}

static std::string Check(Connection &con, const std::string &task, const std::vector<std::string> &rows) {
	auto colon = task.find(':');
	std::string kind = task.substr(0, colon);
	if (kind != "stream") {
		return "";
	}
	double ms;
	auto ref = RunTask(con, "duck:" + task.substr(colon + 1), ms);
	if (ref == rows) {
		return " [equal to DuckDB, " + std::to_string(rows.size()) + " rows]";
	}
	std::string msg = " [MISMATCH vs DuckDB: " + std::to_string(ref.size()) + " vs " + std::to_string(rows.size()) + " rows]";
	int shown = 0;
	for (size_t i = 0; i < std::max(ref.size(), rows.size()) && shown < 4; i++) {
		if (i < ref.size() && i < rows.size() && ref[i] == rows[i]) {
			continue;
		}
		shown++;
		msg += "\n   duck:   " + (i < ref.size() ? ref[i] : "-") + "\n   stream: " + (i < rows.size() ? rows[i] : "-");
	}
	return msg;
}

static int Main(int argc, char **argv);
int main(int argc, char **argv) {
	setvbuf(stdout, nullptr, _IOLBF, 0);
	try {
		return Main(argc, argv);
	} catch (std::exception &e) {
		fprintf(stderr, "ERROR: %s\n", e.what());
		return 1;
	}
}

static int Main(int argc, char **argv) {
	if (argc < 4) {
		fprintf(stderr, "usage: stream_spike <db> first <task> | warm <reps> <task>...\n");
		return 2;
	}
	DBConfig config;
	config.options.access_mode = AccessMode::READ_ONLY;
	DuckDB db(argv[1], &config);
	Connection con(db);
	con.Query("PRAGMA threads=8");
	con.Query("PRAGMA memory_limit='8GB'");
	std::string mode = argv[2];
	if (mode == "first") {
		std::string task = argv[3];
		double ms;
		auto rows = RunTask(con, task, ms);
		printf("FIRST %s %.2f\n", task.c_str(), ms);
		if (g_build_ms >= 0) {
			printf("FIRST %s#build %.2f\n", task.c_str(), g_build_ms);
		}
		auto colon = task.find(':');
		if (task.substr(0, colon) == "stats" || task.substr(0, colon) == "scan") {
			for (auto &r : rows) {
				printf("  %s\n", r.c_str());
			}
		}
		printf("  check:%s\n", Check(con, task, rows).c_str());
		return 0;
	}
	int reps = atoi(argv[3]);
	std::vector<std::string> tasks(argv + 4, argv + argc);
	std::map<std::string, std::vector<double>> times;
	for (auto &t : tasks) {
		double ms;
		auto rows = RunTask(con, t, ms);
		printf("WARMUP %s %.2f%s\n", t.c_str(), ms, Check(con, t, rows).c_str());
		auto colon = t.find(':');
		if (t.substr(0, colon) == "stats" || t.substr(0, colon) == "scan") {
			for (auto &r : rows) {
				printf("  %s\n", r.c_str());
			}
		}
	}
	for (int r = 0; r < reps; r++) {
		for (size_t i = 0; i < tasks.size(); i++) {
			auto &t = tasks[(i + r) % tasks.size()]; // rotate the order every round
			double ms;
			RunTask(con, t, ms);
			times[t].push_back(ms);
			if (g_build_ms >= 0) {
				times[t + "#build"].push_back(g_build_ms);
			}
		}
	}
	for (auto &kv : times) {
		auto &t = kv.first;
		auto v = kv.second;
		if (v.empty()) {
			continue;
		}
		std::sort(v.begin(), v.end());
		printf("WARM %s median %.2f min %.2f max %.2f n=%zu\n", t.c_str(), v[v.size() / 2], v.front(), v.back(), v.size());
	}
	return 0;
}
