from __future__ import annotations

import re
from typing import Any

from api.errors import invalid_argument


class FilterCondition:
    def __init__(self, field: str, op: str, value: Any):
        self.field = field
        self.op = op
        self.value = value

    def to_lancedb(self) -> str:
        safe_field = self.field.replace("'", "").replace('"', "").replace(";", "")
        if isinstance(self.value, str):
            escaped = self.value.replace("'", "''")
            return f"{safe_field} {self.op} '{escaped}'"
        return f"{safe_field} {self.op} {self.value}"

    def __repr__(self):
        return f"FilterCondition({self.field} {self.op} {self.value})"


_DQS = '\"[^\"]*\"'
_SQS = "'[^']*'"
_TOKEN_SPEC = [
    ("AND", r"\bAND\b"),
    ("OR", r"\bOR\b"),
    ("LPAREN", r"\("),
    ("RPAREN", r"\)"),
    ("OP", r">=|<=|!=|="),
    ("STRING", f"{_SQS}|{_DQS}"),
    ("NUMBER", r"\d+"),
    ("IDENT", r"[a-zA-Z_][a-zA-Z0-9_]*"),
    ("SKIP", r"\s+"),
]


class FilterParser:
    def __init__(self, expression: str):
        self.tokens = self._tokenize(expression)
        self.pos = 0

    def _tokenize(self, expr: str) -> list[tuple[str, str]]:
        tokens = []
        i = 0
        while i < len(expr):
            for name, pattern in _TOKEN_SPEC:
                m = re.match(pattern, expr[i:])
                if m:
                    raw = m.group(0)
                    val = raw
                    if name != "SKIP":
                        if name == "STRING":
                            val = val[1:-1]
                        tokens.append((name, val))
                    i += len(raw)
                    break
            else:
                raise invalid_argument(f"Unexpected character at position {i}: '{expr[i]}'")
        return tokens

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def consume(self, expected: str | None = None) -> tuple[str, str]:
        tok = self.tokens[self.pos]
        self.pos += 1
        if expected and tok[0] != expected:
            raise invalid_argument(f"Expected {expected}, got {tok[0]} ('{tok[1]}')")
        return tok

    def parse(self) -> list[FilterCondition]:
        conditions = self._parse_or()
        if not isinstance(conditions, list):
            return [conditions]
        return conditions

    def _parse_or(self):
        left = self._parse_and()
        while self.peek() and self.peek()[0] == "OR":
            self.consume("OR")
            right = self._parse_and()
            left = self._combine(left, right, "OR")
        return left

    def _parse_and(self):
        left = self._parse_condition()
        while self.peek() and self.peek()[0] == "AND":
            self.consume("AND")
            right = self._parse_condition()
            left = self._combine(left, right, "AND")
        return left

    def _parse_condition(self):
        if self.peek() and self.peek()[0] == "LPAREN":
            self.consume("LPAREN")
            result = self._parse_or()
            self.consume("RPAREN")
            return result
        ident = self.consume("IDENT")
        op = self.consume("OP")
        if self.peek() and self.peek()[0] in ("STRING", "NUMBER"):
            val = self.consume()[1]
            return FilterCondition(field=ident[1], op=op[1], value=val)
        raise invalid_argument(f"Expected value after {ident[1]} {op[1]}")

    def _combine(self, left, right, operator: str):
        if operator == "AND":
            if isinstance(left, list) and isinstance(right, list):
                return left + right
            elif isinstance(left, list):
                return left + [right]
            elif isinstance(right, list):
                return [left] + right
            return [left, right]
        return [left, right]
