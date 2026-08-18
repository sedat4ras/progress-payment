"""End-to-end: service slip in, progress payment draft or review queue out."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import AUTO_APPROVE_THRESHOLD
from app.engine.backends import MatcherBackend, get_backend
from app.engine.matching import MatchIndex, match_line
from app.engine.pricing import check_quantity, check_unit, gst_of, line_net, money
from app.engine.validation import validate_slip
from app.models import (
    ContractItem,
    DraftStatus,
    FlagCode,
    MatchMethod,
    PaymentDraft,
    PaymentLine,
    ReviewFlag,
    ServiceSlip,
    TakeoverReason,
    utcnow,
)


class SlipProcessor:
    def __init__(
        self,
        session: Session,
        backend: MatcherBackend | None = None,
        threshold: float = AUTO_APPROVE_THRESHOLD,
    ):
        self.session = session
        self.backend = backend or get_backend()
        self.threshold = threshold
        self._indexes: dict[int, MatchIndex] = {}

    def index_for(self, contract) -> MatchIndex:
        if contract.id not in self._indexes:
            self._indexes[contract.id] = MatchIndex.build(contract)
        return self._indexes[contract.id]

    def process(self, slip: ServiceSlip) -> PaymentDraft:
        self._clear_previous(slip)

        draft = PaymentDraft(slip_id=slip.id, status=DraftStatus.READY)
        self.session.add(draft)
        self.session.flush()

        validation = validate_slip(self.session, slip)
        if not validation.ok:
            draft.status = DraftStatus.INVALID
            draft.contract_id = validation.contract.id if validation.contract else None
            for code, message in validation.failures:
                self.session.add(ReviewFlag(draft_id=draft.id, code=code, message=message))
            self.session.flush()
            return draft

        contract = validation.contract
        draft.contract_id = contract.id
        index = self.index_for(contract)
        by_code = {item.code: item for item in contract.items}

        needs_review = False

        for slip_line in sorted(slip.lines, key=lambda l: l.line_no):
            proposal = match_line(
                index, slip_line.raw_description, slip_line.unit, self.backend, self.threshold
            )
            item = by_code.get(proposal.item_code) if proposal.item_code else None

            payment_line = PaymentLine(
                draft_id=draft.id,
                slip_line_id=slip_line.id,
                contract_item_id=item.id if item else None,
                match_method=proposal.method,
                confidence=proposal.confidence,
                rationale=proposal.rationale,
                quantity=slip_line.quantity,
                # Frozen copy of the engine's answer. Nothing below this point,
                # and no human afterwards, may write to these three.
                proposed_item_id=item.id if item else None,
                proposed_method=proposal.method,
                proposed_confidence=proposal.confidence,
            )
            self.session.add(payment_line)
            self.session.flush()

            blocker = self._blocker_for(item, proposal, slip_line)
            if blocker is not None:
                code, message = blocker
                payment_line.needs_review = True
                needs_review = True
                self.session.add(
                    ReviewFlag(
                        draft_id=draft.id,
                        payment_line_id=payment_line.id,
                        code=code,
                        message=message,
                    )
                )
                continue

            payment_line.unit_price = item.unit_price
            payment_line.line_net = line_net(item.unit_price, slip_line.quantity)
            payment_line.auto_priced = True

        draft.status = DraftStatus.NEEDS_REVIEW if needs_review else DraftStatus.READY
        recompute_totals(draft)

        self.session.flush()
        return draft

    def _blocker_for(self, item: ContractItem | None, proposal, slip_line):
        if item is None:
            return (
                FlagCode.UNMATCHED_LINE,
                f"'{slip_line.raw_description}' has no counterpart in the contract "
                "price list. No price was applied.",
            )

        # Checked before confidence on purpose. A material/labour collision is
        # not a weak match to be waved through by a high score - the score is
        # exactly what cannot be trusted here.
        if proposal.conflict_code is not None:
            return (FlagCode.CATEGORY_AMBIGUOUS, proposal.rationale)

        if proposal.confidence < self.threshold:
            return (
                FlagCode.LOW_CONFIDENCE,
                f"'{slip_line.raw_description}' was proposed as {item.code} at "
                f"{proposal.confidence * 100:.0f}% confidence, below the "
                f"{self.threshold * 100:.0f}% threshold. No price was applied.",
            )

        return check_unit(item, slip_line.unit) or check_quantity(item, slip_line.quantity)

    def _clear_previous(self, slip: ServiceSlip) -> None:
        existing = self.session.scalar(
            select(PaymentDraft).where(PaymentDraft.slip_id == slip.id)
        )
        if existing is not None:
            self.session.delete(existing)
            self.session.flush()


def recompute_totals(draft: PaymentDraft) -> None:
    """Confirmed money, and separately what is still at stake.

    A slip in review used to report a total of zero, which told a reviewer
    nothing about whether it was worth opening. Confirmed is what carries a
    price today; pending is an indication drawn from the proposals behind the
    unresolved lines, and is never billed.
    """
    confirmed = sum(
        (Decimal(line.line_net) for line in draft.lines if line.line_net is not None),
        Decimal("0"),
    )

    pending = Decimal("0")
    for line in draft.lines:
        if not line.needs_review or line.contract_item is None:
            continue
        pending += line_net(line.contract_item.unit_price, line.quantity)

    draft.total_net = money(confirmed)
    draft.total_gst = gst_of(confirmed)
    draft.total_gross = money(Decimal(draft.total_net) + Decimal(draft.total_gst))
    draft.pending_net = money(pending)


def resolve_line(
    session: Session,
    payment_line: PaymentLine,
    item_code: str | None,
    reviewer: str | None = None,
) -> None:
    """Apply a reviewer's decision to one line.

    Works on any line, not only a flagged one. Correcting a line the machine
    priced confidently is the whole point of UC-8, and it is what makes the
    silent error rate measurable.

    Passing `item_code=None` means "this line is not billable" - it stays
    unpriced and is simply excluded from the total.

    The decision applies to this line and nothing else. It deliberately does
    not become a rule: identical field wording can legitimately mean different
    catalogue items on different slips, so generalising one judgement would
    manufacture the silent mispricings this system exists to prevent.
    """
    draft = payment_line.draft
    contract = draft.contract

    _record_intervention(payment_line, reviewer)

    for flag in list(draft.flags):
        if flag.payment_line_id == payment_line.id:
            draft.flags.remove(flag)

    payment_line.manual_description = None

    if item_code is None:
        payment_line.contract_item_id = None
        payment_line.unit_price = None
        payment_line.line_net = None
        payment_line.needs_review = False
        payment_line.match_method = MatchMethod.NONE
        payment_line.confidence = 1.0
        payment_line.rationale = "Reviewer decision: not billable."
        recompute_totals(draft)
        _settle_status(draft)
        session.flush()
        return

    item = session.scalar(
        select(ContractItem).where(
            ContractItem.contract_id == contract.id,
            ContractItem.code == item_code,
        )
    )
    if item is None:
        raise ValueError(f"{item_code} is not part of this contract.")

    payment_line.contract_item_id = item.id
    payment_line.unit_price = item.unit_price
    payment_line.line_net = line_net(item.unit_price, payment_line.quantity)
    payment_line.needs_review = False
    payment_line.match_method = MatchMethod.NONE
    payment_line.confidence = 1.0
    payment_line.rationale = "Chosen by a reviewer."

    recompute_totals(draft)
    _settle_status(draft)
    session.flush()


def set_manual_price(
    session: Session,
    payment_line: PaymentLine,
    description: str,
    unit_price: Decimal | float | str,
    reviewer: str | None = None,
) -> None:
    """Price a line the catalogue does not cover.

    Only reachable on a slip a reviewer has taken over. This is the single path
    by which a price enters the system without coming from a ContractItem, and
    a human is the one typing it - the guarantee is that no *model* ever sets a
    price, and that still holds.
    """
    draft = payment_line.draft
    if draft.status is not DraftStatus.MANUAL:
        raise ValueError(
            "A manual price can only be entered on a slip that has been taken over."
        )

    price = Decimal(str(unit_price))
    if price < 0:
        raise ValueError("A manual price cannot be negative.")

    _record_intervention(payment_line, reviewer)

    for flag in list(draft.flags):
        if flag.payment_line_id == payment_line.id:
            draft.flags.remove(flag)

    payment_line.contract_item_id = None
    payment_line.manual_description = description
    payment_line.unit_price = money(price)
    payment_line.line_net = line_net(price, payment_line.quantity)
    payment_line.needs_review = False
    payment_line.match_method = MatchMethod.NONE
    payment_line.confidence = 1.0
    payment_line.rationale = "Priced manually by a reviewer; not in the contract."

    recompute_totals(draft)
    session.flush()


def take_over(
    session: Session,
    draft: PaymentDraft,
    reason: TakeoverReason,
    reviewer: str,
    note: str | None = None,
) -> PaymentDraft:
    """Move a slip out of the automated flow so a reviewer can finish it.

    Reachable from READY only. A slip in NEEDS_REVIEW is already the machine
    asking for help, and working it there is ordinary review. Restricting the
    entry point is what lets MANUAL mean one specific thing: the machine was
    confident and it was wrong.
    """
    if draft.status is not DraftStatus.READY:
        raise ValueError(
            f"Only a slip that is ready for sign-off can be taken over; "
            f"this one is {draft.status.value}."
        )

    draft.status = DraftStatus.MANUAL
    draft.taken_over_at = utcnow()
    draft.taken_over_by = reviewer
    draft.takeover_reason = reason
    draft.takeover_note = note
    session.flush()
    return draft


def finalize_draft(session: Session, draft: PaymentDraft, resolved_by: str) -> PaymentDraft:
    """Freeze the figures once nothing on the draft is waiting on a human."""
    if draft.status not in (DraftStatus.READY, DraftStatus.NEEDS_REVIEW, DraftStatus.MANUAL):
        raise ValueError(f"A {draft.status.value} slip cannot be approved.")

    if any(line.needs_review for line in draft.lines) or draft.flags:
        raise ValueError(
            "A progress payment cannot be approved while any line is unresolved."
        )

    recompute_totals(draft)
    draft.status = DraftStatus.APPROVED
    draft.resolved_at = utcnow()
    draft.resolved_by = resolved_by
    session.flush()
    return draft


def _settle_status(draft: PaymentDraft) -> None:
    """Move a slip out of the queue once the last question on it is answered.

    Only NEEDS_REVIEW moves. MANUAL is a reviewer's claim on the slip and is
    not given back by resolving a line, and APPROVED is frozen.
    """
    if draft.status is not DraftStatus.NEEDS_REVIEW:
        return
    if any(line.needs_review for line in draft.lines) or draft.flags:
        return
    draft.status = DraftStatus.READY


def _record_intervention(payment_line: PaymentLine, reviewer: str | None) -> None:
    """Stamp a line the machine had already priced.

    Only a line carrying `auto_priced` counts: the machine committed to it
    without asking, so a human changing it now is recording a silent error.
    Resolving a flagged line is not an error - it is the machine correctly
    saying it did not know.
    """
    if payment_line.auto_priced and payment_line.corrected_at is None:
        payment_line.corrected_at = utcnow()
        payment_line.corrected_by = reviewer


def process_all(session: Session, backend: MatcherBackend | None = None) -> list[PaymentDraft]:
    processor = SlipProcessor(session, backend=backend)
    slips = session.scalars(select(ServiceSlip).order_by(ServiceSlip.id)).all()
    return [processor.process(slip) for slip in slips]
