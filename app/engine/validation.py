"""Deterministic gate that runs before anything else.

No language model is involved here and none ever should be: these are the
checks that decide whether a progress payment may exist at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Contract, Customer, FlagCode, ServiceSlip


@dataclass
class ValidationResult:
    customer: Customer | None = None
    contract: Contract | None = None
    failures: list[tuple[FlagCode, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def validate_slip(session: Session, slip: ServiceSlip) -> ValidationResult:
    result = ValidationResult()

    customer = session.scalar(
        select(Customer).where(Customer.code == slip.customer_code)
    )
    if customer is None:
        result.failures.append(
            (
                FlagCode.NO_CUSTOMER,
                f"No customer is registered under the code '{slip.customer_code}'.",
            )
        )
        return result

    result.customer = customer

    contract = _active_contract(session, customer.id, slip.service_date)
    if contract is None:
        result.failures.append(
            (
                FlagCode.NO_ACTIVE_CONTRACT,
                f"No contract was active for {customer.name} on "
                f"{slip.service_date:%d %b %Y}.",
            )
        )
    else:
        result.contract = contract

    if not slip.lines:
        result.failures.append(
            (FlagCode.EMPTY_SLIP, "The slip reports no work at all.")
        )

    return result


def _active_contract(session: Session, customer_id: int, on: date) -> Contract | None:
    return session.scalar(
        select(Contract).where(
            Contract.customer_id == customer_id,
            Contract.period_start <= on,
            Contract.period_end >= on,
        )
    )
