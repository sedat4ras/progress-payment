from decimal import Decimal

import pytest

from app.engine.normalize import normalize, normalize_for_match
from app.engine.pricing import check_quantity, check_unit, gst_of, line_net
from app.models import ContractItem, FlagCode, ItemCategory


def _item(unit="ea", price="450.00", limit=None):
    return ContractItem(
        code="FLT-001",
        description="Split System Air Filter",
        category=ItemCategory.MATERIAL,
        unit=unit,
        unit_price=Decimal(price),
        max_quantity_per_slip=limit,
    )


@pytest.mark.parametrize(
    "price,qty,expected",
    [
        ("450.00", 3, "1350.00"),
        ("950.00", 2.5, "2375.00"),
        ("1250.33", 3, "3750.99"),
        ("0.01", 3, "0.03"),
    ],
)
def test_line_net_rounds_to_cents(price, qty, expected):
    assert line_net(Decimal(price), qty) == Decimal(expected)


def test_gst_is_ten_percent():
    assert gst_of(Decimal("1350.00")) == Decimal("135.00")


def test_quantity_within_limit_passes():
    assert check_quantity(_item(limit=12), 12) is None


def test_quantity_above_limit_is_flagged():
    flag, message = check_quantity(_item(limit=12), 13)
    assert flag is FlagCode.QUANTITY_LIMIT_EXCEEDED
    assert "12" in message


def test_non_positive_quantity_is_flagged():
    flag, _ = check_quantity(_item(), 0)
    assert flag is FlagCode.NON_POSITIVE_QUANTITY


def test_unit_mismatch_is_flagged():
    flag, _ = check_unit(_item(unit="hr"), "ea")
    assert flag is FlagCode.UNIT_MISMATCH


def test_unit_comparison_ignores_case():
    assert check_unit(_item(unit="ea"), "EA") is None


def test_accents_fold_to_ascii():
    assert normalize("Légionella Réplacement") == "legionella replacement"
    assert normalize("LEGIONELLA replacement") == "legionella replacement"


def test_normalize_for_match_drops_filler_words():
    assert normalize_for_match("3 x Split System Filter was replaced") == "3 split system filter replaced"
