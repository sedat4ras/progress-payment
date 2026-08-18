"""Maps a free-text slip line onto exactly one contract item.

Order matters. Each layer is cheaper and more trustworthy than the next:

    exact  -> the technician typed the catalogue description
    alias  -> an expert has confirmed this phrasing before
    fuzzy  -> string distance, scored down when the result is ambiguous
    llm    -> last resort, and only ever allowed to pick from a closed list

The layer that produced a match is stored on the payment line, so any figure
in a progress payment can be traced back to how it was decided.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from app.config import (
    CATEGORY_AMBIGUITY_MARGIN,
    FUZZY_FLOOR,
    LLM_CANDIDATE_COUNT,
    NO_MATCH_CEILING,
)
from app.engine.backends.base import Candidate, MatcherBackend, Proposal
from app.engine.normalize import normalize, normalize_for_match
from app.models import Contract, ContractItem, ItemCategory, MatchMethod

EXACT_CONFIDENCE = 1.0
ALIAS_CONFIDENCE = 0.99


@dataclass
class MatchIndex:
    """Lookup structures for one contract, built once and reused per slip."""

    contract_id: int
    exact: dict[str, ContractItem] = field(default_factory=dict)
    alias: dict[str, ContractItem] = field(default_factory=dict)
    choices: list[str] = field(default_factory=list)
    choice_items: list[ContractItem] = field(default_factory=list)
    texts_by_item: dict[int, list[str]] = field(default_factory=dict)
    units: dict[str, set[ItemCategory]] = field(default_factory=dict)

    @classmethod
    def build(cls, contract: Contract) -> "MatchIndex":
        index = cls(contract_id=contract.id)
        for item in contract.items:
            index.exact[normalize(item.description)] = item
            index._add_choice(item.description, item)
            index.units.setdefault(item.unit.lower(), set()).add(item.category)
            for alias in item.aliases:
                index.alias[alias.normalized_text] = item
                index._add_choice(alias.normalized_text, item)
        return index

    def categories_for_unit(self, unit: str | None) -> set[ItemCategory] | None:
        """Which categories this contract prices in the given unit.

        Read off the price list rather than hardcoded, so it stays true for any
        catalogue. In practice hours are only ever labour and kilograms only
        ever materials, which eliminates most of the candidates that would
        otherwise let a part be confused with the work of fitting it.

        None means the unit says nothing useful and no filtering applies.
        """
        if not unit:
            return None
        return self.units.get(unit.strip().lower()) or None

    def _add_choice(self, text: str, item: ContractItem) -> None:
        normalized = normalize_for_match(text)
        self.choices.append(normalized)
        self.choice_items.append(item)
        self.texts_by_item.setdefault(item.id, []).append(normalized)

    def register_alias(self, normalized_text: str, item: ContractItem) -> None:
        """Keep an in-memory index in step with an alias just written to the DB."""
        self.alias[normalized_text] = item
        self._add_choice(normalized_text, item)


def _strict_score(query: str, texts: list[str]) -> float:
    """Whole-string similarity, on purpose.

    Retrieval uses WRatio because it is forgiving enough to surface the right
    item despite typos. It is far too forgiving to *decide* with: a catalogue
    full of items sharing words ("Fan Motor 1/4 HP" vs "Industrial Fan Balancing") scores
    ~90 on partial overlap alone. Confidence is therefore recomputed with
    scorers that punish tokens the query does not account for.
    """
    return max(
        max(fuzz.ratio(query, text), fuzz.token_sort_ratio(query, text))
        for text in texts
    )


def _ranked_candidates(
    index: MatchIndex,
    query: str,
    allowed: set[ItemCategory] | None = None,
) -> list[Candidate]:
    """Recall with WRatio, then re-score strictly and rank on that.

    `allowed` is the category filter from the slip line's unit. Candidates are
    dropped before scoring rather than penalised after it: a labour item is not
    a weak answer for a line measured in kilograms, it is not an answer at all.
    """
    hits = process.extract(
        query,
        index.choices,
        scorer=fuzz.WRatio,
        limit=LLM_CANDIDATE_COUNT * 3,
        score_cutoff=FUZZY_FLOOR,
    )

    seen: set[int] = set()
    candidates: list[Candidate] = []
    for _text, _score, position in hits:
        item = index.choice_items[position]
        if item.id in seen:
            continue
        if allowed is not None and item.category not in allowed:
            continue
        seen.add(item.id)
        strict = _strict_score(query, index.texts_by_item[item.id])
        candidates.append(Candidate(item=item, score=strict / 100))

    return sorted(candidates, key=lambda c: c.score, reverse=True)


def _category_conflict(candidates: list[Candidate]) -> Candidate | None:
    """The best candidate from the other category, if it is too close to call.

    A part and the labour of fitting that part are described with the same
    words, so text similarity alone cannot separate them. When the two readings
    are within the margin, the honest answer is that the machine does not know
    which one the technician meant.
    """
    if len(candidates) < 2:
        return None

    best = candidates[0]
    rival = next(
        (c for c in candidates[1:] if c.item.category is not best.item.category),
        None,
    )
    if rival is None:
        return None

    return rival if (best.score - rival.score) * 100 < CATEGORY_AMBIGUITY_MARGIN else None


def _fuzzy_confidence(candidates: list[Candidate]) -> float:
    """Penalise ambiguity: a close runner-up means we are not actually sure."""
    best = candidates[0].score
    runner_up = candidates[1].score if len(candidates) > 1 else 0.0
    margin = (best - runner_up) * 100

    if margin >= 10:
        adjustment = 1.0
    elif margin >= 5:
        adjustment = 0.95
    else:
        adjustment = 0.85

    return round(best * adjustment, 3)


def match_line(
    index: MatchIndex,
    raw_description: str,
    unit: str | None,
    backend: MatcherBackend,
    threshold: float,
) -> Proposal:
    normalized = normalize(raw_description)

    # Exact and alias hits skip the category guards deliberately. Both are
    # verbatim lookups against the catalogue, so there is nothing to be
    # ambiguous about; a wrong unit on such a line is caught by `check_unit`.
    item = index.exact.get(normalized)
    if item is not None:
        return Proposal(
            item.code,
            EXACT_CONFIDENCE,
            MatchMethod.EXACT,
            "Identical to the catalogue description.",
        )

    item = index.alias.get(normalized)
    if item is not None:
        return Proposal(
            item.code,
            ALIAS_CONFIDENCE,
            MatchMethod.ALIAS,
            "A phrasing recorded in the contract's own list of synonyms.",
        )

    allowed = index.categories_for_unit(unit)
    candidates = _ranked_candidates(index, normalize_for_match(raw_description), allowed)
    if not candidates or candidates[0].score < NO_MATCH_CEILING:
        return Proposal(
            None,
            0.0,
            MatchMethod.NONE,
            "Nothing in the contract price list is close to this.",
        )

    confidence = _fuzzy_confidence(candidates)
    best = candidates[0]
    rival = _category_conflict(candidates)

    if rival is not None:
        return Proposal(
            best.item.code,
            confidence,
            MatchMethod.FUZZY,
            f"This reads as either {best.item.description} "
            f"({best.item.category.value}) or {rival.item.description} "
            f"({rival.item.category.value}), and the wording does not separate them.",
            conflict_code=rival.item.code,
        )

    if confidence >= threshold:
        return Proposal(
            best.item.code,
            confidence,
            MatchMethod.FUZZY,
            f"{best.score * 100:.0f}% text similarity, clear of the next candidate.",
        )

    if backend.available():
        # The candidate list is already category-filtered, so the model cannot
        # answer across the boundary even if it wanted to.
        proposal = backend.propose(raw_description, candidates[:LLM_CANDIDATE_COUNT])
        if proposal is not None:
            return proposal

    return Proposal(
        best.item.code,
        confidence,
        MatchMethod.FUZZY,
        f"Weak similarity ({best.score * 100:.0f}%) or several candidates too close to call.",
    )
