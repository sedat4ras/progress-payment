"""HTTP surface.

Every route is a thin shell: read a request, call one function in
`app.pipeline`, redirect. No pricing, matching or state logic lives here, which
is what keeps the guarantee auditable - the money is written in one module and
this is not it.

Writes use plain form posts and redirect afterwards, so a decision can be made
with JavaScript disabled and the back button never resubmits anything.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import AUTO_APPROVE_THRESHOLD, CURRENCY
from app.db import SessionLocal
from app.engine.backends import get_backend
from app.models import FlagCode, PaymentDraft, PaymentLine, ServiceSlip, TakeoverReason
from app.pipeline import (
    SlipProcessor,
    finalize_draft,
    resolve_line,
    set_manual_price,
    take_over,
)
from app.web import presenters

HERE = Path(__file__).parent
REVIEWER = os.getenv("PP_REVIEWER", "Sedat Aras")
REVIEWER_TITLE = "Progress Payment Specialist"

app = FastAPI(title="3P — Progress Payment")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.filters["money"] = lambda v: f"{Decimal(v or 0):,.2f}"
templates.env.filters["pct"] = lambda v: f"{v * 100:.0f}"
templates.env.filters["day"] = lambda d: d.strftime("%-d %b")
templates.env.filters["status"] = lambda s: s.value.replace("_", " ")


def get_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _backend():
    backend = get_backend()
    return backend, backend.available()


def _render(request: Request, session: Session, template: str, **context):
    backend, ready = _backend()
    return templates.TemplateResponse(
        request,
        template,
        {
            "sidebar": presenters.sidebar(session, backend.name, ready),
            "reviewer": REVIEWER,
            "reviewer_title": REVIEWER_TITLE,
            "currency": CURRENCY,
            "threshold": AUTO_APPROVE_THRESHOLD,
            **context,
        },
    )


def _draft(session: Session, draft_id: int) -> PaymentDraft:
    draft = session.get(PaymentDraft, draft_id)
    if draft is None:
        raise HTTPException(404, "No such progress payment.")
    return draft


def _line(session: Session, line_id: int) -> PaymentLine:
    line = session.get(PaymentLine, line_id)
    if line is None:
        raise HTTPException(404, "No such line.")
    return line


def _back_to(draft_id: int, error: str | None = None) -> RedirectResponse:
    target = f"/slips/{draft_id}"
    if error:
        target = f"{target}?error={quote(error)}"
    return RedirectResponse(target, status_code=303)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@app.get("/")
def pipeline(
    request: Request,
    customer: str | None = None,
    flag: str | None = None,
    sort: str = "age",
    session: Session = Depends(get_session),
):
    flag_code = FlagCode(flag) if flag in FlagCode._value2member_map_ else None
    return _render(
        request,
        session,
        "pipeline.html",
        columns=presenters.board(session, customer, flag_code, sort),
        metrics=presenters.metrics(session),
        sort=sort,
        customer=customer,
        customer_label=presenters.customer_name(session, customer) if customer else None,
        flag=flag_code,
        flag_label=presenters.FLAG_LABELS[flag_code] if flag_code else None,
    )


@app.get("/slips/{draft_id}")
def slip(
    request: Request,
    draft_id: int,
    error: str | None = None,
    session: Session = Depends(get_session),
):
    draft = _draft(session, draft_id)
    return _render(
        request,
        session,
        "slip.html",
        draft=draft,
        card=presenters.card(draft),
        lines=presenters.line_views(draft),
        catalogue=presenters.catalogue(draft),
        blocking_reason=presenters.blocking_reason(draft),
        takeover_reasons=list(TakeoverReason),
        error=error,
    )


@app.get("/invalid")
def invalid(request: Request, session: Session = Depends(get_session)):
    return _render(
        request, session, "invalid.html", slips=presenters.invalid_slips(session)
    )


@app.get("/approved")
def approved(
    request: Request, q: str | None = None, session: Session = Depends(get_session)
):
    return _render(
        request,
        session,
        "approved.html",
        cards=presenters.approved_slips(session, q),
        query=q or "",
    )


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------


@app.post("/lines/{line_id}/resolve")
def resolve(
    line_id: int,
    item_code: str = Form(...),
    session: Session = Depends(get_session),
):
    line = _line(session, line_id)
    try:
        resolve_line(
            session,
            line,
            None if item_code == "__not_billable__" else item_code,
            reviewer=REVIEWER,
        )
    except ValueError as exc:
        return _back_to(line.draft_id, str(exc))
    return _back_to(line.draft_id)


@app.post("/lines/{line_id}/manual-price")
def manual_price(
    line_id: int,
    description: str = Form(...),
    unit_price: str = Form(...),
    session: Session = Depends(get_session),
):
    line = _line(session, line_id)
    try:
        set_manual_price(session, line, description, unit_price, reviewer=REVIEWER)
    except (ValueError, ArithmeticError) as exc:
        return _back_to(line.draft_id, str(exc))
    return _back_to(line.draft_id)


@app.post("/slips/{draft_id}/take-over")
def take_slip_over(
    draft_id: int,
    reason: str = Form(...),
    note: str = Form(""),
    session: Session = Depends(get_session),
):
    draft = _draft(session, draft_id)
    try:
        take_over(
            session,
            draft,
            TakeoverReason(reason),
            reviewer=REVIEWER,
            note=note.strip() or None,
        )
    except ValueError as exc:
        return _back_to(draft_id, str(exc))
    return _back_to(draft_id)


@app.post("/slips/{draft_id}/approve")
def approve(draft_id: int, session: Session = Depends(get_session)):
    draft = _draft(session, draft_id)
    try:
        finalize_draft(session, draft, resolved_by=REVIEWER)
    except ValueError as exc:
        return _back_to(draft_id, str(exc))
    return _back_to(draft_id)


@app.post("/slips/{draft_id}/reprocess")
def reprocess(draft_id: int, session: Session = Depends(get_session)):
    """Run the slip through the engine again.

    Discards the existing draft and every human decision on it, which is the
    point: it is the control you reach for after fixing master data or a price
    list, not a way to retry a review.
    """
    slip = session.get(ServiceSlip, _draft(session, draft_id).slip_id)
    fresh = SlipProcessor(session).process(slip)
    return RedirectResponse(f"/slips/{fresh.id}", status_code=303)
