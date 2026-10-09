import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from fastapi import BackgroundTasks, HTTPException
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import main
from app.analysis import groq_enrichment, novelty
from app.config import settings
from app.db.session import Session
from app.errors import EngineError
from app.models.novelty import NoveltyReport, NoveltyWorkspace
from app.provider_credentials import ProviderCredentials, credentials_for
from app.search_budget import DailySearchLimit, claim_provider_attempt, claim_groq_attempt
from app.serpapi_clients import base
from app import search_budget
from app.models.novelty import NoveltyDailyBudget, GroqDailyBudget, SerpApiUserBudget

PERSONAL = 'dummy-personal-serpapi-key'
HOSTED = 'dummy-hosted-serpapi-key'
GROQ = 'dummy-personal-groq-key'


@pytest.fixture
def isolated_budget(monkeypatch, tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'dummy-budget.db'),
                           connect_args={'check_same_thread': False, 'timeout': 30})
    NoveltyDailyBudget.__table__.create(engine)
    GroqDailyBudget.__table__.create(engine)
    SerpApiUserBudget.__table__.create(engine)
    sessions = sessionmaker(engine)
    monkeypatch.setattr(search_budget, 'Session', sessions)
    monkeypatch.setattr(settings, 'hosted_serpapi_daily_budget', 20)
    monkeypatch.setattr(settings, 'hosted_serpapi_reserve', 0)
    yield engine, sessions
    engine.dispose()


def test_user_allowances_are_independent_and_concurrent(isolated_budget, monkeypatch):
    monkeypatch.setattr(settings, 'hosted_serpapi_daily_budget', 100)
    def attempt(_):
        try:
            claim_provider_attempt('account:first')
            return True
        except DailySearchLimit:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(30))) == 20
    assert search_budget.user_remaining('account:first') == 0
    assert search_budget.user_remaining('account:second') == 20
    claim_provider_attempt('account:second')
    assert search_budget.user_remaining('account:second') == 19
    # A fresh session factory represents a restarted process against the same database.
    monkeypatch.setattr(search_budget, 'Session', sessionmaker(isolated_budget[0]))
    with pytest.raises(DailySearchLimit): claim_provider_attempt('account:first')


def test_global_rejection_rolls_back_user_charge(isolated_budget, monkeypatch):
    monkeypatch.setattr(settings, 'hosted_serpapi_daily_budget', 1)
    claim_provider_attempt('account:first')
    with pytest.raises(DailySearchLimit): claim_provider_attempt('account:second')
    assert search_budget.user_remaining('account:second') == 20


def test_user_reset_is_midnight_ist(isolated_budget, monkeypatch):
    monkeypatch.setattr(settings, 'hosted_serpapi_daily_budget', 100)
    tick = [datetime(2026, 10, 9, 18, 29, 59, tzinfo=timezone.utc)]
    monkeypatch.setattr(search_budget, 'datetime', SimpleNamespace(now=lambda zone: tick[0].astimezone(zone)))
    for _ in range(20): claim_provider_attempt('account:first')
    with pytest.raises(DailySearchLimit): claim_provider_attempt('account:first')
    tick[0] = datetime(2026, 10, 9, 18, 30, tzinfo=timezone.utc)
    assert search_budget.user_remaining('account:first') == 20
    claim_provider_attempt('account:first')
    assert search_budget.user_remaining('account:first') == 19


def test_concurrent_attempts_cannot_exceed_shared_daily_limit(isolated_budget, monkeypatch):
    tick = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(search_budget, 'datetime', SimpleNamespace(now=lambda zone: tick))
    def attempt(_):
        try:
            search_budget.claim_provider_attempt()
            return True
        except DailySearchLimit:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = list(pool.map(attempt, range(30)))
    assert sum(accepted) == 20
    with isolated_budget[1]() as db:
        row = db.get(NoveltyDailyBudget, tick.date().isoformat())
        assert row.calls_used == 20


def test_counter_survives_new_sessions_and_resets_only_at_utc_day(isolated_budget, monkeypatch):
    engine, sessions = isolated_budget
    monkeypatch.setattr(settings, 'hosted_serpapi_daily_budget', 1)
    tick = [datetime(2026, 10, 9, 23, 59, 59, tzinfo=timezone.utc)]
    monkeypatch.setattr(search_budget, 'datetime', SimpleNamespace(now=lambda zone: tick[0]))
    search_budget.claim_provider_attempt()
    monkeypatch.setattr(search_budget, 'Session', sessionmaker(engine))
    with pytest.raises(DailySearchLimit): search_budget.claim_provider_attempt()
    tick[0] = datetime(2026, 10, 10, 0, 0, 0, tzinfo=timezone.utc)
    search_budget.claim_provider_attempt()
    with sessions() as db:
        assert db.get(NoveltyDailyBudget, '2026-10-09').calls_used == 1
        assert db.get(NoveltyDailyBudget, '2026-10-10').calls_used == 1


def request(token='', **headers):
    return SimpleNamespace(headers={'X-Review-Token': token, **headers},
                           client=SimpleNamespace(host='127.0.0.1'))


def forbidden(*args, **kwargs):
    raise AssertionError('Unexpected hosted allowance or provider request')


def test_personal_search_selects_only_own_key_and_skips_shared_budget(monkeypatch):
    selected = []
    monkeypatch.setattr(settings, 'live_serpapi_enabled', True)
    monkeypatch.setattr(settings, 'serpapi_key', SecretStr(HOSTED))
    monkeypatch.setattr(base, 'claim_provider_attempt', forbidden)
    monkeypatch.setattr(novelty, 'claim_provider_attempt', forbidden)
    def client(**kwargs):
        selected.append(kwargs['api_key'])
        return SimpleNamespace(search=lambda params: {})
    monkeypatch.setattr(base.serpapi, 'Client', client)
    credentials = ProviderCredentials(serpapi=PERSONAL)
    search = base.SearchClient(credentials=credentials)
    assert search._search('google_news', {'q': 'Research'}) == {}
    assert novelty.provider_search(client(api_key=PERSONAL), 'google_scholar', personal=True, q='Research') == {}
    assert selected == [PERSONAL, PERSONAL]


def test_hosted_provider_caps_fail_before_request(monkeypatch):
    monkeypatch.setattr(settings, 'hosted_serpapi_daily_budget', 1)
    monkeypatch.setattr(settings, 'hosted_serpapi_reserve', 0)
    monkeypatch.setattr(settings, 'hosted_groq_daily_budget', 1)
    claim_provider_attempt()
    claim_groq_attempt()
    with pytest.raises(DailySearchLimit): claim_provider_attempt()
    with pytest.raises(DailySearchLimit): claim_groq_attempt()
    monkeypatch.setattr(settings, 'live_serpapi_enabled', True)
    monkeypatch.setattr(settings, 'serpapi_key', SecretStr(HOSTED))
    monkeypatch.setattr(base.serpapi, 'Client', lambda **kwargs: SimpleNamespace(search=forbidden))
    with pytest.raises(EngineError) as failure:
        base.SearchClient()._search('google_news', {'q': 'Research'})
    assert failure.value.code == 'ALLOWANCE_UNAVAILABLE'


def test_invalid_personal_key_never_retries_with_hosted_credentials(monkeypatch):
    selected = []
    monkeypatch.setattr(settings, 'serpapi_key', SecretStr(HOSTED))
    monkeypatch.setattr(base, 'claim_provider_attempt', forbidden)
    def client(**kwargs):
        selected.append(kwargs['api_key'])
        return SimpleNamespace(search=lambda params: {'error': 'Invalid API key'})
    monkeypatch.setattr(base.serpapi, 'Client', client)
    with pytest.raises(EngineError) as failure:
        base.SearchClient(credentials=ProviderCredentials(serpapi=PERSONAL))._search('google_news', {'q': 'Research'})
    assert failure.value.code == 'AUTH_ERROR'
    assert selected == [PERSONAL]


def test_personal_groq_uses_own_key_without_hosted_fallback(monkeypatch):
    authorization = []
    monkeypatch.setattr(settings, 'groq_enabled', True)
    monkeypatch.setattr(settings, 'groq_api_key', SecretStr('dummy-hosted-groq-key'))
    monkeypatch.setattr(groq_enrichment, 'claim_groq_attempt', forbidden)
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def raise_for_status(self): pass
        def iter_bytes(self):
            yield json.dumps({'choices': [{'message': {'content': '{}'}}]}).encode()
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def stream(self, method, url, **kwargs):
            authorization.append(kwargs['headers']['Authorization'])
            return Response()
    monkeypatch.setattr(groq_enrichment.httpx, 'Client', Client)
    assert groq_enrichment._complete('Schema', {}, ProviderCredentials(serpapi=PERSONAL, groq=GROQ)) == {}
    with pytest.raises(RuntimeError):
        groq_enrichment._complete('Schema', {}, ProviderCredentials(serpapi=PERSONAL))
    assert authorization == ['Bearer ' + GROQ]


def test_personal_credentials_require_serpapi_and_bounded_key():
    with pytest.raises(HTTPException): credentials_for(request(**{'X-Groq-Key': GROQ}))
    with pytest.raises(HTTPException): credentials_for(request(**{'X-SerpApi-Key': 'bad key'}))
    assert credentials_for(request()) is None


def test_creation_issues_owner_once_without_persisting_provider_keys():
    data = main.NoveltyInput(
        title='A sufficiently descriptive research title',
        abstract='A sufficiently long abstract describing the proposed technical system, its methods, and intended research contribution.',
        keywords=['first technical term', 'second technical term', 'third technical term'],
        use_groq=False,
    )
    background = BackgroundTasks()
    response = main.create_novelty_analysis(data, request(**{'X-SerpApi-Key': PERSONAL}), background)
    result = json.loads(response.body)
    assert response.status_code == 202
    assert result['owner_token'] and result['review_token']
    assert main.create_novelty_workspace(uuid4()).status_code == 403
    with Session() as db:
        row = db.get(NoveltyReport, result['id'])
        workspace = db.get(NoveltyWorkspace, result['id'])
        assert PERSONAL not in json.dumps(row.input_data)
        assert workspace.owner_token_hash == hashlib.sha256(result['owner_token'].encode()).hexdigest()
        assert result['owner_token'] != workspace.owner_token_hash
    assert len(background.tasks) == 1


def test_workspace_privacy_and_rotation_revoke_old_capabilities():
    identifier = uuid4()
    with Session.begin() as db:
        db.add(NoveltyReport(id=str(identifier), fingerprint='privacy-test', title='Study', field='',
                            input_data={}, status='complete', saved=True, is_public=False,
                            report=main.sample_novelty_report()))
        db.add(NoveltyWorkspace(report_id=str(identifier), comments=[], watched=False,
                               owner_token_hash=hashlib.sha256(b'owner').hexdigest(),
                               review_token_hash=hashlib.sha256(b'reviewer').hexdigest()))
    assert main.get_novelty_workspace(identifier, request()).status_code == 403
    assert main.get_novelty_workspace(identifier, request('reviewer'))['comments'] == []
    assert main.rotate_workspace(identifier, request('reviewer')).status_code == 403
    rotated = main.rotate_workspace(identifier, request('owner'))
    assert main.get_novelty_workspace(identifier, request('owner')).status_code == 403
    assert main.get_novelty_workspace(identifier, request('reviewer')).status_code == 403
    assert main.get_novelty_workspace(identifier, request(rotated['review_token']))['comments'] == []


def test_personal_refresh_applies_explicit_ai_consent_without_shared_fallback():
    data=main.NoveltyInput(title='A sufficiently descriptive research title',
        abstract='A sufficiently long abstract describing the proposed technical system, its methods, and intended research contribution.',
        keywords=['first technical term','second technical term','third technical term'],use_groq=False)
    created=json.loads(main.create_novelty_analysis(data,request(**{'X-SerpApi-Key':PERSONAL}),BackgroundTasks()).body)
    with Session.begin() as db:
        row=db.get(NoveltyReport,created['id']);row.status='complete';row.report={'credential_mode':'personal'}
    denied=main.refresh_novelty_analysis(created['id'],request(created['owner_token']),BackgroundTasks())
    assert denied.status_code==409
    refreshed=main.refresh_novelty_analysis(created['id'],request(created['owner_token'],**{'X-SerpApi-Key':PERSONAL,'X-Groq-Key':GROQ}),BackgroundTasks(),main.RefreshOptions(use_groq=True))
    assert refreshed.status_code==202
    with Session() as db:
        row=db.get(NoveltyReport,json.loads(refreshed.body)['id'])
        assert row.input_data['use_groq'] is True
        assert PERSONAL not in json.dumps(row.input_data) and GROQ not in json.dumps(row.input_data)
