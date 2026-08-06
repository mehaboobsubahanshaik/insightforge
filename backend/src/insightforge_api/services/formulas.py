"""Formula engine — the semantic layer's calculation language and the ONLY
path from user-authored expressions to SQL. Recursive descent, no eval;
column names travel as bind parameters inside constant allow-listed aggregate
templates; division is NULLIF-guarded. This is the deliberate seam for the
MVP 3 AI copilot: models will emit formulas, never SQL."""

import re

_FUNCS = {
    "sum": "SUM((data->>:{p})::numeric)",
    "avg": "AVG((data->>:{p})::numeric)",
    "min": "MIN((data->>:{p})::numeric)",
    "max": "MAX((data->>:{p})::numeric)",
    "count": "COUNT(*)",
    "count_distinct": "COUNT(DISTINCT data->>:{p})",
}
_TOKEN = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<ident>[A-Za-z_][A-Za-z0-9_]*)|(?P<op>[-+*/()]))"
)
MAX_FORMULA_LEN = 500


class FormulaError(ValueError):
    pass


def _tokenize(src: str) -> list[tuple[str, str]]:
    out, pos = [], 0
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        if m is None:
            raise FormulaError(f"Unexpected character at position {pos}: {src[pos:].strip()[:1]!r}")
        if m.group("num"):
            out.append(("num", m.group("num")))
        elif m.group("ident"):
            out.append(("ident", m.group("ident")))
        elif m.group("op"):
            out.append(("op", m.group("op")))
        pos = m.end()
        if m.end() == m.start():
            break
    if src[pos:].strip():
        raise FormulaError(f"Unexpected character: {src[pos:].strip()[:1]!r}")
    return out


class _Parser:
    def __init__(self, tokens, columns: set[str]):
        self.toks, self.i, self.columns = tokens, 0, columns
        self.params: dict[str, str] = {}

    def _peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def _eat(self, kind=None, value=None):
        k, v = self._peek()
        if k is None or (kind and k != kind) or (value and v != value):
            raise FormulaError(f"Unexpected token {v!r} (expected {value or kind})")
        self.i += 1
        return v

    def parse(self) -> str:
        sql = self._expr()
        if self.i != len(self.toks):
            raise FormulaError(f"Trailing tokens starting at {self._peek()[1]!r}")
        return sql

    def _expr(self) -> str:
        sql = self._term()
        while self._peek() in (("op", "+"), ("op", "-")):
            op = self._eat("op")
            sql = f"({sql} {op} {self._term()})"
        return sql

    def _term(self) -> str:
        sql = self._factor()
        while self._peek() in (("op", "*"), ("op", "/")):
            op = self._eat("op")
            rhs = self._factor()
            sql = f"({sql} * {rhs})" if op == "*" else f"({sql} / NULLIF({rhs}, 0))"
        return sql

    def _factor(self) -> str:
        kind, value = self._peek()
        if kind == "num":
            return self._eat("num")
        if kind == "op" and value == "(":
            self._eat("op", "(")
            sql = self._expr()
            self._eat("op", ")")
            return sql
        if kind == "ident":
            fname = self._eat("ident")
            if fname not in _FUNCS:
                raise FormulaError(
                    f"Unknown function {fname!r}; allowed: {', '.join(sorted(_FUNCS))}"
                )
            self._eat("op", "(")
            template = _FUNCS[fname]
            if "{p}" in template:
                col = self._eat("ident")
                if col not in self.columns:
                    raise FormulaError(f"Unknown column {col!r}")
                pname = f"fc{len(self.params)}"
                self.params[pname] = col
                sql = template.format(p=pname)
            else:
                sql = template
            self._eat("op", ")")
            return sql
        raise FormulaError(f"Unexpected token {value!r}")


def compile_formula(formula: str, dataset_schema: list[dict]) -> tuple[str, dict]:
    if not formula or len(formula) > MAX_FORMULA_LEN:
        raise FormulaError(f"Formula must be 1-{MAX_FORMULA_LEN} characters")
    parser = _Parser(_tokenize(formula), {c["name"] for c in dataset_schema})
    return parser.parse(), parser.params
