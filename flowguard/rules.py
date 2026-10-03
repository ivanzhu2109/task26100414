"""Rule set and per-field check session API."""

from __future__ import annotations

from typing import Dict, Iterable, List, Tuple, Union

from .nfa import NFA, compile_nfa
from .parser import parse

Pattern = Union[bytes, str]


class RuleSet:
    """A reusable set of compiled rules with unique identifiers.

    Rules and check state live only in process memory. A RuleSet can be
    reused for any number of field inspections.
    """

    def __init__(self) -> None:
        self._rules: Dict[str, NFA] = {}

    def add_rule(self, rule_id: str, pattern: Pattern) -> None:
        """Compile and register a rule. rule_id must be unique."""
        if rule_id in self._rules:
            raise ValueError(f"duplicate rule id: {rule_id!r}")
        self._rules[rule_id] = compile_nfa(parse(_as_bytes(pattern)))

    def load(self, rules: Iterable[Tuple[str, Pattern]]) -> None:
        """Register many rules at once."""
        for rule_id, pattern in rules:
            self.add_rule(rule_id, pattern)

    def __len__(self) -> int:
        return len(self._rules)

    def begin(self) -> "CheckSession":
        """Start a new field inspection using this rule set."""
        return CheckSession(self._rules)


class CheckSession:
    """One field inspection: feed byte chunks, then finish().

    Chunks are raw bytes of exactly one field; no decoding or
    normalization is applied. Chunk boundaries (including empty chunks)
    are not field boundaries.
    """

    def __init__(self, rules: Dict[str, NFA]) -> None:
        self._rules = rules
        self._chunks: List[bytes] = []
        self._finished = False

    def feed(self, chunk: bytes) -> None:
        """Append the next raw byte chunk of the field."""
        if self._finished:
            raise RuntimeError("check already finished")
        if not isinstance(chunk, (bytes, bytearray, memoryview)):
            raise TypeError("chunk must be a bytes-like object")
        self._chunks.append(bytes(chunk))

    def finish(self) -> Dict[str, Tuple[int, int]]:
        """End the check; return {rule_id: (start, end)} for matched rules.

        Evidence intervals are half-open byte offsets, chosen by the
        leftmost-longest rule. Rules without a match are omitted.
        """
        if self._finished:
            raise RuntimeError("check already finished")
        self._finished = True
        data = b"".join(self._chunks)
        self._chunks = []
        results: Dict[str, Tuple[int, int]] = {}
        for rule_id in sorted(self._rules):
            hit = self._rules[rule_id].search_leftmost_longest(data)
            if hit is not None:
                results[rule_id] = hit
        return results


def _as_bytes(pattern: Pattern) -> bytes:
    if isinstance(pattern, str):
        return pattern.encode("ascii")
    return bytes(pattern)
