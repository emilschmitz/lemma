#include "lemma_util.hpp"

#include <cctype>
#include <cstring>
#include <stdexcept>

namespace lemma {

// ---------------------------------------------------------------- SHA-256 (FIPS 180-4)

namespace {
const uint32_t K[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01,
    0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
    0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08,
    0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};

inline uint32_t Rotr(uint32_t x, int n) {
	return (x >> n) | (x << (32 - n));
}

void Block(uint32_t h[8], const uint8_t *p) {
	uint32_t w[64];
	for (int i = 0; i < 16; i++) {
		w[i] = (uint32_t(p[4 * i]) << 24) | (uint32_t(p[4 * i + 1]) << 16) | (uint32_t(p[4 * i + 2]) << 8) | uint32_t(p[4 * i + 3]);
	}
	for (int i = 16; i < 64; i++) {
		uint32_t s0 = Rotr(w[i - 15], 7) ^ Rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
		uint32_t s1 = Rotr(w[i - 2], 17) ^ Rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
		w[i] = w[i - 16] + s0 + w[i - 7] + s1;
	}
	uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
	for (int i = 0; i < 64; i++) {
		uint32_t t1 = hh + (Rotr(e, 6) ^ Rotr(e, 11) ^ Rotr(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i];
		uint32_t t2 = (Rotr(a, 2) ^ Rotr(a, 13) ^ Rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
		hh = g;
		g = f;
		f = e;
		e = d + t1;
		d = c;
		c = b;
		b = a;
		a = t1 + t2;
	}
	h[0] += a;
	h[1] += b;
	h[2] += c;
	h[3] += d;
	h[4] += e;
	h[5] += f;
	h[6] += g;
	h[7] += hh;
}
} // namespace

std::string Sha256Hex(const std::string &bytes) {
	uint32_t h[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
	const uint8_t *data = reinterpret_cast<const uint8_t *>(bytes.data());
	size_t n = bytes.size();
	size_t full = n / 64;
	for (size_t i = 0; i < full; i++) {
		Block(h, data + 64 * i);
	}
	uint8_t tail[128];
	size_t rest = n - 64 * full;
	std::memset(tail, 0, sizeof(tail));
	std::memcpy(tail, data + 64 * full, rest);
	tail[rest] = 0x80;
	size_t tail_len = rest + 1 + 8 <= 64 ? 64 : 128;
	uint64_t bits = uint64_t(n) * 8;
	for (int i = 0; i < 8; i++) {
		tail[tail_len - 1 - i] = uint8_t(bits >> (8 * i));
	}
	Block(h, tail);
	if (tail_len == 128) {
		Block(h, tail + 64);
	}
	static const char *hex = "0123456789abcdef";
	std::string out;
	for (int i = 0; i < 8; i++) {
		for (int j = 3; j >= 0; j--) {
			uint8_t byte = uint8_t(h[i] >> (8 * j));
			out.push_back(hex[byte >> 4]);
			out.push_back(hex[byte & 15]);
		}
	}
	return out;
}

// ---------------------------------------------------------------- SQL normalization

namespace {
bool IsWs(char c) {
	return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' || c == '\v';
}

std::string StripEnd(std::string text) {
	size_t b = 0;
	while (b < text.size() && IsWs(text[b])) {
		b++;
	}
	text = text.substr(b);
	while (!text.empty() && IsWs(text.back())) {
		text.pop_back();
	}
	while (!text.empty() && text.back() == ';') {
		text.pop_back();
		while (!text.empty() && IsWs(text.back())) {
			text.pop_back();
		}
	}
	return text;
}
} // namespace

std::string NormalizeSql(const std::string &sql, bool keep_dollar) {
	std::string out;
	size_t i = 0, n = sql.size();
	bool pending_space = false;
	while (i < n) {
		char c = sql[i];
		if (IsWs(c)) {
			pending_space = true;
			i++;
			continue;
		}
		if (pending_space && !out.empty()) {
			out.push_back(' ');
		}
		pending_space = false;
		size_t j;
		if (c == '\'' || c == '"') {
			j = sql.find(c, i + 1);
			j = j == std::string::npos ? n : j + 1;
		} else if (sql.compare(i, 2, "--") == 0) {
			j = sql.find('\n', i);
			j = j == std::string::npos ? n : j + 1;
		} else if (sql.compare(i, 2, "/*") == 0) {
			j = sql.find("*/", i + 2);
			j = j == std::string::npos ? n : j + 2;
		} else if (c == '$' && !keep_dollar) {
			return StripEnd(sql);
		} else {
			j = i + 1;
		}
		out.append(sql, i, j - i);
		i = j;
	}
	return StripEnd(out);
}

// ---------------------------------------------------------------- literal tokens, template skeletons and template matching

namespace {
bool IdentChar(char c) {
	unsigned char u = static_cast<unsigned char>(c);
	return std::isalnum(u) || c == '_' || u >= 0x80;
}
bool Digit(char c) {
	return c >= '0' && c <= '9';
}
// The end of a '...' string at i ('' is an escaped quote inside it); npos when it is not closed.
size_t StringEnd(const std::string &s, size_t i) {
	size_t j = i + 1;
	while (j < s.size()) {
		if (s[j] == '\'') {
			if (j + 1 < s.size() && s[j + 1] == '\'') {
				j += 2;
				continue;
			}
			return j + 1;
		}
		j++;
	}
	return std::string::npos;
}
// The end of a quoted segment or comment starting at i (the same rule as NormalizeSql), or i when none starts there.
size_t OpaqueEnd(const std::string &s, size_t i) {
	size_t n = s.size(), j;
	char c = s[i];
	if (c == '\'' || c == '"') {
		j = s.find(c, i + 1);
		return j == std::string::npos ? n : j + 1;
	}
	if (s.compare(i, 2, "--") == 0) {
		j = s.find('\n', i);
		return j == std::string::npos ? n : j + 1;
	}
	if (s.compare(i, 2, "/*") == 0) {
		j = s.find("*/", i + 2);
		return j == std::string::npos ? n : j + 2;
	}
	return i;
}
size_t PlaceholderEnd(const std::string &s, size_t i) {
	if (s[i] != '$' || i + 1 >= s.size() || !(std::isalpha(static_cast<unsigned char>(s[i + 1])) || s[i + 1] == '_')) {
		return i;
	}
	size_t j = i + 1;
	while (j < s.size() && (std::isalnum(static_cast<unsigned char>(s[j])) || s[j] == '_')) {
		j++;
	}
	return j;
}
} // namespace

LiteralKind LiteralAt(const std::string &s, size_t i, size_t &end) {
	size_t n = s.size();
	if (i >= n || (i > 0 && (IdentChar(s[i - 1]) || s[i - 1] == '.' || s[i - 1] == '$' || s[i - 1] == '\'' || s[i - 1] == '"'))) {
		return LiteralKind::None;
	}
	if (Digit(s[i])) {
		size_t j = i;
		while (j < n && Digit(s[j])) {
			j++;
		}
		if (j + 1 < n && s[j] == '.' && Digit(s[j + 1])) {
			j++;
			while (j < n && Digit(s[j])) {
				j++;
			}
		}
		if (j < n && (IdentChar(s[j]) || s[j] == '.')) {
			return LiteralKind::None;
		}
		end = j;
		return LiteralKind::Number;
	}
	if (s[i] == '\'') {
		size_t j = StringEnd(s, i);
		if (j == std::string::npos) {
			return LiteralKind::None;
		}
		end = j;
		return LiteralKind::String;
	}
	if (i + 4 <= n && (s[i] == 'D' || s[i] == 'd') && (s[i + 1] == 'A' || s[i + 1] == 'a') && (s[i + 2] == 'T' || s[i + 2] == 't') &&
	    (s[i + 3] == 'E' || s[i + 3] == 'e')) {
		size_t q = i + 4;
		if (q < n && s[q] == ' ') {
			q++;
		}
		if (q < n && s[q] == '\'') {
			size_t j = StringEnd(s, q);
			if (j != std::string::npos) {
				end = j;
				return LiteralKind::Date;
			}
		}
	}
	return LiteralKind::None;
}

std::string TemplateSkeleton(const std::string &normalized) {
	std::string out;
	size_t i = 0, n = normalized.size();
	while (i < n) {
		size_t end = 0;
		size_t p = PlaceholderEnd(normalized, i);
		if (p > i) {
			out += '?';
			i = p;
			continue;
		}
		if (LiteralAt(normalized, i, end) != LiteralKind::None) {
			out += '?';
			i = end;
			continue;
		}
		size_t j = OpaqueEnd(normalized, i);
		if (j > i) {
			out.append(normalized, i, j - i);
			i = j;
			continue;
		}
		out += normalized[i++];
	}
	return out;
}

bool MatchTemplate(const std::string &tmpl, const std::string &query, const std::map<std::string, LiteralKind> &params,
                   std::map<std::string, std::string> &bound) {
	bound.clear();
	size_t i = 0, j = 0, n = tmpl.size(), m = query.size();
	while (i < n) {
		size_t p = PlaceholderEnd(tmpl, i);
		if (p > i) {
			auto it = params.find(tmpl.substr(i + 1, p - i - 1));
			if (it == params.end()) {
				return false;
			}
			size_t end = 0;
			if (LiteralAt(query, j, end) != it->second) {
				return false;
			}
			std::string text = query.substr(j, end - j);
			auto seen = bound.find(it->first);
			if (seen != bound.end() && seen->second != text) {
				return false;
			}
			bound[it->first] = text;
			i = p;
			j = end;
			// the text after the placeholder must not continue the literal (e.g. `$p.5` against `1.5`): checked by LiteralAt's end
			// rule on the query, and the template's next character is compared below as usual
			continue;
		}
		size_t e = OpaqueEnd(tmpl, i);
		size_t len = e > i ? e - i : 1;
		if (j + len > m || query.compare(j, len, tmpl, i, len) != 0) {
			return false;
		}
		i += len;
		j += len;
	}
	return j == m;
}

// ---------------------------------------------------------------- JSON

const Json &Json::At(const std::string &key) const {
	auto it = fields.find(key);
	if (kind != Kind::Object || it == fields.end()) {
		throw std::runtime_error("manifest: missing key '" + key + "'");
	}
	return it->second;
}

bool Json::Has(const std::string &key) const {
	return kind == Kind::Object && fields.count(key) > 0;
}

const std::string &Json::Str() const {
	if (kind != Kind::String) {
		throw std::runtime_error("manifest: expected a string");
	}
	return text;
}

int64_t Json::Int() const {
	if (kind != Kind::Number) {
		throw std::runtime_error("manifest: expected a number");
	}
	size_t used = 0;
	long long v = std::stoll(text, &used);
	if (used != text.size()) {
		throw std::runtime_error("manifest: expected an integer, got " + text);
	}
	return v;
}

bool Json::Bool() const {
	if (kind != Kind::Bool) {
		throw std::runtime_error("manifest: expected a boolean");
	}
	return boolean;
}

const std::vector<Json> &Json::Arr() const {
	if (kind != Kind::Array) {
		throw std::runtime_error("manifest: expected an array");
	}
	return items;
}

namespace {
struct Parser {
	explicit Parser(const std::string &text) : s(text) {
	}
	const std::string &s;
	size_t i = 0;

	[[noreturn]] void Fail(const std::string &what) {
		throw std::runtime_error("manifest JSON: " + what + " at byte " + std::to_string(i));
	}
	void Ws() {
		while (i < s.size() && (s[i] == ' ' || s[i] == '\n' || s[i] == '\r' || s[i] == '\t')) {
			i++;
		}
	}
	void Expect(const char *lit) {
		size_t len = std::strlen(lit);
		if (s.compare(i, len, lit) != 0) {
			Fail(std::string("expected ") + lit);
		}
		i += len;
	}
	static void Utf8(std::string &out, uint32_t cp) {
		if (cp < 0x80) {
			out.push_back(char(cp));
		} else if (cp < 0x800) {
			out.push_back(char(0xC0 | (cp >> 6)));
			out.push_back(char(0x80 | (cp & 0x3F)));
		} else if (cp < 0x10000) {
			out.push_back(char(0xE0 | (cp >> 12)));
			out.push_back(char(0x80 | ((cp >> 6) & 0x3F)));
			out.push_back(char(0x80 | (cp & 0x3F)));
		} else {
			out.push_back(char(0xF0 | (cp >> 18)));
			out.push_back(char(0x80 | ((cp >> 12) & 0x3F)));
			out.push_back(char(0x80 | ((cp >> 6) & 0x3F)));
			out.push_back(char(0x80 | (cp & 0x3F)));
		}
	}
	uint32_t Hex4() {
		if (i + 4 > s.size()) {
			Fail("short \\u escape");
		}
		uint32_t v = 0;
		for (int k = 0; k < 4; k++) {
			char c = s[i++];
			v <<= 4;
			if (c >= '0' && c <= '9') {
				v |= uint32_t(c - '0');
			} else if (c >= 'a' && c <= 'f') {
				v |= uint32_t(c - 'a' + 10);
			} else if (c >= 'A' && c <= 'F') {
				v |= uint32_t(c - 'A' + 10);
			} else {
				Fail("bad \\u escape");
			}
		}
		return v;
	}
	std::string String() {
		Expect("\"");
		std::string out;
		while (true) {
			if (i >= s.size()) {
				Fail("unterminated string");
			}
			char c = s[i++];
			if (c == '"') {
				return out;
			}
			if (c != '\\') {
				out.push_back(c);
				continue;
			}
			if (i >= s.size()) {
				Fail("unterminated escape");
			}
			char e = s[i++];
			switch (e) {
			case '"':
			case '\\':
			case '/':
				out.push_back(e);
				break;
			case 'b':
				out.push_back('\b');
				break;
			case 'f':
				out.push_back('\f');
				break;
			case 'n':
				out.push_back('\n');
				break;
			case 'r':
				out.push_back('\r');
				break;
			case 't':
				out.push_back('\t');
				break;
			case 'u': {
				uint32_t cp = Hex4();
				if (cp >= 0xD800 && cp < 0xDC00) {
					Expect("\\u");
					uint32_t lo = Hex4();
					if (lo < 0xDC00 || lo >= 0xE000) {
						Fail("bad surrogate pair");
					}
					cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
				}
				Utf8(out, cp);
				break;
			}
			default:
				Fail("bad escape");
			}
		}
	}
	Json Value() {
		Ws();
		Json v;
		if (i >= s.size()) {
			Fail("unexpected end");
		}
		char c = s[i];
		if (c == '{') {
			i++;
			v.kind = Json::Kind::Object;
			Ws();
			if (i < s.size() && s[i] == '}') {
				i++;
				return v;
			}
			while (true) {
				Ws();
				std::string key = String();
				Ws();
				Expect(":");
				v.fields[key] = Value();
				Ws();
				if (i < s.size() && s[i] == ',') {
					i++;
					continue;
				}
				Expect("}");
				return v;
			}
		}
		if (c == '[') {
			i++;
			v.kind = Json::Kind::Array;
			Ws();
			if (i < s.size() && s[i] == ']') {
				i++;
				return v;
			}
			while (true) {
				v.items.push_back(Value());
				Ws();
				if (i < s.size() && s[i] == ',') {
					i++;
					continue;
				}
				Expect("]");
				return v;
			}
		}
		if (c == '"') {
			v.kind = Json::Kind::String;
			v.text = String();
			return v;
		}
		if (s.compare(i, 4, "true") == 0) {
			i += 4;
			v.kind = Json::Kind::Bool;
			v.boolean = true;
			return v;
		}
		if (s.compare(i, 5, "false") == 0) {
			i += 5;
			v.kind = Json::Kind::Bool;
			return v;
		}
		if (s.compare(i, 4, "null") == 0) {
			i += 4;
			return v;
		}
		size_t start = i;
		while (i < s.size() && (std::strchr("+-0123456789.eE", s[i]) != nullptr)) {
			i++;
		}
		if (start == i) {
			Fail("unexpected character");
		}
		v.kind = Json::Kind::Number;
		v.text = s.substr(start, i - start);
		return v;
	}
};
} // namespace

Json ParseJson(const std::string &text) {
	Parser p(text);
	Json v = p.Value();
	p.Ws();
	if (p.i != text.size()) {
		p.Fail("trailing text");
	}
	return v;
}

} // namespace lemma
