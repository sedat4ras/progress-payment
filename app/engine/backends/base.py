"""The seam that lets the same core run offline or against a hosted API.

A backend never sees prices and never returns one. It is handed a free-text
line plus a *closed* list of contract items and may only pick one of them or
abstain. Everything downstream of this is deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.models import ContractItem, MatchMethod


@dataclass
class Candidate:
    item: ContractItem
    score: float          # 0..1, how close the deterministic layer thought it was


@dataclass
class Proposal:
    item_code: str | None
    confidence: float
    method: MatchMethod
    rationale: str
    # Set when a candidate from the other category scored too close to call.
    # The proposal still names its best guess so a reviewer can see both
    # readings, but pricing refuses to act on it whatever the confidence says.
    conflict_code: str | None = None


@runtime_checkable
class MatcherBackend(Protocol):
    name: str

    def available(self) -> bool:
        """Whether this backend can serve requests right now."""

    def propose(self, line_text: str, candidates: list[Candidate]) -> Proposal | None:
        """Pick one candidate or abstain by returning None."""
