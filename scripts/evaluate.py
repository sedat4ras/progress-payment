"""Scores the engine against the synthetic ground truth.

The number that matters is `silently mispriced`: a line that was priced
automatically against the wrong contract item. A human never sees those, so
they are the only failures that can actually put a wrong figure in front of a
customer. Target is zero, and everything else is a workload trade-off.

Part-versus-labour failures are reported separately, in two forms. Billing a
part as the labour of fitting it is not a near miss on the same kind of thing,
it is the failure the whole category apparatus exists to prevent, so it stays
visible even when the overall figure is small.

  * a mispricing that swapped a material for labour, where the ground truth
    says which side was right
  * the deliberately undecidable lines, where nothing in the wording says
    whether something was supplied or done. There is no right answer to price
    these with, so the only passing behaviour is to hand them to a human.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from sqlalchemy import select

from app.config import AUTO_APPROVE_THRESHOLD
from app.db import session_scope
from app.engine.backends import get_backend
from app.engine.normalize import normalize
from app.models import DraftStatus, MatchMethod, PaymentDraft
from app.pipeline import process_all
from data.catalog import CATEGORY_TRAP_PHRASES


def evaluate(backend_name: str | None = None) -> dict:
    backend = get_backend(backend_name)
    traps = {normalize(phrase) for phrase in CATEGORY_TRAP_PHRASES}

    with session_scope() as session:
        process_all(session, backend=backend)

        drafts = session.scalars(select(PaymentDraft)).all()

        status_counts = Counter(d.status for d in drafts)
        method_counts = Counter()
        stats = Counter()

        for draft in drafts:
            if draft.status is DraftStatus.INVALID:
                stats["lines_on_invalid_slips"] += len(draft.slip.lines)
                continue

            category_of = {item.code: item.category for item in draft.contract.items}

            for line in draft.lines:
                truth = line.slip_line.truth_item_code
                got = line.contract_item.code if line.contract_item else None
                undecidable = normalize(line.slip_line.raw_description) in traps
                method_counts[line.match_method] += 1
                stats["undecidable"] += undecidable

                if line.needs_review:
                    stats["queued"] += 1
                    stats["undecidable_held"] += undecidable
                    if truth is not None and truth == got:
                        stats["queued_but_correct"] += 1
                    continue

                stats["auto_priced"] += 1
                stats["undecidable_priced_anyway"] += undecidable
                if truth is not None and truth == got:
                    stats["auto_correct"] += 1
                    continue

                stats["silently_mispriced"] += 1
                if _crosses_category(category_of, truth, got):
                    stats["cross_category"] += 1

        return {
            "backend": backend.name,
            "threshold": AUTO_APPROVE_THRESHOLD,
            "slips": len(drafts),
            "status": status_counts,
            "methods": method_counts,
            "stats": stats,
        }


def _crosses_category(category_of: dict, truth: str | None, got: str | None) -> bool:
    """Whether a mispricing swapped a material for labour or the reverse.

    Only decidable when both sides name a real contract item. A line that
    should not have been priced at all (`truth is None`) is a different kind of
    failure and is not counted here.
    """
    if truth is None or got is None:
        return False
    left, right = category_of.get(truth), category_of.get(got)
    return left is not None and right is not None and left is not right


def render(result: dict) -> str:
    stats = result["stats"]
    auto = stats["auto_priced"]
    queued = stats["queued"]
    lines = auto + queued

    out = [
        f"Backend                : {result['backend']}",
        f"Auto-approve threshold : {result['threshold']}",
        "",
        f"Service slips          : {result['slips']}",
    ]
    for status in DraftStatus:
        count = result["status"].get(status, 0)
        if count:
            out.append(f"  {status.value:<12} : {count}")

    out += [
        "",
        f"Lines evaluated        : {lines}",
        f"  priced automatically : {auto} ({_pct(auto, lines)}%)",
        f"  sent to the queue    : {queued} ({_pct(queued, lines)}%)",
        "",
        "Match method:",
    ]
    for method in MatchMethod:
        count = result["methods"].get(method, 0)
        if count:
            out.append(f"  {method.value:<8} : {count}")

    out += [
        "",
        f"Automatic and correct   : {stats['auto_correct']}",
        f"SILENTLY MISPRICED      : {stats['silently_mispriced']}   <-- target 0",
        f"  material <-> labour   : {stats['cross_category']}",
        "",
        "Part-or-labour lines the wording cannot settle:",
        f"  seen                  : {stats['undecidable']}",
        f"  held for a human      : {stats['undecidable_held']}",
        f"  PRICED ANYWAY         : {stats['undecidable_priced_anyway']}   <-- target 0",
        "",
        f"Queued unnecessarily    : {stats['queued_but_correct']} "
        f"(matched correctly but confidence sat below the threshold)",
        f"Lines on invalid slips  : {stats['lines_on_invalid_slips']}",
    ]
    return "\n".join(out)


def _pct(part: int, whole: int) -> str:
    return f"{(100 * part / whole):.1f}" if whole else "0.0"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default=None, help="rules | ollama | openai")
    args = parser.parse_args()

    result = evaluate(args.backend)
    print(render(result))
    stats = result["stats"]
    sys.exit(
        1 if stats["silently_mispriced"] or stats["undecidable_priced_anyway"] else 0
    )
