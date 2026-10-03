"""NFA 编译与最左最长搜索。

Thompson 构造：每个状态带若干条边，边分四类——
epsilon、字节集消费边（256 位掩码）、字段开头断言、字段结束断言。
"""
from __future__ import annotations

from typing import List, Optional, Set, Tuple

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

_EPS = 0
_BYTE = 1
_BOS = 2  # 仅字段开头（位置 0）
_EOS = 3  # 仅真正的字段结束（位置 == len）

_FULL_MASK = (1 << 256) - 1

# 边: (kind, byte_mask, target)
_Edge = Tuple[int, int, int]


class NFA:
    """Thompson 构造的 NFA，含锚点断言边。"""

    def __init__(self) -> None:
        self.edges: List[List[_Edge]] = []
        self.start: int = -1
        self.accept: int = -1

    def _new_state(self) -> int:
        self.edges.append([])
        return len(self.edges) - 1

    def _add(self, src: int, kind: int, mask: int, dst: int) -> None:
        self.edges[src].append((kind, mask, dst))


def _compile_into(nfa: NFA, node: Node) -> Tuple[int, int]:
    """把子表达式编译进 nfa，返回 (入口状态, 出口状态)。"""
    if isinstance(node, Literal):
        s, t = nfa._new_state(), nfa._new_state()
        nfa._add(s, _BYTE, 1 << node.value, t)
        return s, t
    if isinstance(node, Dot):
        s, t = nfa._new_state(), nfa._new_state()
        nfa._add(s, _BYTE, _FULL_MASK, t)
        return s, t
    if isinstance(node, CharClass):
        mask = 0
        for lo, hi in node.ranges:
            for v in range(lo, hi + 1):
                mask |= 1 << v
        if node.negated:
            mask ^= _FULL_MASK
        s, t = nfa._new_state(), nfa._new_state()
        nfa._add(s, _BYTE, mask, t)
        return s, t
    if isinstance(node, AnchorStart):
        s, t = nfa._new_state(), nfa._new_state()
        nfa._add(s, _BOS, 0, t)
        return s, t
    if isinstance(node, AnchorEnd):
        s, t = nfa._new_state(), nfa._new_state()
        nfa._add(s, _EOS, 0, t)
        return s, t
    if isinstance(node, Seq):
        s, t = nfa._new_state(), nfa._new_state()
        prev = s
        for item in node.items:
            sub_s, sub_t = _compile_into(nfa, item)
            nfa._add(prev, _EPS, 0, sub_s)
            prev = sub_t
        nfa._add(prev, _EPS, 0, t)
        return s, t
    if isinstance(node, Alt):
        s, t = nfa._new_state(), nfa._new_state()
        for branch in node.branches:
            sub_s, sub_t = _compile_into(nfa, branch)
            nfa._add(s, _EPS, 0, sub_s)
            nfa._add(sub_t, _EPS, 0, t)
        return s, t
    if isinstance(node, Repeat):
        s, t = nfa._new_state(), nfa._new_state()
        sub_s, sub_t = _compile_into(nfa, node.node)
        nfa._add(s, _EPS, 0, sub_s)
        if node.kind in ("star", "quest"):
            nfa._add(s, _EPS, 0, t)
        if node.kind in ("star", "plus"):
            nfa._add(sub_t, _EPS, 0, sub_s)
        nfa._add(sub_t, _EPS, 0, t)
        return s, t
    raise TypeError(f"未知节点: {node!r}")


def compile_nfa(node: Node) -> NFA:
    nfa = NFA()
    nfa.start, nfa.accept = _compile_into(nfa, node)
    return nfa


def _closure(nfa: NFA, states: Set[int], pos: int, end: int) -> Set[int]:
    """epsilon/断言闭包；断言边按当前位置 pos 与字段长度 end 判定。"""
    stack = list(states)
    seen = set(states)
    while stack:
        cur = stack.pop()
        for kind, _mask, dst in nfa.edges[cur]:
            if kind == _EPS or (kind == _BOS and pos == 0) or (kind == _EOS and pos == end):
                if dst not in seen:
                    seen.add(dst)
                    stack.append(dst)
    return seen


def _match_ends(nfa: NFA, data: bytes, start: int) -> List[int]:
    """从 start 开始匹配，返回所有可行的终点位置列表（可能含 start 本身）。"""
    n = len(data)
    states = _closure(nfa, {nfa.start}, start, n)
    ends = []
    if nfa.accept in states:
        ends.append(start)
    for i in range(start, n):
        nxt: Set[int] = set()
        byte_bit = 1 << data[i]
        for st in states:
            for kind, mask, dst in nfa.edges[st]:
                if kind == _BYTE and mask & byte_bit:
                    nxt.add(dst)
        if not nxt:
            break
        states = _closure(nfa, nxt, i + 1, n)
        if nfa.accept in states:
            ends.append(i + 1)
    return ends


def leftmost_longest(nfa: NFA, data: bytes) -> Optional[Tuple[int, int]]:
    """在 data 任意位置搜索，返回最左最长证据区间 [start, end)；无命中返回 None。"""
    for s in range(len(data) + 1):
        ends = _match_ends(nfa, data, s)
        if ends:
            return (s, max(ends))
    return None
