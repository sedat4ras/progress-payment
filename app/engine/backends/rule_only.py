"""Backend that always abstains.

With this selected the system runs on exact/alias/fuzzy matching alone. It is
the CI default: the test suite must pass with no model of any kind running.
"""

from app.engine.backends.base import Candidate, Proposal


class RuleOnlyBackend:
    name = "rules"

    def available(self) -> bool:
        return True

    def propose(self, line_text: str, candidates: list[Candidate]) -> Proposal | None:
        return None
