"""Automated tests for the flowguard rule-matching library."""

from __future__ import annotations

import itertools
import random
import re
import unittest

from flowguard import RuleSet


# --- Independent full-field reference --------------------------------------
#
# The reference translates the supported subset into an equivalent Python
# `re` bytes pattern ('^' -> '\A', '$' -> '\Z', compiled with DOTALL) and
# then brute-forces the leftmost-longest interval by trying every
# (start, end) pair with Pattern.fullmatch(data, start, end).


def _translate(pattern: bytes, dollar: bytes) -> bytes:
    out = bytearray()
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == 0x5C:  # backslash: copy escape verbatim
            out += pattern[i : i + 2]
            i += 2
        elif ch == ord("["):
            j = i + 1
            if j < n and pattern[j] == ord("^"):
                j += 1
            if j < n and pattern[j] == ord("]"):
                j += 1
            while j < n and pattern[j] != ord("]"):
                j += 2 if pattern[j] == 0x5C else 1
            out += pattern[i : j + 1]
            i = j + 1
        elif ch == ord("^"):
            out += b"\\A"
            i += 1
        elif ch == ord("$"):
            out += dollar
            i += 1
        else:
            out.append(ch)
            i += 1
    return bytes(out)


def reference_leftmost_longest(pattern: bytes, data: bytes):
    """Independent reference: brute-force leftmost-longest over the field."""
    # '^' -> '\A' is absolute and correct for any candidate interval.
    # '$' is absolute end-of-field: for intervals ending at the true field
    # end translate to '\Z'; for shorter intervals translate to '(?!)'
    # (never matches), because any match relying on '$' must end at the
    # true end of the field.
    at_end = re.compile(_translate(pattern, b"\\Z"), re.DOTALL)
    not_end = re.compile(_translate(pattern, b"(?!)"), re.DOTALL)
    best = None
    n = len(data)
    for start in range(n + 1):
        for end in range(start, n + 1):
            engine = at_end if end == n else not_end
            if engine.fullmatch(data, start, end) is not None:
                if best is None:
                    best = (start, end)
                elif start == best[0] and end > best[1]:
                    best = (start, end)
    return best


def run_whole(pattern: bytes, data: bytes):
    rs = RuleSet()
    rs.add_rule("only", pattern)
    session = rs.begin()
    session.feed(data)
    return session.finish().get("only")


def run_chunked(pattern: bytes, data: bytes, chunks):
    rs = RuleSet()
    rs.add_rule("only", pattern)
    session = rs.begin()
    for chunk in chunks:
        session.feed(chunk)
    got = session.finish().get("only")
    # Sanity: the chunks must reassemble into the field.
    assert b"".join(chunks) == data
    return got


def chunkings(data: bytes):
    """Deterministic set of chunkings, including empty chunks."""
    yield [data]
    yield [bytes([b]) for b in data]
    yield [b""] + [data] + [b""]
    for cut in range(len(data) + 1):
        yield [data[:cut], data[cut:]]
    for cut1 in range(len(data) + 1):
        for cut2 in range(cut1, len(data) + 1):
            yield [data[:cut1], data[cut1:cut2], data[cut2:]]
    rng = random.Random(1234)
    for _ in range(25):
        pieces = []
        rest = data
        while rest:
            size = rng.randint(0, len(rest))
            pieces.append(rest[:size])
            rest = rest[size:]
            if rng.random() < 0.3:
                pieces.append(b"")
        pieces.append(rest)
        yield pieces


class TestLeftmostLongest(unittest.TestCase):
    def test_alternation_is_longest_not_first_branch(self):
        self.assertEqual(run_whole(b"a|aa", b"aa"), (0, 2))
        self.assertEqual(run_whole(b"aa|a", b"aa"), (0, 2))

    def test_leftmost_wins_over_longer_later_match(self):
        self.assertEqual(run_whole(b"a+", b"a aaa"), (0, 1))
        self.assertEqual(run_whole(b"a*", b"bbb"), (0, 0))

    def test_empty_pattern_matches_empty_at_zero(self):
        self.assertEqual(run_whole(b"", b"xy"), (0, 0))
        self.assertEqual(run_whole(b"", b""), (0, 0))

    def test_empty_string_match_interval(self):
        self.assertEqual(run_whole(b"x*", b"bbb"), (0, 0))
        self.assertEqual(run_whole(b"b?c", b"c"), (0, 1))

    def test_empty_loop_with_multiple_branches(self):
        # '(a*)*' can match empty anywhere; leftmost-longest on 'aaab'.
        self.assertEqual(run_whole(b"(a*)*", b"aaab"), (0, 3))
        self.assertEqual(run_whole(b"(a*)*b", b"aaab"), (0, 4))
        self.assertEqual(run_whole(b"(a|aa)*", b"aaa"), (0, 3))
        self.assertEqual(run_whole(b"(ab|a)(b?)", b"ab"), (0, 2))
        self.assertEqual(run_whole(b"(a|ab)(c|bcd)", b"abcd"), (0, 4))

    def test_no_match_returns_no_evidence(self):
        self.assertIsNone(run_whole(b"zzz", b"abc"))


class TestAnchorsAndDot(unittest.TestCase):
    def test_start_anchor_only_at_field_start(self):
        self.assertEqual(run_whole(b"^abc", b"abc"), (0, 3))
        self.assertIsNone(run_whole(b"^abc", b"xabc"))
        self.assertIsNone(run_whole(b"^abc", b"\nabc"))

    def test_end_anchor_only_at_true_end(self):
        self.assertEqual(run_whole(b"abc$", b"abc"), (0, 3))
        # Unlike Python's '$', a trailing newline must NOT satisfy '$'.
        self.assertIsNone(run_whole(b"abc$", b"abc\n"))
        self.assertIsNone(run_whole(b"^abc$", b"abc\n"))
        self.assertEqual(run_whole(b"abc\n$", b"abc\n"), (0, 4))

    def test_both_anchors(self):
        self.assertEqual(run_whole(b"^a+$", b"aaa"), (0, 3))
        self.assertIsNone(run_whole(b"^a+$", b"aaab"))
        self.assertEqual(run_whole(b"^$", b""), (0, 0))
        self.assertIsNone(run_whole(b"^$", b"\n"))

    def test_dot_matches_newline_and_nul(self):
        self.assertEqual(run_whole(b"a.c", b"a\nc"), (0, 3))
        self.assertEqual(run_whole(b"a.c", b"a\x00c"), (0, 3))

    def test_anchor_alone(self):
        self.assertEqual(run_whole(b"^", b"ab"), (0, 0))
        self.assertEqual(run_whole(b"$", b"ab"), (2, 2))


class TestSyntaxFeatures(unittest.TestCase):
    def test_hex_escape(self):
        self.assertEqual(run_whole(b"\x41\x42", b"ZABZ"), (1, 3))
        self.assertEqual(run_whole(b"\x00", b"a\x00b"), (1, 2))

    def test_escaped_metacharacters(self):
        self.assertEqual(run_whole(b"a\.b", b"axa.b"), (2, 5))
        self.assertEqual(run_whole(b"\(\*\)", b"(*)"), (0, 3))
        self.assertEqual(run_whole(b"\$", b"a$"), (1, 2))

    def test_char_class_ranges_and_negation(self):
        self.assertEqual(run_whole(b"[a-c]+", b"xyabcz"), (2, 5))
        self.assertEqual(run_whole(b"[^a-z]+", b"ab12cd"), (2, 4))
        self.assertEqual(run_whole(b"[]a]+", b"a]a"), (0, 3))
        self.assertEqual(run_whole(b"[a-]+", b"b-a"), (1, 3))

    def test_quantifiers(self):
        self.assertEqual(run_whole(b"ab*c", b"abbbc"), (0, 5))
        self.assertEqual(run_whole(b"ab+c", b"ac abbc"), (3, 7))
        self.assertEqual(run_whole(b"colou?r", b"xcolor"), (1, 6))


class TestChunkInvariance(unittest.TestCase):
    """Any chunking of a field must yield identical hits and evidence."""

    CASES = [
        (b"a|aa", b"aa"),
        (b"(a*)*b", b"aaab"),
        (b"(a|ab)(c|bcd)d?", b"xxabcddyy"),
        (b"^a.c$", b"a\nc"),
        (b"abc$", b"abc\n"),
        (b"abc\n$", b"abc\n"),
        (b"[^a-z]+", b"ab\x0012\ncd"),
        (b"x*y+", b"xxxyy"),
        (b"", b"ab"),
        (b"^$", b""),
        (b"\x41|B\x42", b"aABB"),
        (b"(ab|a)(b?)c", b"abc"),
    ]

    def test_all_chunkings_match_whole_field_result(self):
        for pattern, data in self.CASES:
            expected = run_whole(pattern, data)
            for chunks in chunkings(data):
                with self.subTest(pattern=pattern, data=data, chunks=chunks):
                    self.assertEqual(run_chunked(pattern, data, chunks), expected)


class TestAgainstReference(unittest.TestCase):
    """Evidence must match the independent full-field reference."""

    PATTERNS = [
        b"a|aa",
        b"(a*)*",
        b"(a*)*b",
        b"(a|aa)*b?",
        b"(a|ab)(c|bcd)",
        b"(ab|a)(b?)",
        b"x*y+",
        b"a.c",
        b"^a.c$",
        b"^a+",
        b"a+$",
        b"^$",
        b"$",
        b"^",
        b"[^a-z]+",
        b"[a-c]+d?",
        b"\x41\x42",
        b"",
        b"b?",
        b"(|a)b",
        b"a(b|c)*d",
    ]
    FIELDS = [
        b"",
        b"a",
        b"aa",
        b"aaa",
        b"ab",
        b"aaab",
        b"abcd",
        b"abc\n",
        b"a\nc",
        b"\x00a\x00",
        b"xxabcdd",
        b"aabbcc",
        b"\n",
        b"AB",
    ]

    def test_matches_reference(self):
        for pattern in self.PATTERNS:
            for data in self.FIELDS:
                with self.subTest(pattern=pattern, data=data):
                    self.assertEqual(
                        run_whole(pattern, data),
                        reference_leftmost_longest(pattern, data),
                    )

    def test_chunked_matches_reference(self):
        rng = random.Random(99)
        cases = list(itertools.product(self.PATTERNS, self.FIELDS))
        rng.shuffle(cases)
        for pattern, data in cases[:60]:
            chunks = [data[i : i + 2] for i in range(0, len(data), 2)]
            with self.subTest(pattern=pattern, data=data):
                self.assertEqual(
                    run_chunked(pattern, data, chunks),
                    reference_leftmost_longest(pattern, data),
                )


class TestRuleSetBehavior(unittest.TestCase):
    def test_duplicate_rule_id_rejected(self):
        rs = RuleSet()
        rs.add_rule("r1", b"a")
        with self.assertRaises(ValueError):
            rs.add_rule("r1", b"b")

    def test_ruleset_reusable_across_sessions(self):
        rs = RuleSet()
        rs.load([("r1", b"a|aa"), ("r2", b"^x+y$")])
        s1 = rs.begin()
        s1.feed(b"aa")
        s2 = rs.begin()
        s2.feed(b"xxy")
        self.assertEqual(s1.finish(), {"r1": (0, 2)})
        self.assertEqual(s2.finish(), {"r2": (0, 3)})

    def test_only_matched_rules_returned(self):
        rs = RuleSet()
        rs.load([("hit", b"b"), ("miss", b"zzz")])
        s = rs.begin()
        s.feed(b"abc")
        self.assertEqual(s.finish(), {"hit": (1, 2)})

    def test_load_order_does_not_change_results(self):
        rules = [("r1", b"a|aa"), ("r2", b"b+"), ("r3", b"^c$"), ("r4", b"")]
        data = b"aabb"
        baseline = None
        for perm in itertools.permutations(rules):
            rs = RuleSet()
            rs.load(list(perm))
            s = rs.begin()
            s.feed(data)
            result = s.finish()
            if baseline is None:
                baseline = result
            self.assertEqual(result, baseline)
        self.assertEqual(
            baseline, {"r1": (0, 2), "r2": (2, 4), "r4": (0, 0)}
        )

    def test_empty_chunks_are_not_field_boundaries(self):
        rs = RuleSet()
        rs.add_rule("r", b"^ab$")
        s = rs.begin()
        s.feed(b"")
        s.feed(b"a")
        s.feed(b"")
        s.feed(b"b")
        s.feed(b"")
        self.assertEqual(s.finish(), {"r": (0, 2)})

    def test_bytes_like_chunks_accepted(self):
        rs = RuleSet()
        rs.add_rule("r", b"abc")
        s = rs.begin()
        s.feed(bytearray(b"ab"))
        s.feed(memoryview(b"c"))
        self.assertEqual(s.finish(), {"r": (0, 3)})

    def test_feed_after_finish_rejected(self):
        rs = RuleSet()
        rs.add_rule("r", b"a")
        s = rs.begin()
        s.feed(b"a")
        s.finish()
        with self.assertRaises(RuntimeError):
            s.feed(b"b")
        with self.assertRaises(RuntimeError):
            s.finish()

    def test_str_patterns_accepted(self):
        rs = RuleSet()
        rs.add_rule("r", "a+")
        s = rs.begin()
        s.feed(b"caaa")
        self.assertEqual(s.finish(), {"r": (1, 4)})


class RandomPatternGenerator:
    """Generates random patterns inside the supported subset."""

    LITERALS = b"abcAB01 \n"

    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)

    def pattern(self, depth: int = 0) -> bytes:
        rng = self.rng
        choice = rng.random()
        if depth > 2 or choice < 0.35:
            return self.atom(depth)
        if choice < 0.55:
            return self.quantifiable_atom(depth) + rng.choice([b"*", b"+", b"?"])
        if choice < 0.7:
            return b"".join(self.pattern(depth + 1) for _ in range(rng.randint(1, 3)))
        if choice < 0.85:
            return b"|".join(self.pattern(depth + 1) for _ in range(rng.randint(2, 3)))
        return b"(" + self.pattern(depth + 1) + b")" + rng.choice([b"", b"*", b"+", b"?"])

    def atom(self, depth: int) -> bytes:
        rng = self.rng
        choice = rng.random()
        if choice < 0.5:
            return bytes([rng.choice(self.LITERALS)])
        if choice < 0.6:
            return b"."
        if choice < 0.7:
            return b"[" + rng.choice([b"a-c", b"^a-c", b"a-z", b"^ab", b"\x00-\x7f"]) + b"]"
        if choice < 0.8:
            return rng.choice([b"^", b"$"])
        if choice < 0.9:
            return b"\\x%02x" % rng.randint(0, 255)
        return b"(" + self.pattern(depth + 1) + b")"

    def quantifiable_atom(self, depth: int) -> bytes:
        # Anchors may not be quantified (invalid in Python's re too).
        while True:
            atom = self.atom(depth)
            if atom not in (b"^", b"$"):
                return atom


class TestRandomizedDifferential(unittest.TestCase):
    """Random patterns x random fields, checked against the reference."""

    def test_random_differential(self):
        gen = RandomPatternGenerator(20261004)
        rng = random.Random(7)
        alphabet = b"abcAB01 \n\x00"
        for i in range(400):
            pattern = gen.pattern()
            data = bytes(rng.choice(alphabet) for _ in range(rng.randint(0, 9)))
            expected = reference_leftmost_longest(pattern, data)
            with self.subTest(pattern=pattern, data=data):
                self.assertEqual(run_whole(pattern, data), expected)
                # Also verify a random chunked delivery agrees.
                chunks = []
                rest = data
                while rest:
                    cut = rng.randint(0, len(rest))
                    chunks.append(rest[:cut])
                    rest = rest[cut:]
                self.assertEqual(run_chunked(pattern, data, chunks), expected)


if __name__ == "__main__":
    unittest.main()
