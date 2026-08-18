"""Arithmetic and contractual limit checks.

Pure functions, no database and no model. Every number that ends up on a
progress payment is produced here, from a unit price that was read out of the
contract - never generated, never inferred.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.config import GST_RATE
from app.models import ContractItem, FlagCode

CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def line_net(unit_price: Decimal, quantity: float) -> Decimal:
    return money(Decimal(unit_price) * Decimal(str(quantity)))


def gst_of(net: Decimal) -> Decimal:
    return money(Decimal(net) * GST_RATE)


def check_quantity(item: ContractItem, quantity: float) -> tuple[FlagCode, str] | None:
    if quantity is None or quantity <= 0:
        return (
            FlagCode.NON_POSITIVE_QUANTITY,
            f"Quantity is not valid ({quantity}).",
        )

    limit = item.max_quantity_per_slip
    if limit is not None and quantity > limit:
        return (
            FlagCode.QUANTITY_LIMIT_EXCEEDED,
            f"The contract caps {item.code} at {_fmt(limit)} {item.unit} per slip; "
            f"this slip reports {_fmt(quantity)} {item.unit}.",
        )

    return None


def check_unit(item: ContractItem, unit: str) -> tuple[FlagCode, str] | None:
    if unit and unit.strip().lower() != item.unit.lower():
        return (
            FlagCode.UNIT_MISMATCH,
            f"{item.code} is priced per '{item.unit}' in the contract, "
            f"but the slip says '{unit}'.",
        )
    return None


def _fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)
