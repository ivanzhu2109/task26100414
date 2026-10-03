"""对外引擎：规则集与字段检查会话。状态仅保存在进程内存。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Union

from .nfa import NFA, compile_nfa, leftmost_longest
from .parser import parse


@dataclass(frozen=True)
class Evidence:
    """一条命中证据：区间 [start, end)，偏移从零开始按字节计。"""
    rule_id: str
    start: int
    end: int


class RuleSet:
    """可复用的规则集；规则带唯一标识，可复用于多次检查。"""

    def __init__(self) -> None:
        self._rules: Dict[str, NFA] = {}

    def add_rule(self, rule_id: str, pattern: Union[str, bytes]) -> None:
        """加载一条规则。pattern 为 ASCII 文本（str 或 bytes）。"""
        if rule_id in self._rules:
            raise ValueError(f"规则标识重复: {rule_id!r}")
        if isinstance(pattern, str):
            pattern = pattern.encode("ascii")
        self._rules[rule_id] = compile_nfa(parse(pattern))

    def begin(self) -> "CheckSession":
        """开始一次字段检查。"""
        return CheckSession(self)


class CheckSession:
    """一次字段检查：逐段追加字节，结束检查后返回命中证据。

    片段边界不是字段边界，空片段也不表示结束；只有 finish() 表示字段结束。
    """

    def __init__(self, ruleset: RuleSet) -> None:
        self._ruleset = ruleset
        self._buf = bytearray()
        self._finished = False

    def append(self, chunk: bytes) -> None:
        """追加一个字节片段（可为空）。"""
        if self._finished:
            raise RuntimeError("检查已结束，不能再追加片段")
        self._buf += chunk

    def finish(self) -> List[Evidence]:
        """结束检查，按规则装载顺序返回命中证据；未命中的规则不返回。"""
        if self._finished:
            raise RuntimeError("检查已结束")
        self._finished = True
        data = bytes(self._buf)
        results = []
        for rule_id, nfa in self._ruleset._rules.items():
            hit = leftmost_longest(nfa, data)
            if hit is not None:
                results.append(Evidence(rule_id=rule_id, start=hit[0], end=hit[1]))
        return results
