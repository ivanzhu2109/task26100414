"""Streaming byte-pattern rule matching for traffic inspection.

Public API:
    RuleSet       -- holds a set of uniquely identified, compiled rules.
    CheckSession  -- one field inspection: feed chunks, then finish().
"""

from .rules import CheckSession, RuleSet

__all__ = ["RuleSet", "CheckSession"]
