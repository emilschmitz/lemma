// Small self-contained helpers of the Lemma extension: SHA-256, the SQL cache-key normalization, a minimal JSON reader.
#pragma once

#include <cstdint>
#include <map>
#include <memory>
#include <string>
#include <vector>

namespace lemma {

//! Lower-case hex SHA-256 of the bytes.
std::string Sha256Hex(const std::string &bytes);

//! The cache-key form of a SQL text. Mirror of research_loop/in_duckdb.py normalize_sql (see its docstring); tests check both agree.
std::string NormalizeSql(const std::string &sql);

//! A parsed JSON value (objects keep their keys sorted; the manifest never depends on key order).
struct Json {
	enum class Kind { Null, Bool, Number, String, Array, Object };
	Kind kind = Kind::Null;
	bool boolean = false;
	std::string text; // String: the decoded string; Number: the literal as written
	std::vector<Json> items;
	std::map<std::string, Json> fields;

	//! Throws std::runtime_error naming the key when it is missing.
	const Json &At(const std::string &key) const;
	bool Has(const std::string &key) const;
	const std::string &Str() const;
	int64_t Int() const;
	bool Bool() const;
	const std::vector<Json> &Arr() const;
};

//! Parse a whole JSON document; throws std::runtime_error on any syntax error or trailing text.
Json ParseJson(const std::string &text);

} // namespace lemma
