"""模式文本解析：ASCII 模式 -> AST。假定输入语法有效。

支持的子集：普通字面量、元字符转义、\\xHH、点号、字符集合（范围/取反）、
圆括号分组、竖线选择、星号/加号/问号、首尾锚点。
"""
from __future__ import annotations

from .nodes import (
    Alt,
    AnchorEnd,
    AnchorStart,
    CharClass,
    Dot,
    Literal,
    Node,
    Repeat,
    Seq,
)

_SIMPLE_ESCAPES = {ord("n"): 0x0A, ord("r"): 0x0D, ord("t"): 0x09, ord("0"): 0x00}


class _Cursor:
    def __init__(self, pattern: bytes) -> None:
        self.data = pattern
        self.pos = 0

    def peek(self) -> int:
        return self.data[self.pos]

    def next(self) -> int:
        ch = self.data[self.pos]
        self.pos += 1
        return ch

    def done(self) -> bool:
        return self.pos >= len(self.data)


def _parse_escape(cur: _Cursor) -> int:
    """解析反斜杠转义，返回字节值。光标位于 '\\' 之后。"""
    ch = cur.next()
    if ch == ord("x"):
        return int(bytes([cur.next(), cur.next()]).decode("ascii"), 16)
    if ch in _SIMPLE_ESCAPES:
        return _SIMPLE_ESCAPES[ch]
    return ch  # 元字符转义及其他：按字面量处理


def _parse_class(cur: _Cursor) -> CharClass:
    """解析字符集合。光标位于 '[' 之后。"""
    negated = False
    if cur.peek() == ord("^"):
        cur.next()
        negated = True
    ranges = []
    first = True
    while True:
        ch = cur.next()
        if ch == ord("]") and not first:
            break
        first = False
        if ch == ord("\\"):
            lo = _parse_escape(cur)
        else:
            lo = ch
        if not cur.done() and cur.peek() == ord("-") and cur.data[cur.pos + 1] != ord("]"):
            cur.next()  # 消费 '-'
            hi_ch = cur.next()
            hi = _parse_escape(cur) if hi_ch == ord("\\") else hi_ch
            ranges.append((lo, hi))
        else:
            ranges.append((lo, lo))
    return CharClass(ranges=tuple(ranges), negated=negated)


def _parse_atom(cur: _Cursor) -> Node:
    ch = cur.next()
    if ch == ord("("):
        node = _parse_alt(cur)
        cur.next()  # 消费 ')'
        return node
    if ch == ord("["):
        return _parse_class(cur)
    if ch == ord("."):
        return Dot()
    if ch == ord("^"):
        return AnchorStart()
    if ch == ord("$"):
        return AnchorEnd()
    if ch == ord("\\"):
        return Literal(_parse_escape(cur))
    return Literal(ch)


def _parse_piece(cur: _Cursor) -> Node:
    node = _parse_atom(cur)
    if not cur.done() and cur.peek() in (ord("*"), ord("+"), ord("?")):
        kind = {ord("*"): "star", ord("+"): "plus", ord("?"): "quest"}[cur.next()]
        return Repeat(node, kind)
    return node


def _parse_seq(cur: _Cursor) -> Node:
    items = []
    while not cur.done() and cur.peek() not in (ord(")"), ord("|")):
        items.append(_parse_piece(cur))
    return Seq(tuple(items))


def _parse_alt(cur: _Cursor) -> Node:
    branches = [_parse_seq(cur)]
    while not cur.done() and cur.peek() == ord("|"):
        cur.next()
        branches.append(_parse_seq(cur))
    if len(branches) == 1:
        return branches[0]
    return Alt(tuple(branches))


def parse(pattern: bytes) -> Node:
    """将字节形式的模式解析为 AST。空模式返回空 Seq。"""
    cur = _Cursor(pattern)
    return _parse_alt(cur)
