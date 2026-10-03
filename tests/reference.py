"""独立参考实现：自带解析器 + 直接集合语义求值，与 flowguard 的 NFA 实现互不为因果。

match_set(ast, pos, data) 返回从 pos 出发所有可行的终点集合；
重复用不动点迭代，天然处理空串循环。
"""
from __future__ import annotations

from typing import Optional, Set, Tuple

# AST 用元组表示：
# ('lit', v) ('dot',) ('cls', negated, ((lo,hi),...)) ('bos',) ('eos',)
# ('seq', (items...)) ('alt', (branches...)) ('rep', sub, kind)


class _Cur:
    def __init__(self, pat: bytes) -> None:
        self.d = pat
        self.i = 0


def _esc(c: _Cur) -> int:
    ch = c.d[c.i]; c.i += 1
    if ch == 0x78:  # 'x'
        v = int(c.d[c.i:c.i + 2].decode(), 16); c.i += 2
        return v
    return {0x6E: 10, 0x72: 13, 0x74: 9, 0x30: 0}.get(ch, ch)


def _cls(c: _Cur):
    neg = False
    if c.d[c.i] == 0x5E:  # '^'
        c.i += 1; neg = True
    rs = []
    first = True
    while True:
        ch = c.d[c.i]; c.i += 1
        if ch == 0x5D and not first:  # ']'
            break
        first = False
        lo = _esc(c) if ch == 0x5C else ch
        if c.i < len(c.d) and c.d[c.i] == 0x2D and c.d[c.i + 1] != 0x5D:
            c.i += 1
            h = c.d[c.i]; c.i += 1
            hi = _esc(c) if h == 0x5C else h
            rs.append((lo, hi))
        else:
            rs.append((lo, lo))
    return ('cls', neg, tuple(rs))


def _atom(c: _Cur):
    ch = c.d[c.i]; c.i += 1
    if ch == 0x28:  # '('
        n = _alt(c)
        c.i += 1
        return n
    if ch == 0x5B:
        return _cls(c)
    if ch == 0x2E:
        return ('dot',)
    if ch == 0x5E:
        return ('bos',)
    if ch == 0x24:
        return ('eos',)
    if ch == 0x5C:
        return ('lit', _esc(c))
    return ('lit', ch)


def _piece(c: _Cur):
    n = _atom(c)
    if c.i < len(c.d) and c.d[c.i] in (0x2A, 0x2B, 0x3F):
        k = {0x2A: 'star', 0x2B: 'plus', 0x3F: 'quest'}[c.d[c.i]]
        c.i += 1
        return ('rep', n, k)
    return n


def _seq(c: _Cur):
    items = []
    while c.i < len(c.d) and c.d[c.i] not in (0x29, 0x7C):
        items.append(_piece(c))
    return ('seq', tuple(items))


def _alt(c: _Cur):
    bs = [_seq(c)]
    while c.i < len(c.d) and c.d[c.i] == 0x7C:
        c.i += 1
        bs.append(_seq(c))
    return bs[0] if len(bs) == 1 else ('alt', tuple(bs))


def parse_ref(pattern: bytes):
    return _alt(_Cur(pattern))


def match_set(node, pos: int, data: bytes) -> Set[int]:
    """从 pos 匹配 node，返回所有可行终点集合。"""
    tag = node[0]
    n = len(data)
    if tag == 'lit':
        return {pos + 1} if pos < n and data[pos] == node[1] else set()
    if tag == 'dot':
        return {pos + 1} if pos < n else set()
    if tag == 'cls':
        if pos >= n:
            return set()
        v = data[pos]
        inside = any(lo <= v <= hi for lo, hi in node[2])
        return {pos + 1} if inside != node[1] else set()
    if tag == 'bos':
        return {pos} if pos == 0 else set()
    if tag == 'eos':
        return {pos} if pos == n else set()
    if tag == 'seq':
        positions = {pos}
        for item in node[1]:
            nxt: Set[int] = set()
            for p in positions:
                nxt |= match_set(item, p, data)
            positions = nxt
        return positions
    if tag == 'alt':
        out: Set[int] = set()
        for b in node[1]:
            out |= match_set(b, pos, data)
        return out
    if tag == 'rep':
        sub, kind = node[1], node[2]
        if kind == 'quest':
            return {pos} | match_set(sub, pos, data)
        if kind == 'plus':
            out = match_set(sub, pos, data)
            frontier = set(out)
            while frontier:
                nxt = set()
                for p in frontier:
                    nxt |= match_set(sub, p, data)
                nxt -= out
                out |= nxt
                frontier = nxt
            return out
        # star：不动点迭代，空串循环自然收敛
        reachable = {pos}
        frontier = {pos}
        while frontier:
            nxt = set()
            for p in frontier:
                nxt |= match_set(sub, p, data)
            nxt -= reachable
            reachable |= nxt
            frontier = nxt
        return reachable
    raise AssertionError(tag)


def ref_leftmost_longest(pattern: bytes, data: bytes) -> Optional[Tuple[int, int]]:
    """参考最左最长：起点最小优先，同起点取终点最大。"""
    ast = parse_ref(pattern)
    for s in range(len(data) + 1):
        ends = match_set(ast, s, data)
        if ends:
            return (s, max(ends))
    return None
