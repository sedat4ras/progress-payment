import os
import tempfile
from datetime import date
from decimal import Decimal

import pytest

os.environ["PP_DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["PP_MATCHER_BACKEND"] = "rules"


@pytest.fixture
def session():
    from app.db import SessionLocal, init_db

    init_db(drop=True)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def contract(session):
    """One customer, one 2025 contract, a handful of deliberately similar items."""
    from app.models import Contract, ContractItem, Customer, ItemAlias, ItemCategory

    customer = Customer(code="ACM", name="Acme Facilities Pty Ltd")
    session.add(customer)
    session.flush()

    contract = Contract(
        customer_id=customer.id,
        code="CTR-ACM-2025H1",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 6, 30),
    )
    session.add(contract)
    session.flush()

    # PIP-001 and LAB-005 are the deliberate trap: a part and the labour of
    # fitting that part, described in almost the same words and separable only
    # by the unit the technician wrote.
    items = [
        ("FLT-001", "Split System Air Filter", ItemCategory.MATERIAL, "ea", "68.00", None),
        ("MOT-001", "Fan Motor 1/4 HP", ItemCategory.MATERIAL, "ea", "465.00", None),
        ("SVC-001", "Scheduled Maintenance - Split System", ItemCategory.LABOUR, "ea", "128.00", 40),
        ("LAB-001", "Breakdown Callout - Business Hours", ItemCategory.LABOUR, "hr", "142.00", 12),
        ("PIP-001", "Copper Pipe 1/4 inch", ItemCategory.MATERIAL, "m", "34.00", None),
        ("LAB-005", "Copper Pipe Installation", ItemCategory.LABOUR, "hr", "165.00", None),
    ]
    for code, desc, category, unit, price, limit in items:
        session.add(
            ContractItem(
                contract_id=contract.id,
                code=code,
                description=desc,
                category=category,
                unit=unit,
                unit_price=Decimal(price),
                max_quantity_per_slip=limit,
            )
        )
    session.flush()

    split = next(i for i in contract.items if i.code == "SVC-001")
    session.add(
        ItemAlias(
            contract_item_id=split.id,
            normalized_text="split system service",
            source="seed",
        )
    )
    session.flush()
    session.refresh(contract)
    return contract


@pytest.fixture
def make_slip(session):
    from app.models import ServiceSlip, SlipLine, WorkType

    counter = {"n": 0}

    def _make(lines, customer_code="ACM", service_date=date(2025, 3, 10)):
        counter["n"] += 1
        slip = ServiceSlip(
            slip_no=f"TEST-{counter['n']:04d}",
            customer_code=customer_code,
            service_date=service_date,
            technician="Test Technician",
            work_type=WorkType.SERVICE,
        )
        session.add(slip)
        session.flush()
        for line_no, (desc, qty, unit) in enumerate(lines, start=1):
            session.add(
                SlipLine(
                    slip_id=slip.id,
                    line_no=line_no,
                    raw_description=desc,
                    quantity=qty,
                    unit=unit,
                )
            )
        session.flush()
        session.refresh(slip)
        return slip

    return _make
