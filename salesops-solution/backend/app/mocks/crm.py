"""Mock CRM — fuzzy matches inbound text to a Customer/Quote in our SQLite tables."""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Iterable

from sqlalchemy.orm import Session

from ..models import Customer, Quote


def find_customer(db: Session, *, email: str | None, name_hint: str | None) -> tuple[Customer | None, float]:
    customers: Iterable[Customer] = db.query(Customer).all()
    best, score = None, 0.0
    for c in customers:
        s = 0.0
        if email and c.email and email.lower() == c.email.lower():
            return c, 1.0
        if email and c.email:
            s = max(s, SequenceMatcher(None, email.lower(), c.email.lower()).ratio())
        if name_hint:
            s = max(s, SequenceMatcher(None, name_hint.lower(), c.name.lower()).ratio())
        if s > score:
            best, score = c, s
    return best, score


def find_quote(db: Session, *, customer_id: int | None, quote_number: str | None) -> Quote | None:
    if not customer_id and not quote_number:
        return None
    q = db.query(Quote)
    if quote_number:
        exact = q.filter(Quote.quote_number == quote_number).first()
        if exact:
            return exact
        if customer_id:
            normalized = quote_number.strip().lower()
            for cand in q.filter(Quote.customer_id == customer_id).all():
                if cand.quote_number.lower() == normalized:
                    return cand
        return None
    if customer_id:
        return (
            q.filter(Quote.customer_id == customer_id)
            .order_by(Quote.id.desc())
            .first()
        )
    return None
