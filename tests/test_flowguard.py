"""flowguard 自动化测试。"""
import itertools
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flowguard import RuleSet
from tests.reference import ref_leftmost_longest


def check_once(rules, chunks):
    """rules: [(rule_id, pattern)]；chunks: 字节片段列表。返回 {rule_id: (start, end)}。"""
    rs = RuleSet()
    for rid, pat in rules:
        rs.add_rule(rid, pat)
    s = rs.begin()
    for c in chunks:
        s.append(c)
    return {e.rule_id: (e.start, e.end) for e in s.finish()}


class TestLeftmostLongest(unittest.TestCase):
    def test_alternation_longest_not_first_written(self):
        # “a|aa” 检查 “aa” 必须得到 [0,2)，与分支书写顺序无关
        self.assertEqual(check_once([("r", "a|aa")], [b"aa"]), {"r": (0, 2)})
        self.assertEqual(check_once([("r", "aa|a")], [b"aa"]), {"r": (0, 2)})

    def test_leftmost_beats_longer(self):
        # 起点更小者优先，即使终点更短
        self.assertEqual(check_once([("r", "a|ba+")], [b"baaa"]), {"r": (0, 4)})
        self.assertEqual(check_once([("r", "b|ab")], [b"xab"]), {"r": (1, 3)})

    def test_empty_pattern_and_empty_match(self):
        self.assertEqual(check_once([("r", "")], [b"zz"]), {"r": (0, 0)})
        self.assertEqual(check_once([("r", "a*")], [b"bbb"]), {"r": (0, 0)})
        self.assertEqual(check_once([("r", "a*")], [b"aab"]), {"r": (0, 2)})

    def test_unmatched_rule_no_evidence(self):
        self.assertEqual(check_once([("r", "zzz")], [b"abc"]), {})


class TestAnchors(unittest.TestCase):
    def test_end_anchor_ignores_trailing_newline(self):
        self.assertEqual(check_once([("r", "^a+$")], [b"aa\n"]), {})
        self.assertEqual(check_once([("r", "^a+$")], [b"aa"]), {"r": (0, 2)})
        self.assertEqual(check_once([("r", "a$")], [b"ba\n"]), {})
        self.assertEqual(check_once([("r", "a$")], [b"ba"]), {"r": (1, 2)})

    def test_start_anchor_only_at_field_start(self):
        self.assertEqual(check_once([("r", "^ab")], [b"xab"]), {})
        self.assertEqual(check_once([("r", "^ab")], [b"abx"]), {"r": (0, 2)})
        # 首锚点不匹配换行之后
        self.assertEqual(check_once([("r", "^b")], [b"a\nb"]), {})

    def test_anchor_empty_field(self):
        self.assertEqual(check_once([("r", "^$")], []), {"r": (0, 0)})
        self.assertEqual(check_once([("r", "^$")], [b"\n"]), {})


class TestSyntax(unittest.TestCase):
    def test_dot_matches_newline_and_nul(self):
        self.assertEqual(check_once([("r", "a.c")], [b"a\nc"]), {"r": (0, 3)})
        self.assertEqual(check_once([("r", "a.c")], [b"a\x00c"]), {"r": (0, 3)})

    def test_hex_escape_and_meta_escape(self):
        self.assertEqual(check_once([("r", r"\x41\x00")], [b"A\x00"]), {"r": (0, 2)})
        self.assertEqual(check_once([("r", r"a\.b")], [b"a.b"]), {"r": (0, 3)})
        self.assertEqual(check_once([("r", r"a\.b")], [b"axb"]), {})

    def test_char_class(self):
        self.assertEqual(check_once([("r", "[0-9a-f]+")], [b"xy09afz"]), {"r": (2, 6)})
        self.assertEqual(check_once([("r", "[^0-9]+")], [b"12abc34"]), {"r": (2, 5)})
        self.assertEqual(check_once([("r", "[]a]")], [b"]"]), {"r": (0, 1)})

    def test_group_and_quantifiers(self):
        self.assertEqual(check_once([("r", "(ab)+c")], [b"xababcy"]), {"r": (1, 6)})
        self.assertEqual(check_once([("r", "ab?c")], [b"ac"]), {"r": (0, 2)})
        self.assertEqual(check_once([("r", "(a|b)*c")], [b"abbc"]), {"r": (0, 4)})


class TestChunking(unittest.TestCase):
    def test_all_split_points_with_empty_chunks(self):
        # 同一字段无论如何切分（含空片段），结果完全一致
        rules = [("p1", "^a+(b|c)*$"), ("p2", "b|aa"), ("p3", "[^x]*z?")]
        field = b"aabcbz\n"
        expected = check_once(rules, [field])
        for cut in range(len(field) + 1):
            got = check_once(rules, [field[:cut], b"", field[cut:], b""])
            self.assertEqual(got, expected, f"切分点 {cut}")

    def test_random_chunkings(self):
        rng = random.Random(20261004)
        rules = [("a", "^x*y$"), ("b", "a|aa"), ("c", "(ab|b)+"), ("d", ".$")]
        for _ in range(50):
            field = bytes(rng.randrange(0, 128) for _ in range(rng.randrange(0, 24)))
            expected = check_once(rules, [field])
            chunks = []
            i = 0
            while i < len(field):
                step = rng.randrange(1, 5)
                chunks.append(field[i:i + step])
                if rng.random() < 0.3:
                    chunks.append(b"")
                i += step
            self.assertEqual(check_once(rules, chunks), expected, f"field={field!r}")


class TestAgainstReference(unittest.TestCase):
    def test_empty_loops_and_multi_branch_short_fields(self):
        # 空串循环 + 多条可行分支的短字段，与独立全字段参考计算一致
        patterns = [
            b"(a|)*b", b"(a*|b?)+", b"(|a)b", b"(a|aa)(a|)", b"(|)*a",
            b"a|aa", b"(a|)(a|)a", b"(x?)*y", b"(|a|aa)*", b"a**",
        ]
        fields = [b"", b"a", b"aa", b"aaa", b"ab", b"ba", b"aab", b"b", b"xy", b"aaxy"]
        for pat, field in itertools.product(patterns, fields):
            got = check_once([("r", pat)], [field]).get("r")
            want = ref_leftmost_longest(pat, field)
            self.assertEqual(got, want, f"pattern={pat!r} field={field!r}")

    def test_randomized_against_reference(self):
        rng = random.Random(7)
        atoms = [b"a", b"b", b".", b"[ab]", b"[^a]", rb"\x00", b"(a|b)", b"(|a)"]
        quants = [b"", b"*", b"+", b"?"]
        for _ in range(300):
            parts = []
            for _ in range(rng.randrange(1, 5)):
                parts.append(rng.choice(atoms) + rng.choice(quants))
            pat = b"".join(parts)
            if rng.random() < 0.3:
                pat = b"^" + pat
            if rng.random() < 0.3:
                pat = pat + b"$"
            field = bytes(rng.choice(b"ab\n\x00") for _ in range(rng.randrange(0, 8)))
            got = check_once([("r", pat)], [field]).get("r")
            want = ref_leftmost_longest(pat, field)
            self.assertEqual(got, want, f"pattern={pat!r} field={field!r}")


class TestRuleSetApi(unittest.TestCase):
    def test_duplicate_rule_id_rejected(self):
        rs = RuleSet()
        rs.add_rule("r", "a")
        with self.assertRaises(ValueError):
            rs.add_rule("r", "b")

    def test_ruleset_reusable_across_sessions(self):
        rs = RuleSet()
        rs.add_rule("r", "ab")
        self.assertEqual({e.rule_id: (e.start, e.end) for e in rs.begin().finish()}, {})
        s = rs.begin()
        s.append(b"ab")
        self.assertEqual([(e.rule_id, e.start, e.end) for e in s.finish()], [("r", 0, 2)])

    def test_load_order_does_not_change_results(self):
        rules = [("r1", "a+"), ("r2", "^b"), ("r3", "c$")]
        forward = check_once(rules, [b"baac"])
        backward = check_once(list(reversed(rules)), [b"baac"])
        self.assertEqual(forward, backward)
        self.assertEqual(forward, {"r1": (1, 3), "r2": (0, 1), "r3": (3, 4)})

    def test_append_after_finish_rejected(self):
        rs = RuleSet()
        rs.add_rule("r", "a")
        s = rs.begin()
        s.finish()
        with self.assertRaises(RuntimeError):
            s.append(b"a")
        with self.assertRaises(RuntimeError):
            s.finish()


if __name__ == "__main__":
    unittest.main()
