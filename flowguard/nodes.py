"""正则子集的 AST 节点定义（纯类型，无逻辑）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple, Union


@dataclass(frozen=True)
class Literal:
    """单字节字面量，value 取值 0-255。"""
    value: int


@dataclass(frozen=True)
class Dot:
    """点号：匹配任意字节（含换行与零字节）。"""


@dataclass(frozen=True)
class CharClass:
    """字符集合；ranges 为闭区间元组 (lo, hi)，negated 表示取反。"""
    ranges: Tuple[Tuple[int, int], ...]
    negated: bool = False


@dataclass(frozen=True)
class Seq:
    """顺序连接。"""
    items: Tuple["Node", ...]


@dataclass(frozen=True)
class Alt:
    """竖线选择，branches 至少一个分支。"""
    branches: Tuple["Node", ...]


@dataclass(frozen=True)
class Repeat:
    """量词：kind 为 'star' | 'plus' | 'quest'。"""
    node: "Node"
    kind: str


@dataclass(frozen=True)
class AnchorStart:
    """首锚点：仅匹配整个字段开头。"""


@dataclass(frozen=True)
class AnchorEnd:
    """尾锚点：仅匹配真正的字段结束。"""


Node = Union[Literal, Dot, CharClass, Seq, Alt, Repeat, AnchorStart, AnchorEnd]
