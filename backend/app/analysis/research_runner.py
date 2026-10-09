import asyncio
import logging
from sqlalchemy import select
from app.models.database import Signal, Analysis
from app.models.research import ENGINES
from app.db.session import Session
from app.errors import EngineError, MESSAGES
from app.serpapi_clients.base import SearchClient
from app.analysis.research_normalizers import normalize, obj, safe_url

logger = logging.getLogger('market.research')


def persist(job_id, status, payload):
    with Session.begin() as db:
        row = db.get(Signal, job_id)
        row.status, row.payload = status, payload


async def collect(job_id, tool, plans, report_mode, initial, credentials=None, subject=None):
    client = SearchClient(live=report_mode == 'live', credentials=credentials, max_attempts=9, subject=subject)
    payload = {**initial, 'batches':[], 'usage':client.usage(), 'completed_requests':0}
    try:
        persist(job_id,'running',payload)
        for plan in plans:
            batch = {'label':plan['label'],'rows':[], 'status':'empty', 'message':'', 'source_url':None}
            try:
                raw = await client.search(ENGINES[tool],plan['params'])
                batch['rows'] = normalize(tool,raw,plan['context'])
                metadata = obj(raw.get('search_metadata'))
                batch['source_url'] = next((safe_url(v) for k,v in metadata.items() if k.endswith('_url') and safe_url(v)),None)
                batch['status'] = 'complete' if batch['rows'] else 'empty'
            except EngineError as exc:
                batch.update(status='failed',message=MESSAGES.get(exc.code,'This source is unavailable.'))
            except Exception:
                batch.update(status='failed',message='The source response could not be processed.')
            payload['batches'].append(batch)
            payload['completed_requests'] += 1
            payload['usage'] = client.usage()
            persist(job_id,'running',payload)
            if client.halted:
                for remaining in plans[len(payload['batches']):]:
                    payload['batches'].append({'label':remaining['label'],'rows':[],'status':'skipped','message':'Search allowance unavailable.','source_url':None})
                break
        failed = sum(b['status'] in ('failed','skipped') for b in payload['batches'])
        successful = len(payload['batches']) - failed
        status = 'partial' if failed and successful else 'failed' if failed else 'complete'
        persist(job_id,status,payload)
    except Exception:
        # Keep sanitized errors and accumulated usage if storage recovers.
        payload['error'] = 'Research could not finish. Completed source batches are retained.'
        payload['usage'] = client.usage()
        persist(job_id,'failed',payload)


def run_research(job_id, tool, plans, mode, payload, credentials=None, subject=None):
    try:
        asyncio.run(collect(job_id,tool,plans,mode,payload,credentials,subject))
    except Exception:
        logger.warning('Research job did not finish; saved results may be incomplete.')
