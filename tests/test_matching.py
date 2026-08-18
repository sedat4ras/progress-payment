from app.config import AUTO_APPROVE_THRESHOLD
from app.engine.backends.rule_only import RuleOnlyBackend
from app.engine.matching import MatchIndex, match_line
from app.models import ItemCategory, MatchMethod

BACKEND = RuleOnlyBackend()


def _match(contract, text, unit=None):
    index = MatchIndex.build(contract)
    return match_line(index, text, unit, BACKEND, AUTO_APPROVE_THRESHOLD)


def test_exact_description_is_certain(contract):
    proposal = _match(contract, "Split System Air Filter")
    assert proposal.method is MatchMethod.EXACT
    assert proposal.item_code == "FLT-001"
    assert proposal.confidence == 1.0


def test_exact_match_survives_casing_and_punctuation(contract):
    proposal = _match(contract, "SCHEDULED MAINTENANCE / SPLIT SYSTEM")
    assert proposal.method is MatchMethod.EXACT
    assert proposal.item_code == "SVC-001"


def test_confirmed_alias_is_matched(contract):
    proposal = _match(contract, "Split System Service")
    assert proposal.method is MatchMethod.ALIAS
    assert proposal.item_code == "SVC-001"


def test_typo_is_recovered_by_fuzzy(contract):
    proposal = _match(contract, "Split Sytsem Air Fillter")
    assert proposal.item_code == "FLT-001"
    assert proposal.confidence >= AUTO_APPROVE_THRESHOLD


def test_work_absent_from_contract_yields_no_match(contract):
    proposal = _match(contract, "Roof membrane waterproofing renewed")
    assert proposal.item_code is None
    assert proposal.method is MatchMethod.NONE


def test_shared_word_does_not_produce_a_confident_match(contract):
    """The failure this design exists to prevent.

    'Industrial Fan Balancing' is not in this contract. Partial string overlap
    with 'Fan Motor 1/4 HP' must never be enough to price it.
    """
    proposal = _match(contract, "Industrial Fan Balancing")
    assert proposal.confidence < AUTO_APPROVE_THRESHOLD


def test_rule_only_backend_always_abstains(contract):
    assert BACKEND.propose("any text at all", []) is None


def test_the_unit_settles_a_material_labour_collision(contract):
    """Metres are only ever a material in this contract, so labour is not an
    answer to be scored down - it is dropped before scoring."""
    proposal = _match(contract, "copper pipe", unit="m")

    assert proposal.item_code == "PIP-001"
    assert proposal.conflict_code is None


def test_the_unit_can_settle_it_the_other_way(contract):
    proposal = _match(contract, "copper pipe", unit="hr")

    assert proposal.item_code == "LAB-005"
    assert proposal.conflict_code is None


def test_a_unit_used_by_both_categories_leaves_the_collision_open(contract):
    """'ea' prices both parts and labour here, so it disambiguates nothing and
    the machine has to admit it cannot tell the two readings apart."""
    proposal = _match(contract, "copper pipe", unit="ea")

    assert proposal.conflict_code is not None
    assert {proposal.item_code, proposal.conflict_code} == {"PIP-001", "LAB-005"}


def test_the_conflict_rationale_names_both_readings(contract):
    proposal = _match(contract, "copper pipe", unit="ea")

    assert "material" in proposal.rationale
    assert "labour" in proposal.rationale


def test_an_exact_description_is_not_second_guessed_by_the_unit(contract):
    """A verbatim catalogue hit is a lookup, not a guess. A wrong unit on such
    a line is caught later by the pricing check, not by suppressing the match."""
    proposal = _match(contract, "Copper Pipe 1/4 inch", unit="hr")

    assert proposal.method is MatchMethod.EXACT
    assert proposal.item_code == "PIP-001"


def test_the_index_reads_categories_off_the_price_list(contract):
    index = MatchIndex.build(contract)

    assert index.categories_for_unit("hr") == {ItemCategory.LABOUR}
    assert index.categories_for_unit("m") == {ItemCategory.MATERIAL}
    assert index.categories_for_unit("ea") == {ItemCategory.MATERIAL, ItemCategory.LABOUR}
    assert index.categories_for_unit(None) is None
    assert index.categories_for_unit("furlong") is None
