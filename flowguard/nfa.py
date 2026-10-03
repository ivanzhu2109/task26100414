"""NFA construction (Thompson) and leftmost-longest simulation."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .parser import Alt, Anchor, CharClass, Concat, Dot, Literal, Node, Repeat

# Epsilon edge conditions.
_ALWAYS = 0
_AT_START = 1  # only at absolute field start (offset 0)
_AT_END = 2  # only at true field end


class NFA:
    """Compiled NFA for one rule pattern."""

    def __init__(self) -> None:
        # eps[state] -> list of (condition, target)
        self.eps: List[List[Tuple[int, int]]] = []
        # trans[state] -> list of (lo, hi, target) byte ranges
        self.trans: List[List[Tuple[int, int, int]]] = []
        self.start = self._new_state()
        self.accept = self._new_state()

    def _new_state(self) -> int:
        self.eps.append([])
        self.trans.append([])
        return len(self.eps) - 1

    def search_leftmost_longest(self, data: bytes) -> Optional[Tuple[int, int]]:
        """Return the [start, end) evidence interval, or None if no match.

        Leftmost-longest: smallest start wins; ties broken by largest end.
        """
        n = len(data)
        best_end: Dict[int, int] = {}
        # Live threads: maps state -> smallest start offset seen for it.
        # Distinct starts must be tracked separately, so keep (state, start).
        current: set[Tuple[int, int]] = set()
        for pos in range(n + 1):
            at_start = pos == 0
            at_end = pos == n
            current.add((self.start, pos))
            closure = self._closure(current, at_start, at_end)
            for state, origin in closure:
                if state == self.accept and pos >= origin:
                    if pos > best_end.get(origin, -1):
                        best_end[origin] = pos
            if at_end:
                break
            byte = data[pos]
            nxt: set[Tuple[int, int]] = set()
            for state, origin in closure:
                for lo, hi, target in self.trans[state]:
                    if lo <= byte <= hi:
                        nxt.add((target, origin))
            current = nxt
        if not best_end:
            return None
        leftmost = min(best_end)
        return (leftmost, best_end[leftmost])

    def _closure(
        self, seeds: set[Tuple[int, int]], at_start: bool, at_end: bool
    ) -> set[Tuple[int, int]]:
        seen: set[Tuple[int, int]] = set()
        stack = list(seeds)
        while stack:
            item = stack.pop()
            if item in seen:
                continue
            seen.add(item)
            state, origin = item
            for cond, target in self.eps[state]:
                if cond == _AT_START and not at_start:
                    continue
                if cond == _AT_END and not at_end:
                    continue
                nxt = (target, origin)
                if nxt not in seen:
                    stack.append(nxt)
        return seen


def _complement(ranges: Tuple[Tuple[int, int], ...]) -> Tuple[Tuple[int, int], ...]:
    """Complement of byte ranges over [0, 255], as merged sorted ranges."""
    merged: List[Tuple[int, int]] = []
    for lo, hi in sorted(ranges):
        if merged and lo <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    out: List[Tuple[int, int]] = []
    cursor = 0
    for lo, hi in merged:
        if cursor < lo:
            out.append((cursor, lo - 1))
        cursor = hi + 1
    if cursor <= 255:
        out.append((cursor, 255))
    return tuple(out)


class _Builder:
    def __init__(self) -> None:
        self.nfa = NFA()

    def build(self, node: Node) -> Tuple[int, int]:
        """Add fragment for node; return (start, accept) state ids."""
        nfa = self.nfa
        if isinstance(node, Literal):
            s, a = nfa._new_state(), nfa._new_state()
            nfa.trans[s].append((node.byte, node.byte, a))
            return s, a
        if isinstance(node, Dot):
            s, a = nfa._new_state(), nfa._new_state()
            nfa.trans[s].append((0, 255, a))
            return s, a
        if isinstance(node, CharClass):
            ranges = node.ranges
            if node.negated:
                ranges = _complement(ranges)
            s, a = nfa._new_state(), nfa._new_state()
            for lo, hi in ranges:
                nfa.trans[s].append((lo, hi, a))
            return s, a
        if isinstance(node, Anchor):
            s, a = nfa._new_state(), nfa._new_state()
            cond = _AT_START if node.kind == "start" else _AT_END
            nfa.eps[s].append((cond, a))
            return s, a
        if isinstance(node, Concat):
            if not node.parts:
                s, a = nfa._new_state(), nfa._new_state()
                nfa.eps[s].append((_ALWAYS, a))
                return s, a
            s, a = self.build(node.parts[0])
            for part in node.parts[1:]:
                ps, pa = self.build(part)
                nfa.eps[a].append((_ALWAYS, ps))
                a = pa
            return s, a
        if isinstance(node, Alt):
            s, a = nfa._new_state(), nfa._new_state()
            for branch in node.branches:
                bs, ba = self.build(branch)
                nfa.eps[s].append((_ALWAYS, bs))
                nfa.eps[ba].append((_ALWAYS, a))
            return s, a
        if isinstance(node, Repeat):
            if node.max_count == 1:  # '?'
                s, a = nfa._new_state(), nfa._new_state()
                ns, na = self.build(node.node)
                nfa.eps[s].append((_ALWAYS, ns))
                nfa.eps[s].append((_ALWAYS, a))
                nfa.eps[na].append((_ALWAYS, a))
                return s, a
            # '*' or '+': loop fragment.
            s, a = nfa._new_state(), nfa._new_state()
            ns, na = self.build(node.node)
            nfa.eps[s].append((_ALWAYS, ns))
            nfa.eps[na].append((_ALWAYS, ns))
            nfa.eps[na].append((_ALWAYS, a))
            if node.min_count == 0:
                nfa.eps[s].append((_ALWAYS, a))
            return s, a
        raise TypeError(f"unknown node: {node!r}")


def compile_nfa(ast: Node) -> NFA:
    """Compile a parsed pattern AST into an NFA."""
    builder = _Builder()
    s, a = builder.build(ast)
    nfa = builder.nfa
    nfa.eps[nfa.start].append((_ALWAYS, s))
    nfa.eps[a].append((_ALWAYS, nfa.accept))
    return nfa
