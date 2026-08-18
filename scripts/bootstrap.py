"""Prepare a demo database: seed if empty, then process every slip.

Safe to run repeatedly - it will not wipe expert corrections that already
exist. Use `--reset` to start over.
"""

from __future__ import annotations

import argparse

from sqlalchemy import func, select

from app.db import init_db, session_scope
from app.engine.backends import get_backend
from app.models import Customer, PaymentDraft
from app.pipeline import process_all
from data.generate import seed


def bootstrap(reset: bool = False, backend_name: str | None = None) -> None:
    init_db(drop=reset)

    with session_scope() as session:
        customers = session.scalar(select(func.count()).select_from(Customer))

    if reset or not customers:
        seed(reset=reset)
        print("Synthetic dataset created.")

    with session_scope() as session:
        drafts = session.scalar(select(func.count()).select_from(PaymentDraft))
        if reset or not drafts:
            backend = get_backend(backend_name)
            processed = process_all(session, backend=backend)
            print(f"Processed {len(processed)} slips (backend: {backend.name}).")
        else:
            print(f"{drafts} progress payments already exist; nothing reprocessed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="wipe the database first")
    parser.add_argument("--backend", default=None, help="rules | ollama | openai")
    args = parser.parse_args()
    bootstrap(reset=args.reset, backend_name=args.backend)
