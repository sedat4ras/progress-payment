"""Domain model.

Money is Numeric(12, 2) everywhere and is only ever written by the pricing
engine, never by anything that talks to a language model.
"""

from __future__ import annotations

import enum
from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ItemCategory(str, enum.Enum):
    MATERIAL = "material"
    LABOUR = "labour"


class WorkType(str, enum.Enum):
    MAINTENANCE = "maintenance"
    SERVICE = "service"
    REPLACEMENT = "replacement"


class MatchMethod(str, enum.Enum):
    EXACT = "exact"
    ALIAS = "alias"
    FUZZY = "fuzzy"
    LLM = "llm"
    NONE = "none"


class DraftStatus(str, enum.Enum):
    INVALID = "invalid"            # failed the validation gate, no claim can exist yet
    NEEDS_REVIEW = "needs_review"  # the machine knows it does not know
    READY = "ready"                # every line priced automatically, awaiting sign-off
    MANUAL = "manual"              # a reviewer took it over; the machine was confidently wrong
    APPROVED = "approved"          # signed off, figures frozen


class TakeoverReason(str, enum.Enum):
    OUT_OF_CONTRACT = "out_of_contract"
    MACHINE_ERROR = "machine_error"
    OTHER = "other"


class FlagCode(str, enum.Enum):
    NO_CUSTOMER = "no_customer"
    NO_ACTIVE_CONTRACT = "no_active_contract"
    EMPTY_SLIP = "empty_slip"
    UNMATCHED_LINE = "unmatched_line"
    LOW_CONFIDENCE = "low_confidence"
    CATEGORY_AMBIGUOUS = "category_ambiguous"
    QUANTITY_LIMIT_EXCEEDED = "quantity_limit_exceeded"
    NON_POSITIVE_QUANTITY = "non_positive_quantity"
    UNIT_MISMATCH = "unit_mismatch"


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))

    contracts: Mapped[list["Contract"]] = relationship(back_populates="customer")


class Contract(Base):
    """A price list valid for one customer over one period."""

    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    code: Mapped[str] = mapped_column(String(64), unique=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)

    customer: Mapped[Customer] = relationship(back_populates="contracts")
    items: Mapped[list["ContractItem"]] = relationship(back_populates="contract")


class ContractItem(Base):
    __tablename__ = "contract_items"
    __table_args__ = (UniqueConstraint("contract_id", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id"))
    code: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(String(300))
    category: Mapped[ItemCategory] = mapped_column(Enum(ItemCategory))
    unit: Mapped[str] = mapped_column(String(16))          # adet, saat, mt, kg
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2))
    # Contractual ceiling per single slip; None means unlimited.
    max_quantity_per_slip: Mapped[float | None] = mapped_column(Float, nullable=True)

    contract: Mapped[Contract] = relationship(back_populates="items")
    aliases: Mapped[list["ItemAlias"]] = relationship(back_populates="item")


class ItemAlias(Base):
    """A phrasing already known to map to a contract item.

    Seeded from the catalogue as a synonym list. Corrections do not write rows
    here: the same field wording legitimately means different items on
    different sites, so a fix stays local to the line it was made on.
    """

    __tablename__ = "item_aliases"
    __table_args__ = (UniqueConstraint("contract_item_id", "normalized_text"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_item_id: Mapped[int] = mapped_column(ForeignKey("contract_items.id"))
    normalized_text: Mapped[str] = mapped_column(String(300), index=True)
    source: Mapped[str] = mapped_column(String(16))        # seed | expert
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    item: Mapped[ContractItem] = relationship(back_populates="aliases")


class ServiceSlip(Base):
    __tablename__ = "service_slips"

    id: Mapped[int] = mapped_column(primary_key=True)
    slip_no: Mapped[str] = mapped_column(String(32), unique=True)
    customer_code: Mapped[str] = mapped_column(String(32))   # as typed in the field
    service_date: Mapped[date] = mapped_column(Date)
    technician: Mapped[str] = mapped_column(String(120))
    work_type: Mapped[WorkType] = mapped_column(Enum(WorkType))
    site_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    lines: Mapped[list["SlipLine"]] = relationship(back_populates="slip")


class SlipLine(Base):
    __tablename__ = "slip_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    slip_id: Mapped[int] = mapped_column(ForeignKey("service_slips.id"))
    line_no: Mapped[int] = mapped_column(Integer)
    raw_description: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(16))
    # Only populated by the synthetic generator, used to score the engine.
    truth_item_code: Mapped[str | None] = mapped_column(String(32), nullable=True)

    slip: Mapped[ServiceSlip] = relationship(back_populates="lines")


class PaymentDraft(Base):
    __tablename__ = "payment_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    slip_id: Mapped[int] = mapped_column(ForeignKey("service_slips.id"), unique=True)
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("contracts.id"), nullable=True)
    status: Mapped[DraftStatus] = mapped_column(Enum(DraftStatus))

    # Confirmed money: lines that carry a price right now.
    total_net: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    total_gst: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    total_gross: Mapped[float] = mapped_column(Numeric(12, 2), default=0)

    # Indicative money: unresolved lines that at least have a proposal behind
    # them. Never billed, never added to a total - it exists so a reviewer can
    # tell a $40 slip from a $4,000 one before opening it.
    pending_net: Mapped[float] = mapped_column(Numeric(12, 2), default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)

    taken_over_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    taken_over_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    takeover_reason: Mapped[TakeoverReason | None] = mapped_column(
        Enum(TakeoverReason), nullable=True
    )
    takeover_note: Mapped[str | None] = mapped_column(String(400), nullable=True)

    slip: Mapped[ServiceSlip] = relationship()
    contract: Mapped[Contract | None] = relationship()
    lines: Mapped[list["PaymentLine"]] = relationship(
        back_populates="draft", cascade="all, delete-orphan"
    )
    flags: Mapped[list["ReviewFlag"]] = relationship(
        back_populates="draft", cascade="all, delete-orphan"
    )


class PaymentLine(Base):
    __tablename__ = "payment_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("payment_drafts.id"))
    slip_line_id: Mapped[int] = mapped_column(ForeignKey("slip_lines.id"))
    contract_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("contract_items.id"), nullable=True
    )
    match_method: Mapped[MatchMethod] = mapped_column(Enum(MatchMethod))
    confidence: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str | None] = mapped_column(String(400), nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)

    quantity: Mapped[float] = mapped_column(Float)
    unit_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    line_net: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    # ---- what the machine decided, written once and never modified ----
    # The fields above describe what is being billed *now* and a human may
    # overwrite them. These four are the engine's original answer, kept so a
    # correction can be shown next to what it replaced - and so the silent
    # error rate can be counted at all.
    proposed_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("contract_items.id"), nullable=True
    )
    proposed_method: Mapped[MatchMethod] = mapped_column(Enum(MatchMethod))
    proposed_confidence: Mapped[float] = mapped_column(Float)
    # True when the pipeline priced this line with no human involved. A
    # correction to such a line is a silent error: the machine was sure, and
    # it was wrong.
    auto_priced: Mapped[bool] = mapped_column(Boolean, default=False)

    # ---- human intervention ----
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    corrected_by: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Set only on a slip a reviewer has taken over, for work the catalogue does
    # not cover. This is the one price in the system that does not come from a
    # ContractItem, and it is always a human who put it there.
    manual_description: Mapped[str | None] = mapped_column(String(300), nullable=True)

    draft: Mapped[PaymentDraft] = relationship(back_populates="lines")
    slip_line: Mapped[SlipLine] = relationship()
    contract_item: Mapped[ContractItem | None] = relationship(
        foreign_keys=[contract_item_id]
    )
    proposed_item: Mapped[ContractItem | None] = relationship(
        foreign_keys=[proposed_item_id]
    )

    @property
    def is_manual_price(self) -> bool:
        return self.manual_description is not None

    @property
    def is_silent_error(self) -> bool:
        """The machine priced it confidently and a human had to change it."""
        return self.auto_priced and self.corrected_at is not None

    @property
    def is_cross_category_error(self) -> bool:
        """A material was billed as labour, or the reverse.

        Only counted when both readings name a catalogue item: a correction to
        a manual price says the catalogue had no answer, which is a different
        failure and is not this one.
        """
        if not self.is_silent_error:
            return False
        if self.proposed_item is None or self.contract_item is None:
            return False
        return self.contract_item.category is not self.proposed_item.category


class ReviewFlag(Base):
    __tablename__ = "review_flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("payment_drafts.id"))
    payment_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment_lines.id"), nullable=True
    )
    code: Mapped[FlagCode] = mapped_column(Enum(FlagCode))
    message: Mapped[str] = mapped_column(String(400))

    draft: Mapped[PaymentDraft] = relationship(back_populates="flags")
