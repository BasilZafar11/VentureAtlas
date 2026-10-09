"""Claim a provider attempt before sending any paid search request."""
import hashlib
import hmac
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.config import settings
from app.db.session import Session
from app.models.novelty import NoveltyDailyBudget, GroqDailyBudget, SerpApiUserBudget

IST = timezone(timedelta(hours=5, minutes=30))


def user_subject(request):
    authorization = request.headers.get('Authorization')
    if authorization:
        from app.venture_api import account
        with Session() as db:
            return 'account:' + account(db, authorization).id
    secret = settings.ip_hash_secret.get_secret_value()
    if len(secret) < 32:
        raise HTTPException(503, 'Hosted search identity is not configured.')
    address = request.client.host if request.client else 'unknown'
    return 'guest:' + hmac.new(secret.encode(), address.encode(), hashlib.sha256).hexdigest()


def user_remaining(subject):
    day = datetime.now(IST).date().isoformat()
    with Session() as db:
        budget = db.get(SerpApiUserBudget, (subject, day))
        return max(0, 20 - (budget.calls_used if budget else 0))


class DailySearchLimit(Exception):
    pass


def hosted_remaining():
    day = datetime.now(timezone.utc).date().isoformat()
    with Session() as db:
        budget = db.get(NoveltyDailyBudget, day)
        return max(0, settings.hosted_serpapi_daily_budget - settings.hosted_serpapi_reserve
                   - (budget.calls_used + budget.calls_reserved if budget else 0))


def claim_groq_attempt():
    day = datetime.now(timezone.utc).date().isoformat()
    with Session.begin() as db:
        insert = sqlite_insert if db.bind.dialect.name == 'sqlite' else postgres_insert
        db.execute(insert(GroqDailyBudget).values(day_utc=day, calls_used=0)
                   .on_conflict_do_nothing(index_elements=['day_utc']))
        claimed = db.execute(update(GroqDailyBudget).where(GroqDailyBudget.day_utc == day,
                             GroqDailyBudget.calls_used < max(0, settings.hosted_groq_daily_budget))
                             .values(calls_used=GroqDailyBudget.calls_used + 1))
        if claimed.rowcount != 1:
            raise DailySearchLimit('Hosted AI allowance exhausted.')


def claim_provider_attempt(subject=None):
    day = datetime.now(timezone.utc).date().isoformat()
    limit = max(0, settings.hosted_serpapi_daily_budget - settings.hosted_serpapi_reserve)
    with Session.begin() as db:
        insert = sqlite_insert if db.bind.dialect.name == 'sqlite' else postgres_insert
        if subject:
            user_day = datetime.now(IST).date().isoformat()
            db.execute(insert(SerpApiUserBudget).values(subject=subject, day_ist=user_day, calls_used=0)
                       .on_conflict_do_nothing(index_elements=['subject', 'day_ist']))
            user_claim = db.execute(update(SerpApiUserBudget)
                                   .where(SerpApiUserBudget.subject == subject,
                                          SerpApiUserBudget.day_ist == user_day,
                                          SerpApiUserBudget.calls_used < 20)
                                   .values(calls_used=SerpApiUserBudget.calls_used + 1))
            if user_claim.rowcount != 1:
                raise DailySearchLimit('Your 20 daily searches are used. Use a personal key or wait until midnight IST.')
        db.execute(insert(NoveltyDailyBudget).values(day_utc=day, calls_reserved=0, calls_used=0)
                   .on_conflict_do_nothing(index_elements=['day_utc']))
        claimed = db.execute(update(NoveltyDailyBudget)
                             .where(NoveltyDailyBudget.day_utc == day,
                                    NoveltyDailyBudget.calls_used < limit)
                             .values(calls_used=NoveltyDailyBudget.calls_used + 1))
        if claimed.rowcount != 1:
            raise DailySearchLimit('The daily search allowance is exhausted. Try again after the UTC daily reset.')
