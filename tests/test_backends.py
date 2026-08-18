"""Guards on what a model is allowed to influence. No network involved."""

from decimal import Decimal

import pytest

from app.config import LLM_CONFIDENCE_CAP
from app.engine.backends.base import Candidate
from app.engine.backends.prompt import SYSTEM_PROMPT, build_user_prompt, parse_proposal
from app.models import ContractItem, ItemCategory, MatchMethod


def _item(code, description, price, category=ItemCategory.MATERIAL, unit="ea"):
    return ContractItem(
        code=code,
        description=description,
        category=category,
        unit=unit,
        unit_price=Decimal(price),
    )


@pytest.fixture
def candidates():
    return [
        Candidate(_item("FLT-001", "Split System Air Filter", "450.00"), 0.72),
        Candidate(_item("FLT-002", "Cassette Type Air Filter", "780.00"), 0.68),
    ]


@pytest.fixture
def mixed_candidates():
    return [
        Candidate(_item("PIP-001", "Copper Pipe 1/4 inch", "34.00", unit="m"), 0.71),
        Candidate(
            _item(
                "LAB-005",
                "Copper Pipe Installation",
                "165.00",
                category=ItemCategory.LABOUR,
                unit="hr",
            ),
            0.63,
        ),
    ]


def test_prompt_never_exposes_prices(candidates):
    prompt = build_user_prompt("klma fltr splt", candidates)
    assert "450" not in prompt
    assert "780" not in prompt


def test_the_prompt_marks_every_candidate_as_material_or_labour(mixed_candidates):
    """The model cannot be asked to keep parts and labour apart if the list it
    is shown does not say which is which."""
    prompt = build_user_prompt("copper pipe", mixed_candidates)

    assert "PIP-001" in prompt and "MATERIAL" in prompt
    assert "LAB-005" in prompt and "LABOUR" in prompt


def test_the_system_prompt_forbids_crossing_the_category_line(mixed_candidates):
    assert "MATERIAL" in SYSTEM_PROMPT and "LABOUR" in SYSTEM_PROMPT
    assert "never interchangeable" in SYSTEM_PROMPT


def test_valid_choice_is_accepted(candidates):
    proposal = parse_proposal(
        '{"code": "FLT-001", "confidence": 0.82, "reason": "split type filter"}',
        candidates,
        "test",
    )
    assert proposal.item_code == "FLT-001"
    assert proposal.method is MatchMethod.LLM
    assert proposal.confidence == 0.82


def test_code_outside_the_candidate_list_is_discarded(candidates):
    """A hallucinated item code must not reach the pricing engine."""
    proposal = parse_proposal(
        '{"code": "FLT-999", "confidence": 0.99, "reason": "invented"}',
        candidates,
        "test",
    )
    assert proposal is None


def test_abstention_is_respected(candidates):
    assert parse_proposal('{"code": "NONE", "confidence": 0.4}', candidates, "test") is None


def test_confidence_is_capped_below_a_confirmed_alias(candidates):
    proposal = parse_proposal(
        '{"code": "FLT-002", "confidence": 1.0, "reason": "certain"}', candidates, "test"
    )
    assert proposal.confidence == LLM_CONFIDENCE_CAP


def test_json_wrapped_in_prose_is_still_read(candidates):
    proposal = parse_proposal(
        'Certainly!\n```json\n{"code": "FLT-001", "confidence": 0.9}\n```\n',
        candidates,
        "test",
    )
    assert proposal.item_code == "FLT-001"


def test_unparseable_response_is_an_abstention(candidates):
    assert parse_proposal("no idea", candidates, "test") is None


def test_missing_confidence_defaults_to_zero(candidates):
    proposal = parse_proposal('{"code": "FLT-001"}', candidates, "test")
    assert proposal.confidence == 0.0
