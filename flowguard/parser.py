"""Parser for the supported byte-regex subset.

Supported syntax (ASCII patterns):
    literals, meta escapes (\\xHH and escaped metachars), '.',
    character classes [...] with ranges and negation, groups '(...)',
    alternation '|', quantifiers '*', '+', '?', anchors '^' and '$'.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, Union


# --- AST nodes -------------------------------------------------------------


@dataclass(frozen=True)
class Literal:
    """A single literal byte."""

    byte: int


@dataclass(frozen=True)
class Dot:
    """'.' -- matches any single byte, including b'\\n' and b'\\x00'."""


@dataclass(frozen=True)
class CharClass:
    """'[...]' -- a set of byte ranges, optionally negated."""

    ranges: Tuple[Tuple[int, int], ...]
    negated: bool


@dataclass(frozen=True)
class Anchor:
    """'^' (start of field) or '$' (true end of field)."""

    kind: str  # "start" or "end"


@dataclass(frozen=True)
class Concat:
    parts: Tuple["Node", ...]


@dataclass(frozen=True)
class Alt:
    branches: Tuple["Node", ...]


@dataclass(frozen=True)
class Repeat:
    """'*', '+' or '?' applied to a sub-expression."""

    node: "Node"
    min_count: int  # 0 or 1
    max_count: Optional[int]  # None means unbounded


Node = Union[Literal, Dot, CharClass, Anchor, Concat, Alt, Repeat]


_SIMPLE_ESCAPES = {
    ord("n"): 0x0A,
    ord("r"): 0x0D,
    ord("t"): 0x09,
    ord("f"): 0x0C,
    ord("v"): 0x0B,
    ord("0"): 0x00,
}


class _Parser:
    def __init__(self, pattern: bytes) -> None:
        self.pat = pattern
        self.pos = 0

    def peek(self) -> Optional[int]:
        if self.pos < len(self.pat):
            return self.pat[self.pos]
        return None

    def next(self) -> int:
        ch = self.pat[self.pos]
        self.pos += 1
        return ch

    def parse(self) -> Node:
        node = self.parse_alt()
        if self.pos != len(self.pat):
            raise ValueError(f"unexpected character at {self.pos}")
        return node

    def parse_alt(self) -> Node:
        branches = [self.parse_concat()]
        while self.peek() == ord("|"):
            self.next()
            branches.append(self.parse_concat())
        if len(branches) == 1:
            return branches[0]
        return Alt(tuple(branches))

    def parse_concat(self) -> Node:
        parts = []
        while True:
            ch = self.peek()
            if ch is None or ch in (ord("|"), ord(")")):
                break
            parts.append(self.parse_repeat())
        if len(parts) == 1:
            return parts[0]
        return Concat(tuple(parts))

    def parse_repeat(self) -> Node:
        node = self.parse_atom()
        while True:
            ch = self.peek()
            if ch == ord("*"):
                self.next()
                node = Repeat(node, 0, None)
            elif ch == ord("+"):
                self.next()
                node = Repeat(node, 1, None)
            elif ch == ord("?"):
                self.next()
                node = Repeat(node, 0, 1)
            else:
                return node

    def parse_atom(self) -> Node:
        ch = self.next()
        if ch == ord("("):
            node = self.parse_alt()
            if self.next() != ord(")"):
                raise ValueError("unbalanced parenthesis")
            return node
        if ch == ord("."):
            return Dot()
        if ch == ord("["):
            return self.parse_class()
        if ch == ord("^"):
            return Anchor("start")
        if ch == ord("$"):
            return Anchor("end")
        if ch == ord("\\"):
            return Literal(self.parse_escape())
        return Literal(ch)

    def parse_escape(self) -> int:
        ch = self.next()
        if ch == ord("x"):
            hi = self.next()
            lo = self.next()
            return int(bytes([hi, lo]).decode("ascii"), 16)
        if ch in _SIMPLE_ESCAPES:
            return _SIMPLE_ESCAPES[ch]
        # Escaped metacharacter (or any other byte) is a literal.
        return ch

    def parse_class(self) -> Node:
        negated = False
        if self.peek() == ord("^"):
            self.next()
            negated = True
        ranges = []
        first = True
        while True:
            ch = self.peek()
            if ch == ord("]") and not first:
                self.next()
                break
            first = False
            lo = self.parse_class_char()
            if self.peek() == ord("-") and self.pos + 1 < len(self.pat) and self.pat[self.pos + 1] != ord("]"):
                self.next()
                hi = self.parse_class_char()
            else:
                hi = lo
            ranges.append((lo, hi))
        return CharClass(tuple(ranges), negated)

    def parse_class_char(self) -> int:
        ch = self.next()
        if ch == ord("\\"):
            return self.parse_escape()
        return ch


def parse(pattern: bytes) -> Node:
    """Parse a pattern into an AST. Input is assumed syntactically valid."""
    if isinstance(pattern, str):
        pattern = pattern.encode("ascii")
    return _Parser(pattern).parse()
