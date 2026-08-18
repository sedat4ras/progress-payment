"""Prompt construction and response parsing, shared by every model backend.

Two rules are enforced in code rather than trusted to the prompt:

  * the model is shown a closed list and any answer outside it is discarded
  * no price is ever shown to the model, so no price can ever come back
"""

from __future__ import annotations

import json

from app.config import LLM_CONFIDENCE_CAP
from app.engine.backends.base import Candidate, Proposal
from app.models import MatchMethod

SYSTEM_PROMPT = """You are the matching assistant for a facilities maintenance
progress payment system.

You will be given one free-text line from a technician's service slip and a
list of items from that customer's contract. Your only job is to say WHICH
item in the list the line refers to.

Rules:
- You may only answer with one of the codes given in the list.
- If you are not sure, or the line describes work that is not any item in the
  list, answer with the code "NONE". Saying NONE when unsure is always better
  than naming the wrong item.
- Sharing a word is not enough; the work performed must be the same.
- Every item is marked MATERIAL (a part or substance supplied) or LABOUR (work
  performed). The two are never interchangeable. A part and the labour of
  fitting that part are described with almost the same words, so decide first
  whether the line reports something SUPPLIED or something DONE, then choose
  only from items of that kind. If the line could honestly be either, answer
  NONE.
- Do not comment on prices, amounts or quantities. That is not your job.

Answer with this JSON and nothing else:
{"code": "<CODE or NONE>", "confidence": <0.0-1.0>, "reason": "<short reason>"}"""


def build_user_prompt(line_text: str, candidates: list[Candidate]) -> str:
    listing = "\n".join(
        f"- {c.item.code}: {c.item.description} "
        f"[{c.item.category.value.upper()}, unit: {c.item.unit}]"
        for c in candidates
    )
    return (
        f"Service slip line:\n{line_text}\n\n"
        f"Candidate contract items:\n{listing}\n\n"
        "JSON answer:"
    )


def parse_proposal(raw: str, candidates: list[Candidate], backend_name: str) -> Proposal | None:
    """Turn a model response into a Proposal, or abstain if it is not usable."""
    allowed = {c.item.code for c in candidates}

    try:
        payload = json.loads(_extract_json(raw))
    except (ValueError, TypeError):
        return None

    code = str(payload.get("code", "")).strip().upper()
    if code in {"", "NONE", "NULL"}:
        return None

    if code not in allowed:
        # The model named something outside the contract. Discard it entirely.
        return None

    try:
        confidence = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        return None

    confidence = min(max(confidence, 0.0), LLM_CONFIDENCE_CAP)
    reason = str(payload.get("reason", ""))[:200] or "Model proposal."

    return Proposal(
        item_code=code,
        confidence=round(confidence, 3),
        method=MatchMethod.LLM,
        rationale=f"[{backend_name}] {reason}",
    )


def _extract_json(raw: str) -> str:
    """Models sometimes wrap JSON in prose or fences. Take the first object."""
    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object in response")
    return text[start : end + 1]
