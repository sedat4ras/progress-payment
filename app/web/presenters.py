"""Reads the domain and answers the questions the screens ask.

Everything here is a query and an arrangement. No decision is taken in this
module: pricing, matching and state transitions all live in `app.pipeline` and
`app.engine`, and this layer is only allowed to describe what they produced.

The metric definitions are the load-bearing part. Automation rate and silent
errors are the two figures the product is sold on, and they have to mean here
exactly what they mean in `scripts/evaluate.py`, or the dashboard is marketing
rather than measurement.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Customer,
    DraftStatus,
    FlagCode,
    MatchMethod,
    PaymentDraft,
    PaymentLine,
)

BOARD_COLUMNS = [
    (DraftStatus.NEEDS_REVIEW, "Needs review"),
    (DraftStatus.READY, "Ready"),
    (DraftStatus.MANUAL, "Manual"),
    (DraftStatus.APPROVED, "Approved"),
]

# A column is a work queue, not a list of everything. It shows the top of the
# queue under whichever sort is active and reports the true count in its header,
# so the number a reviewer plans against is never the number of cards drawn.
# Approved is shorter still: it is history, and the archive screen owns it.
CARDS_PER_COLUMN = 12
APPROVED_ON_BOARD = 6

IN_FLIGHT = (DraftStatus.NEEDS_REVIEW, DraftStatus.READY, DraftStatus.MANUAL)

FLAG_LABELS = {
    FlagCode.NO_CUSTOMER: "Unknown customer",
    FlagCode.NO_ACTIVE_CONTRACT: "No contract in force",
    FlagCode.EMPTY_SLIP: "Empty slip",
    FlagCode.UNMATCHED_LINE: "Not in the price list",
    FlagCode.LOW_CONFIDENCE: "Below confidence threshold",
    FlagCode.CATEGORY_AMBIGUOUS: "Part or labour unclear",
    FlagCode.QUANTITY_LIMIT_EXCEEDED: "Over the contract ceiling",
    FlagCode.NON_POSITIVE_QUANTITY: "Quantity not positive",
    FlagCode.UNIT_MISMATCH: "Unit does not match",
}

METHOD_LABELS = {
    MatchMethod.EXACT: "exact",
    MatchMethod.ALIAS: "alias",
    MatchMethod.FUZZY: "fuzzy",
    MatchMethod.LLM: "model",
    MatchMethod.NONE: "reviewer",
}


@dataclass
class Card:
    draft: PaymentDraft
    slip_no: str
    customer: str
    line_count: int
    unresolved: int
    service_date: date
    confirmed: Decimal
    pending: Decimal
    contract_code: str | None
    technician: str

    @property
    def headline_value(self) -> Decimal:
        return self.confirmed if self.confirmed else self.pending


@dataclass
class Column:
    status: DraftStatus
    title: str
    count: int
    cards: list[Card]
    truncated: bool = False


@dataclass
class Metrics:
    """The four slots of the metric strip, in `docs/ui-spec.md` §3 order."""

    exceptions: list[tuple[str, str, int]] = field(default_factory=list)  # code, label, count
    automation_rate: float = 0.0
    priced_lines: int = 0
    silent_errors: int = 0
    cross_category_errors: int = 0
    value_pending: Decimal = Decimal("0")

    @property
    def exception_peak(self) -> int:
        return max((count for *_, count in self.exceptions), default=0)


@dataclass
class Sidebar:
    in_flight: int
    invalid: int
    approved: int
    customers: list[tuple[str, str, int]]  # code, name, backlog
    degraded_backend: str | None = None


@dataclass
class LineView:
    """One payment line, already classified into how it should be presented."""

    line: PaymentLine
    kind: str  # flagged | corrected | manual | priced
    flag_label: str | None
    flag_message: str | None


# ---------------------------------------------------------------------------
# Sidebar and board
# ---------------------------------------------------------------------------


def sidebar(session: Session, backend_name: str, backend_ready: bool) -> Sidebar:
    counts = Counter(session.scalars(select(PaymentDraft.status)).all())

    backlog: Counter[str] = Counter()
    for draft in _drafts(session, IN_FLIGHT):
        backlog[_customer_code(draft)] += 1

    customers = [
        (c.code, c.name, backlog.get(c.code, 0))
        for c in session.scalars(select(Customer).order_by(Customer.name)).all()
    ]

    return Sidebar(
        in_flight=sum(counts.get(s, 0) for s in IN_FLIGHT),
        invalid=counts.get(DraftStatus.INVALID, 0),
        approved=counts.get(DraftStatus.APPROVED, 0),
        customers=customers,
        degraded_backend=None if backend_ready else backend_name,
    )


def board(
    session: Session,
    customer: str | None = None,
    flag: FlagCode | None = None,
    sort: str = "age",
) -> list[Column]:
    columns = []
    for status, title in BOARD_COLUMNS:
        drafts = [
            d
            for d in _drafts(session, (status,))
            if _matches(d, customer, flag)
        ]
        drafts.sort(key=_sort_key(sort), reverse=(sort == "value"))

        cap = APPROVED_ON_BOARD if status is DraftStatus.APPROVED else CARDS_PER_COLUMN
        shown = drafts[:cap]
        truncated = len(drafts) > cap

        columns.append(
            Column(
                status=status,
                title=title,
                count=len(drafts),
                cards=[card(d) for d in shown],
                truncated=truncated,
            )
        )
    return columns


def card(draft: PaymentDraft) -> Card:
    return Card(
        draft=draft,
        slip_no=draft.slip.slip_no,
        customer=_customer_name(draft),
        line_count=len(draft.lines),
        unresolved=sum(1 for line in draft.lines if line.needs_review),
        service_date=draft.slip.service_date,
        confirmed=Decimal(draft.total_gross),
        pending=Decimal(draft.pending_net),
        contract_code=draft.contract.code if draft.contract else None,
        technician=draft.slip.technician,
    )


def invalid_slips(session: Session) -> list[tuple[PaymentDraft, list[str]]]:
    """Master-data failures, each with the plain-language reasons it failed."""
    return [
        (draft, [flag.message for flag in draft.flags])
        for draft in _drafts(session, (DraftStatus.INVALID,))
    ]


def approved_slips(session: Session, query: str | None = None) -> list[Card]:
    cards = [card(d) for d in _drafts(session, (DraftStatus.APPROVED,))]
    if query:
        needle = query.strip().lower()
        cards = [
            c
            for c in cards
            if needle in c.slip_no.lower() or needle in c.customer.lower()
        ]
    cards.sort(key=lambda c: c.draft.resolved_at or c.draft.created_at, reverse=True)
    return cards


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def metrics(session: Session) -> Metrics:
    """The four numbers above the board.

    Counted over work that has entered the pipeline. Invalid slips are excluded
    throughout: nothing was ever matched or priced on them, so including them
    would dilute the automation rate with lines the engine never saw.
    """
    drafts = _drafts(session, IN_FLIGHT + (DraftStatus.APPROVED,))

    total_lines = 0
    auto_priced = 0
    silent = 0
    cross = 0
    exceptions: Counter[FlagCode] = Counter()
    pending_value = Decimal("0")

    for draft in drafts:
        for line in draft.lines:
            total_lines += 1
            auto_priced += line.auto_priced
            silent += line.is_silent_error
            cross += line.is_cross_category_error

        if draft.status is not DraftStatus.APPROVED:
            pending_value += Decimal(draft.total_gross) + Decimal(draft.pending_net)
            for flag in draft.flags:
                exceptions[flag.code] += 1

    return Metrics(
        exceptions=[
            (code.value, FLAG_LABELS[code], count)
            for code, count in exceptions.most_common()
        ],
        automation_rate=(auto_priced / total_lines) if total_lines else 0.0,
        priced_lines=auto_priced,
        silent_errors=silent,
        cross_category_errors=cross,
        value_pending=pending_value,
    )


# ---------------------------------------------------------------------------
# Slip detail
# ---------------------------------------------------------------------------


def line_views(draft: PaymentDraft) -> list[LineView]:
    """Sort each line into one of the three presentations in `ui-spec.md` §5.

    A corrected line outranks a priced one because the correction is the more
    important fact about it, and it is the only presentation that shows two
    readings at once.
    """
    by_line = {
        flag.payment_line_id: flag for flag in draft.flags if flag.payment_line_id
    }

    views = []
    for line in sorted(draft.lines, key=lambda pl: pl.slip_line.line_no):
        flag = by_line.get(line.id)
        if flag is not None:
            kind = "flagged"
        elif line.is_manual_price:
            kind = "manual"
        elif line.corrected_at is not None:
            kind = "corrected"
        else:
            kind = "priced"

        views.append(
            LineView(
                line=line,
                kind=kind,
                flag_label=FLAG_LABELS[flag.code] if flag else None,
                flag_message=flag.message if flag else None,
            )
        )
    return views


def blocking_reason(draft: PaymentDraft) -> str | None:
    """Why the approve control is disabled, in words a reviewer can act on.

    Never silently inert: if the button cannot be pressed, the page says which
    lines are in the way.
    """
    if draft.status is DraftStatus.APPROVED:
        return "This progress payment has already been approved."
    if draft.status is DraftStatus.INVALID:
        return "This slip never entered the pipeline. Fix the master data and reprocess it."

    unresolved = [
        line.slip_line.line_no for line in draft.lines if line.needs_review
    ]
    if unresolved:
        listed = ", ".join(str(n) for n in unresolved)
        return f"Line {listed} still needs a decision." if len(unresolved) == 1 else (
            f"Lines {listed} still need a decision."
        )
    if draft.flags:
        return "There is an unresolved flag on this slip."
    return None


def catalogue(draft: PaymentDraft) -> list:
    """The contract items a reviewer may choose from, materials first."""
    if draft.contract is None:
        return []
    return sorted(
        draft.contract.items, key=lambda i: (i.category.value, i.description)
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _drafts(session: Session, statuses: tuple[DraftStatus, ...]) -> list[PaymentDraft]:
    return list(
        session.scalars(
            select(PaymentDraft)
            .where(PaymentDraft.status.in_(statuses))
            .order_by(PaymentDraft.id)
        ).all()
    )


def _customer_code(draft: PaymentDraft) -> str:
    return draft.contract.customer.code if draft.contract else draft.slip.customer_code


def _customer_name(draft: PaymentDraft) -> str:
    if draft.contract is not None:
        return draft.contract.customer.name
    return draft.slip.customer_code


def _matches(draft: PaymentDraft, customer: str | None, flag: FlagCode | None) -> bool:
    if customer and _customer_code(draft) != customer:
        return False
    if flag and not any(f.code is flag for f in draft.flags):
        return False
    return True


def _sort_key(sort: str):
    if sort == "value":
        return lambda d: Decimal(d.total_gross) + Decimal(d.pending_net)
    return lambda d: (d.slip.service_date, d.id)


def customer_name(session: Session, code: str) -> str | None:
    customer = session.scalar(select(Customer).where(Customer.code == code))
    return customer.name if customer else None
