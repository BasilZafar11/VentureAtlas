import asyncio
import json
import logging
import time
from collections import Counter
from threading import Lock
from pathlib import Path
import serpapi
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential
from app.config import settings
from app.errors import EngineError
from app.search_budget import claim_provider_attempt, DailySearchLimit

logger = logging.getLogger('market.search')
FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures'


class SearchClient:
    def __init__(self, live=None, credentials=None, max_attempts=30, subject=None):
        self.subject = subject
        self.credentials = credentials
        self.live = settings.live_serpapi_enabled if live is None else live
        if credentials:
            self.live = True
        if self.live and not settings.live_serpapi_enabled and not credentials:
            raise EngineError('AUTH_ERROR')
        self.max_attempts = max_attempts
        self.halted = False
        self.related_queries = []
        self.review_tokens = {}
        self.logical_requests = Counter()
        self.provider_attempts = Counter()
        self._count_lock = Lock()

    def usage(self):
        return {'mode': 'live' if self.live else 'fixture', 'logical_requests': dict(self.logical_requests),
                'provider_attempts': dict(self.provider_attempts), 'total_requests': sum(self.logical_requests.values()),
                'total_provider_attempts': sum(self.provider_attempts.values()),
                'billing_note': 'Requests are not confirmed billable credits. Provider caching and billing rules may differ.'}

    async def search(self, engine: str, params: dict):
        started, status = time.monotonic(), 'failed'
        try:
            if self.halted:
                raise EngineError('ALLOWANCE_UNAVAILABLE')
            self.logical_requests[engine] += 1
            if not self.live:
                fixture = engine
                if engine == 'google_maps' and params.get('type') == 'place':
                    fixture = 'google_maps_hours'
                if engine == 'google_maps_reviews' and params.get('next_page_token'):
                    fixture = 'google_maps_reviews_history'
                if engine == 'google_trends' and params.get('data_type') == 'RELATED_QUERIES':
                    fixture = 'google_trends_related'
                elif engine == 'google_trends' and params.get('date') == 'today 5-y':
                    fixture = 'google_trends_seasonality'
                result = json.loads((FIXTURES / f'{fixture}.json').read_text(encoding='utf-8'))
            else:
                result = await asyncio.to_thread(self._search, engine, params)
            status = 'complete'
            return result
        finally:
            logger.info('engine=%s duration=%.2f status=%s', engine, time.monotonic() - started, status)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=.5, max=2),
           retry=retry_if_exception(lambda e: isinstance(e, EngineError) and e.code == 'ENGINE_UNAVAILABLE'), reraise=True)
    def _search(self, engine, params):
        if self.halted:
            raise EngineError('ALLOWANCE_UNAVAILABLE')
        key = self.credentials.serpapi.get_secret_value() if self.credentials else settings.serpapi_key.get_secret_value()
        if not key:
            raise EngineError('AUTH_ERROR')
        try:
            client = serpapi.Client(api_key=key, timeout=settings.request_timeout_seconds)
            with self._count_lock:
                if sum(self.provider_attempts.values()) >= self.max_attempts:
                    self.halted = True
                    raise EngineError('ALLOWANCE_UNAVAILABLE')
                if not self.credentials:
                    claim_provider_attempt(self.subject) if self.subject else claim_provider_attempt()
                self.provider_attempts[engine] += 1
            result = dict(client.search({'engine': engine, **params}))
            error = str(result.get('error', ''))
            if error:
                if any(word in error.lower() for word in ('api key', 'unauthorized', 'authentication')):
                    raise EngineError('AUTH_ERROR')
                if any(word in error.lower() for word in ('run out', 'quota', 'rate limit', 'searches left', 'credits')):
                    self.halted = True
                    raise EngineError('ALLOWANCE_UNAVAILABLE')
                if 'no results' in error.lower() or "hasn't returned any results" in error.lower():
                    return {}
                raise EngineError('INVALID_RESPONSE')
            return result
        except serpapi.HTTPError as exc:
            code = getattr(exc, 'status_code', 0)
            if code in (401, 403):
                raise EngineError('AUTH_ERROR') from None
            if code == 429:
                self.halted = True
                raise EngineError('ALLOWANCE_UNAVAILABLE') from None
            raise EngineError('ENGINE_UNAVAILABLE' if code >= 500 else 'INVALID_RESPONSE') from None
        except DailySearchLimit:
            self.halted = True
            raise EngineError('ALLOWANCE_UNAVAILABLE') from None
        except EngineError:
            raise
        except Exception:
            raise EngineError('ENGINE_UNAVAILABLE') from None
