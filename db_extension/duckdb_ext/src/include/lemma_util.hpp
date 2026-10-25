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
//! keep_dollar: a `$` is an ordinary character (a query template's body: its `$name` placeholders); the whitespace is collapsed as
//! everywhere else (research_loop/in_duckdb.py normalize_template_body).
std::string NormalizeSql(const std::string &sql, bool keep_dollar = false);

//! A literal token the template matcher can bind (mirror of research_loop/in_duckdb.py literal_at): Number `[0-9]+(.[0-9]+)?`, String
//! `'...'` ('' escapes), Date `DATE '...'` (any case, at most one space). It must start a token: the character before it is not an
//! identifier character, `.`, `$` or a quote; a Number is not followed by an identifier character or `.`.
enum class LiteralKind { None, Number, String, Date };
LiteralKind LiteralAt(const std::string &s, size_t i, size_t &end);

//! The template index key text: the normalized SQL with every `$name` and every literal token replaced by `?` (quoted identifiers
//! and comments kept). A query and a template it matches have the same skeleton.
std::string TemplateSkeleton(const std::string &normalized);

//! Does `query` (normalized) equal the template body `tmpl` (normalized with keep_dollar) with each `$name` replaced by one literal
//! token of the parameter's kind? Character for character outside the placeholders; a name used twice binds the same text.
//! `bound`: name -> the literal's text in the query.
bool MatchTemplate(const std::string &tmpl, const std::string &query, const std::map<std::string, LiteralKind> &params,
                   std::map<std::string, std::string> &bound);

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
