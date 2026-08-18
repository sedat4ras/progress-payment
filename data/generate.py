"""Synthetic data generator.

Builds three customers, two contract periods each, and a batch of service
slips that deliberately contains the messy cases the engine has to survive:
abbreviations, typos, work that is not in the contract at all, another
customer's speciality items, quantities above the contractual ceiling,
unknown customers, out-of-period dates and empty slips.

Every generated line carries `truth_item_code`, which is what
`scripts/evaluate.py` scores the engine against.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.db import init_db, session_scope
from app.models import (
    Contract,
    ContractItem,
    Customer,
    ItemAlias,
    ServiceSlip,
    SlipLine,
    WorkType,
)
from app.engine.normalize import normalize
from data.catalog import (
    CATEGORY_TRAP_PHRASES,
    CUSTOMER_ONLY_ITEMS,
    CUSTOMERS,
    OFF_CONTRACT_PHRASES,
    SEED_ALIASES,
    SHARED_ITEMS,
    TECHNICIANS,
)

PERIODS = [
    ("2025H1", date(2025, 1, 1), date(2025, 6, 30), Decimal("1.00")),
    ("2025H2", date(2025, 7, 1), date(2025, 12, 31), Decimal("1.15")),
]

SLIP_MIX = {
    "normal": 128,
    "category_trap": 12,
    "off_contract": 18,
    "cross_specialty": 12,
    "over_limit": 10,
    "unknown_customer": 8,
    "no_active_contract": 7,
    "empty": 5,
}

QTY_RANGE = {
    "ea": (1, 4),
    "hr": (1, 6),
    "kg": (1, 4),
    "m": (3, 20),
    "L": (2, 10),
}


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _abbreviate(text: str, rng: random.Random) -> str:
    words = text.replace("-", " ").split()
    out = []
    for w in words:
        if len(w) > 5 and rng.random() < 0.6:
            out.append(w[:4] + ".")
        else:
            out.append(w)
    return " ".join(out).lower()


def _typo(text: str, rng: random.Random) -> str:
    chars = list(text)
    letters = [i for i, c in enumerate(chars) if c.isalpha()]
    if len(letters) < 4:
        return text
    for _ in range(rng.randint(1, 2)):
        i = rng.choice(letters)
        if rng.random() < 0.5:
            chars[i] = ""
        elif i + 1 < len(chars):
            chars[i], chars[i + 1] = chars[i + 1], chars[i]
    return "".join(chars)


def _verbose(text: str, qty: float, rng: random.Random) -> str:
    template = rng.choice(
        [
            "replaced {q} x {d}",
            "{d} completed",
            "{d} - carried out by site crew",
            "{q} {d}",
        ]
    )
    return template.format(q=_fmt_qty(qty), d=text.lower())


def _fmt_qty(qty: float) -> str:
    return str(int(qty)) if float(qty).is_integer() else str(qty)


def _phrase_for(item: ContractItem, qty: float, rng: random.Random) -> str:
    """Turn a contract item description into something a technician would type."""
    roll = rng.random()
    aliases = SEED_ALIASES.get(item.code, [])
    if roll < 0.30:
        return item.description
    if roll < 0.45:
        return normalize(item.description)
    if roll < 0.60 and aliases:
        return rng.choice(aliases)
    if roll < 0.75:
        return _abbreviate(item.description, rng)
    if roll < 0.90:
        return _typo(item.description, rng)
    return _verbose(item.description, qty, rng)


def _quantity(unit: str, rng: random.Random) -> float:
    lo, hi = QTY_RANGE.get(unit, (1, 4))
    if unit == "hr" and rng.random() < 0.3:
        return rng.randint(lo, hi) + 0.5
    return float(rng.randint(lo, hi))


def build_contracts(session, rng: random.Random) -> dict[str, list[Contract]]:
    contracts_by_customer: dict[str, list[Contract]] = {}

    for code, name, multiplier in CUSTOMERS:
        customer = Customer(code=code, name=name)
        session.add(customer)
        session.flush()
        contracts_by_customer[code] = []

        specials = CUSTOMER_ONLY_ITEMS.get(code, [])

        for period_code, start, end, period_mult in PERIODS:
            contract = Contract(
                customer_id=customer.id,
                code=f"CTR-{code}-{period_code}",
                period_start=start,
                period_end=end,
            )
            session.add(contract)
            session.flush()

            for item_code, desc, category, unit, base, max_qty in SHARED_ITEMS + specials:
                price = _money(Decimal(base) * Decimal(str(multiplier)) * period_mult)
                item = ContractItem(
                    contract_id=contract.id,
                    code=item_code,
                    description=desc,
                    category=category,
                    unit=unit,
                    unit_price=price,
                    max_quantity_per_slip=max_qty,
                )
                session.add(item)
                session.flush()

                for alias in SEED_ALIASES.get(item_code, []):
                    session.add(
                        ItemAlias(
                            contract_item_id=item.id,
                            normalized_text=normalize(alias),
                            source="seed",
                        )
                    )

            contracts_by_customer[code].append(contract)

    return contracts_by_customer


def build_slips(session, contracts_by_customer, rng: random.Random) -> None:
    plan: list[str] = []
    for kind, count in SLIP_MIX.items():
        plan.extend([kind] * count)
    rng.shuffle(plan)

    all_codes = [c for c, _, _ in CUSTOMERS]

    for index, kind in enumerate(plan, start=1):
        customer_code = rng.choice(all_codes)
        service_date = date(2025, 1, 1) + timedelta(days=rng.randint(0, 364))

        if kind == "unknown_customer":
            slip_customer = rng.choice(["ZZZ", "SBC-2", "TEST"])
        else:
            slip_customer = customer_code

        if kind == "no_active_contract":
            service_date = date(2024, 1, 1) + timedelta(days=rng.randint(0, 364))

        slip = ServiceSlip(
            slip_no=f"SS-2025-{index:04d}",
            customer_code=slip_customer,
            service_date=service_date,
            technician=rng.choice(TECHNICIANS),
            work_type=rng.choice(list(WorkType)),
            site_note=None,
        )
        session.add(slip)
        session.flush()

        if kind == "empty":
            continue

        contract = _contract_for(contracts_by_customer[customer_code], service_date)
        if contract is None:
            contract = contracts_by_customer[customer_code][0]
        items = list(contract.items)

        line_count = rng.randint(1, 4)
        lines: list[SlipLine] = []

        for line_no in range(1, line_count + 1):
            item = rng.choice(items)
            qty = _quantity(item.unit, rng)
            unit = item.unit
            if rng.random() < 0.03:
                unit = rng.choice([u for u in QTY_RANGE if u != item.unit])
            lines.append(
                SlipLine(
                    slip_id=slip.id,
                    line_no=line_no,
                    raw_description=_phrase_for(item, qty, rng),
                    quantity=qty,
                    unit=unit,
                    truth_item_code=item.code,
                )
            )

        if kind == "off_contract":
            victim = rng.randrange(len(lines))
            lines[victim].raw_description = rng.choice(OFF_CONTRACT_PHRASES)
            lines[victim].truth_item_code = None

        elif kind == "category_trap":
            victim = rng.randrange(len(lines))
            lines[victim].raw_description = rng.choice(CATEGORY_TRAP_PHRASES)
            lines[victim].unit = "ea"
            lines[victim].quantity = float(rng.randint(1, 3))
            # No ground truth on purpose. Any figure the engine puts on this
            # line without asking is a silent mispricing, whichever side it
            # picks, and `scripts/evaluate.py` scores it as one.
            lines[victim].truth_item_code = None

        elif kind == "cross_specialty":
            others = [c for c in CUSTOMER_ONLY_ITEMS if c != customer_code]
            foreign = rng.choice(CUSTOMER_ONLY_ITEMS[rng.choice(others)])
            victim = rng.randrange(len(lines))
            lines[victim].raw_description = foreign[1]
            lines[victim].unit = foreign[3]
            lines[victim].truth_item_code = None

        elif kind == "over_limit":
            limited = [i for i in items if i.max_quantity_per_slip]
            item = rng.choice(limited)
            lines.append(
                SlipLine(
                    slip_id=slip.id,
                    line_no=len(lines) + 1,
                    raw_description=item.description,
                    quantity=float(item.max_quantity_per_slip) + rng.randint(1, 5),
                    unit=item.unit,
                    truth_item_code=item.code,
                )
            )

        session.add_all(lines)


def _contract_for(contracts: list[Contract], on: date) -> Contract | None:
    for contract in contracts:
        if contract.period_start <= on <= contract.period_end:
            return contract
    return None


def seed(reset: bool = True, random_seed: int = 20260816) -> None:
    rng = random.Random(random_seed)
    init_db(drop=reset)
    with session_scope() as session:
        contracts = build_contracts(session, rng)
        build_slips(session, contracts, rng)


if __name__ == "__main__":
    seed()
    print("Synthetic dataset created.")
