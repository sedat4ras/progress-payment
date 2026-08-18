from datetime import date
from decimal import Decimal

import pytest

from app.engine.backends.rule_only import RuleOnlyBackend
from app.models import DraftStatus, FlagCode, MatchMethod, TakeoverReason
from app.pipeline import (
    SlipProcessor,
    finalize_draft,
    resolve_line,
    set_manual_price,
    take_over,
)


@pytest.fixture
def processor(session):
    return SlipProcessor(session, backend=RuleOnlyBackend())


def _flags(draft):
    return {flag.code for flag in draft.flags}


# --------------------------------------------------------------------------
# Intake and validation
# --------------------------------------------------------------------------


def test_clean_slip_is_priced_from_the_contract(contract, make_slip, processor):
    slip = make_slip([("Split System Air Filter", 3, "ea")])
    draft = processor.process(slip)

    assert draft.status is DraftStatus.READY
    assert Decimal(draft.total_net) == Decimal("204.00")
    assert Decimal(draft.total_gst) == Decimal("20.40")
    assert Decimal(draft.total_gross) == Decimal("224.40")


def test_unknown_customer_makes_the_slip_invalid(contract, make_slip, processor):
    slip = make_slip([("Split System Air Filter", 1, "ea")], customer_code="ZZZ")
    draft = processor.process(slip)

    assert draft.status is DraftStatus.INVALID
    assert FlagCode.NO_CUSTOMER in _flags(draft)
    assert draft.lines == []


def test_date_outside_every_contract_period_makes_the_slip_invalid(
    contract, make_slip, processor
):
    slip = make_slip(
        [("Split System Air Filter", 1, "ea")], service_date=date(2024, 3, 10)
    )
    draft = processor.process(slip)

    assert draft.status is DraftStatus.INVALID
    assert FlagCode.NO_ACTIVE_CONTRACT in _flags(draft)


def test_empty_slip_is_invalid(contract, make_slip, processor):
    draft = processor.process(make_slip([]))

    assert draft.status is DraftStatus.INVALID
    assert FlagCode.EMPTY_SLIP in _flags(draft)


# --------------------------------------------------------------------------
# The review queue
# --------------------------------------------------------------------------


def test_line_absent_from_contract_holds_up_the_payment(contract, make_slip, processor):
    slip = make_slip(
        [
            ("Split System Air Filter", 3, "ea"),
            ("Roof membrane waterproofing renewed", 1, "ea"),
        ]
    )
    draft = processor.process(slip)

    assert draft.status is DraftStatus.NEEDS_REVIEW
    assert FlagCode.UNMATCHED_LINE in _flags(draft)
    # The line that was understood still carries its price; the slip simply
    # cannot be approved until the other one is dealt with.
    assert Decimal(draft.total_net) == Decimal("204.00")
    assert draft.lines[1].line_net is None


def test_quantity_above_contract_ceiling_goes_to_review(contract, make_slip, processor):
    slip = make_slip([("Breakdown Callout - Business Hours", 20, "hr")])
    draft = processor.process(slip)

    assert draft.status is DraftStatus.NEEDS_REVIEW
    assert FlagCode.QUANTITY_LIMIT_EXCEEDED in _flags(draft)
    assert draft.lines[0].line_net is None


def test_unit_mismatch_goes_to_review(contract, make_slip, processor):
    slip = make_slip([("Breakdown Callout - Business Hours", 2, "ea")])
    draft = processor.process(slip)

    assert draft.status is DraftStatus.NEEDS_REVIEW
    assert FlagCode.UNIT_MISMATCH in _flags(draft)


def test_low_confidence_line_is_never_priced(contract, make_slip, processor):
    slip = make_slip([("Industrial Fan Balancing", 1, "ea")])
    draft = processor.process(slip)

    assert draft.status is DraftStatus.NEEDS_REVIEW
    assert draft.lines[0].unit_price is None
    assert Decimal(draft.total_net) == Decimal("0")


# --------------------------------------------------------------------------
# Material and labour
# --------------------------------------------------------------------------


def test_a_labour_line_is_priced_when_the_unit_says_labour(
    contract, make_slip, processor
):
    slip = make_slip([("coper pipe instalation", 3, "hr")])
    draft = processor.process(slip)

    assert draft.status is DraftStatus.READY
    assert draft.lines[0].contract_item.code == "LAB-005"
    assert Decimal(draft.total_net) == Decimal("495.00")


def test_the_same_words_in_a_material_unit_never_reach_the_labour_item(
    contract, make_slip, processor
):
    """Identical wording, one character of unit apart.

    Metres are only ever a material in this price list, so the labour item is
    not a weak answer here - it is removed before anything is scored, and what
    is left is not close enough to offer at all.
    """
    slip = make_slip([("coper pipe instalation", 3, "m")])
    draft = processor.process(slip)

    assert draft.status is DraftStatus.NEEDS_REVIEW
    assert FlagCode.UNMATCHED_LINE in _flags(draft)
    assert draft.lines[0].proposed_item is None
    assert draft.lines[0].line_net is None


def test_an_unresolvable_material_labour_collision_is_never_priced(
    contract, make_slip, processor
):
    """The guard that costs the most to get wrong.

    'ea' prices both parts and labour in this contract, so nothing in the line
    says whether the pipe was supplied or fitted. Guessing would bill $34 as
    $165, or the reverse, with nobody the wiser.
    """
    slip = make_slip([("copper pipe", 4, "ea")])
    draft = processor.process(slip)

    assert draft.status is DraftStatus.NEEDS_REVIEW
    assert FlagCode.CATEGORY_AMBIGUOUS in _flags(draft)
    assert draft.lines[0].line_net is None
    assert draft.lines[0].auto_priced is False


def test_a_category_collision_outranks_a_high_score(contract, make_slip, processor):
    """Confidence does not buy a way past the category guard - the score is
    exactly the thing that cannot be trusted when two readings are this close."""
    slip = make_slip([("copper pipe", 4, "ea")])
    draft = processor.process(slip)
    line = draft.lines[0]

    flag = next(f for f in draft.flags if f.payment_line_id == line.id)
    assert flag.code is FlagCode.CATEGORY_AMBIGUOUS
    assert line.proposed_item is not None


# --------------------------------------------------------------------------
# Review decisions
# --------------------------------------------------------------------------


def test_draft_cannot_be_approved_while_the_queue_is_unresolved(
    session, contract, make_slip, processor
):
    slip = make_slip([("Roof membrane waterproofing renewed", 1, "ea")])
    draft = processor.process(slip)

    with pytest.raises(ValueError):
        finalize_draft(session, draft, resolved_by="expert")


def test_expert_correction_prices_the_line_and_totals_the_draft(
    session, contract, make_slip, processor
):
    slip = make_slip([("splt sys ar fltr", 2, "ea")])
    draft = processor.process(slip)
    assert draft.status is DraftStatus.NEEDS_REVIEW

    resolve_line(session, draft.lines[0], "FLT-001")
    finalize_draft(session, draft, resolved_by="expert")

    assert draft.status is DraftStatus.APPROVED
    assert Decimal(draft.total_net) == Decimal("136.00")
    assert draft.resolved_by == "expert"


def test_answering_the_last_question_moves_the_slip_out_of_the_queue(
    session, contract, make_slip, processor
):
    slip = make_slip([("splt sys ar fltr", 2, "ea"), ("Fan Motor 1/4 HP", 1, "ea")])
    draft = processor.process(slip)
    assert draft.status is DraftStatus.NEEDS_REVIEW

    resolve_line(session, draft.lines[0], "FLT-001")

    assert draft.status is DraftStatus.READY
    assert not draft.flags


def test_a_slip_stays_in_the_queue_while_another_line_is_open(
    session, contract, make_slip, processor
):
    slip = make_slip(
        [("splt sys ar fltr", 2, "ea"), ("Roof membrane waterproofing renewed", 1, "ea")]
    )
    draft = processor.process(slip)

    resolve_line(session, draft.lines[0], "FLT-001")

    assert draft.status is DraftStatus.NEEDS_REVIEW


def test_resolving_a_line_does_not_hand_back_a_slip_a_reviewer_took_over(
    session, contract, make_slip, processor
):
    slip = make_slip([("Fan Motor 1/4 HP", 1, "ea")])
    draft = processor.process(slip)
    take_over(session, draft, TakeoverReason.MACHINE_ERROR, reviewer="expert")

    resolve_line(session, draft.lines[0], "FLT-001")

    assert draft.status is DraftStatus.MANUAL


def test_a_correction_does_not_become_a_rule(session, contract, make_slip, processor):
    """One judgement, one line.

    Identical field wording can legitimately mean different catalogue items on
    different slips, so a decision made here must not silently price the next
    slip that happens to read the same way.
    """
    first = make_slip([("splt sys ar fltr", 1, "ea")])
    draft = processor.process(first)
    resolve_line(session, draft.lines[0], "FLT-001")
    session.flush()
    session.refresh(contract)

    second_processor = SlipProcessor(session, backend=RuleOnlyBackend())
    second = make_slip([("splt sys ar fltr", 1, "ea")])
    second_draft = second_processor.process(second)

    assert second_draft.status is DraftStatus.NEEDS_REVIEW
    assert second_draft.lines[0].match_method is not MatchMethod.ALIAS
    assert Decimal(second_draft.total_net) == Decimal("0")


def test_line_marked_unbillable_is_excluded_from_the_total(
    session, contract, make_slip, processor
):
    slip = make_slip(
        [
            ("Split System Air Filter", 1, "ea"),
            ("Roof membrane waterproofing renewed", 1, "ea"),
        ]
    )
    draft = processor.process(slip)

    resolve_line(session, draft.lines[1], None)
    finalize_draft(session, draft, resolved_by="expert")

    assert Decimal(draft.total_net) == Decimal("68.00")
    assert draft.lines[1].line_net is None


def test_resolving_a_line_clears_only_its_own_flag(
    session, contract, make_slip, processor
):
    slip = make_slip(
        [
            ("Roof membrane waterproofing renewed", 1, "ea"),
            ("Breakdown Callout - Business Hours", 20, "hr"),
        ]
    )
    draft = processor.process(slip)
    assert len(draft.flags) == 2

    resolve_line(session, draft.lines[0], None)

    assert len(draft.flags) == 1
    assert draft.flags[0].payment_line_id == draft.lines[1].id


# --------------------------------------------------------------------------
# Confirmed money versus money still at stake
# --------------------------------------------------------------------------


def test_a_slip_in_review_still_reports_what_is_at_stake(
    contract, make_slip, processor
):
    """A review queue that reports zero tells a reviewer nothing about whether
    a slip is worth opening."""
    slip = make_slip([("Breakdown Callout - Business Hours", 20, "hr")])
    draft = processor.process(slip)

    assert Decimal(draft.total_net) == Decimal("0")
    assert Decimal(draft.pending_net) == Decimal("2840.00")


def test_a_line_with_no_counterpart_at_all_is_not_counted_as_pending(
    contract, make_slip, processor
):
    slip = make_slip([("Roof membrane waterproofing renewed", 1, "ea")])
    draft = processor.process(slip)

    assert Decimal(draft.pending_net) == Decimal("0")


def test_pending_falls_away_as_lines_are_resolved(
    session, contract, make_slip, processor
):
    slip = make_slip(
        [
            ("Split System Air Filter", 1, "ea"),
            ("Breakdown Callout - Business Hours", 20, "hr"),
        ]
    )
    draft = processor.process(slip)
    assert Decimal(draft.pending_net) == Decimal("2840.00")

    resolve_line(session, draft.lines[1], "LAB-001")

    assert Decimal(draft.pending_net) == Decimal("0")
    assert Decimal(draft.total_net) == Decimal("2908.00")


# --------------------------------------------------------------------------
# Take-over
# --------------------------------------------------------------------------


def test_take_over_moves_the_slip_out_of_the_automated_flow(
    session, contract, make_slip, processor
):
    slip = make_slip([("Split System Air Filter", 3, "ea")])
    draft = processor.process(slip)

    take_over(
        session,
        draft,
        TakeoverReason.MACHINE_ERROR,
        reviewer="expert",
        note="wrong filter type",
    )

    assert draft.status is DraftStatus.MANUAL
    assert draft.taken_over_by == "expert"
    assert draft.takeover_reason is TakeoverReason.MACHINE_ERROR
    assert draft.taken_over_at is not None


def test_a_slip_already_asking_for_help_cannot_be_taken_over(
    session, contract, make_slip, processor
):
    """NEEDS_REVIEW is the machine admitting it does not know, and working it
    there is ordinary review. Keeping the door to MANUAL narrow is what lets
    MANUAL mean one thing: the machine was confident and it was wrong."""
    slip = make_slip([("Roof membrane waterproofing renewed", 1, "ea")])
    draft = processor.process(slip)

    with pytest.raises(ValueError):
        take_over(session, draft, TakeoverReason.OTHER, reviewer="expert")


def test_an_approved_slip_cannot_be_taken_over(
    session, contract, make_slip, processor
):
    slip = make_slip([("Split System Air Filter", 1, "ea")])
    draft = processor.process(slip)
    finalize_draft(session, draft, resolved_by="expert")

    with pytest.raises(ValueError):
        take_over(session, draft, TakeoverReason.OTHER, reviewer="expert")


# --------------------------------------------------------------------------
# Manual pricing
# --------------------------------------------------------------------------


def test_manual_price_requires_a_taken_over_slip(
    session, contract, make_slip, processor
):
    slip = make_slip([("Split System Air Filter", 1, "ea")])
    draft = processor.process(slip)

    with pytest.raises(ValueError):
        set_manual_price(session, draft.lines[0], "Something else", "50.00")


def test_manual_price_is_applied_and_totalled(
    session, contract, make_slip, processor
):
    slip = make_slip([("Split System Air Filter", 2, "ea")])
    draft = processor.process(slip)
    take_over(session, draft, TakeoverReason.OUT_OF_CONTRACT, reviewer="expert")

    set_manual_price(
        session,
        draft.lines[0],
        "Filter, non-catalogue size",
        "91.50",
        reviewer="expert",
    )

    line = draft.lines[0]
    assert line.contract_item_id is None
    assert line.manual_description == "Filter, non-catalogue size"
    assert line.is_manual_price
    assert Decimal(draft.total_net) == Decimal("183.00")


def test_manual_price_cannot_be_negative(session, contract, make_slip, processor):
    slip = make_slip([("Split System Air Filter", 1, "ea")])
    draft = processor.process(slip)
    take_over(session, draft, TakeoverReason.OTHER, reviewer="expert")

    with pytest.raises(ValueError):
        set_manual_price(session, draft.lines[0], "Nonsense", "-1.00")


def test_a_manually_priced_slip_can_be_approved(
    session, contract, make_slip, processor
):
    slip = make_slip([("Split System Air Filter", 1, "ea")])
    draft = processor.process(slip)
    take_over(session, draft, TakeoverReason.OUT_OF_CONTRACT, reviewer="expert")
    set_manual_price(session, draft.lines[0], "Off-catalogue part", "12.00")

    finalize_draft(session, draft, resolved_by="expert")

    assert draft.status is DraftStatus.APPROVED
    assert Decimal(draft.total_net) == Decimal("12.00")


# --------------------------------------------------------------------------
# The silent error rate
# --------------------------------------------------------------------------


def test_the_machines_answer_is_kept_even_after_a_correction(
    session, contract, make_slip, processor
):
    slip = make_slip([("Split System Air Filter", 1, "ea")])
    draft = processor.process(slip)
    line = draft.lines[0]
    proposed = line.proposed_item_id

    take_over(session, draft, TakeoverReason.MACHINE_ERROR, reviewer="expert")
    resolve_line(session, line, "MOT-001", reviewer="expert")

    assert line.proposed_item_id == proposed
    assert line.proposed_item.code == "FLT-001"
    assert line.contract_item.code == "MOT-001"
    assert line.proposed_method is MatchMethod.EXACT


def test_correcting_a_confidently_priced_line_records_a_silent_error(
    session, contract, make_slip, processor
):
    slip = make_slip([("Split System Air Filter", 1, "ea")])
    draft = processor.process(slip)
    line = draft.lines[0]
    assert line.auto_priced

    take_over(session, draft, TakeoverReason.MACHINE_ERROR, reviewer="expert")
    resolve_line(session, line, "MOT-001", reviewer="expert")

    assert line.is_silent_error
    assert line.corrected_by == "expert"


def test_resolving_a_flagged_line_is_not_a_silent_error(
    session, contract, make_slip, processor
):
    """The machine asked for help and got it. That is the system working."""
    slip = make_slip([("splt sys ar fltr", 1, "ea")])
    draft = processor.process(slip)
    line = draft.lines[0]
    assert line.auto_priced is False

    resolve_line(session, line, "FLT-001", reviewer="expert")

    assert line.is_silent_error is False
    assert line.corrected_at is None


def test_a_material_billed_as_labour_is_reported_as_its_own_kind_of_error(
    session, contract, make_slip, processor
):
    slip = make_slip([("Copper Pipe 1/4 inch", 5, "m")])
    draft = processor.process(slip)
    line = draft.lines[0]

    take_over(session, draft, TakeoverReason.MACHINE_ERROR, reviewer="expert")
    resolve_line(session, line, "LAB-005", reviewer="expert")

    assert line.is_silent_error
    assert line.is_cross_category_error


def test_a_manual_price_is_not_counted_as_a_cross_category_error(
    session, contract, make_slip, processor
):
    slip = make_slip([("Split System Air Filter", 1, "ea")])
    draft = processor.process(slip)
    take_over(session, draft, TakeoverReason.OUT_OF_CONTRACT, reviewer="expert")
    set_manual_price(session, draft.lines[0], "Off-catalogue part", "12.00")

    assert draft.lines[0].is_cross_category_error is False


# --------------------------------------------------------------------------
# Reprocessing
# --------------------------------------------------------------------------


def test_reprocessing_a_slip_replaces_the_previous_draft(
    session, contract, make_slip, processor
):
    from sqlalchemy import func, select

    from app.models import PaymentDraft, PaymentLine

    slip = make_slip([("Split System Air Filter", 1, "ea")])
    processor.process(slip)
    second = processor.process(slip)

    assert session.scalar(select(func.count()).select_from(PaymentDraft)) == 1
    assert session.scalar(select(func.count()).select_from(PaymentLine)) == 1
    assert len(second.lines) == 1
