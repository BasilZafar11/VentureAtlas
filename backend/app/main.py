import asyncio
import hashlib
import hmac
import secrets
import time
import json
from io import BytesIO
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from uuid import UUID
from threading import Lock
from datetime import timedelta, timezone, datetime

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from sqlalchemy import select, text, update, func, desc, delete
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.config import SAVED_REPORT_RETENTION_DAYS, settings
from app.provider_credentials import credentials_for
from app.search_budget import hosted_remaining, user_subject, user_remaining, IST
from app.pdf_review import extract_pdf, PdfBusy, PdfUnavailable
from app.db.session import Session, engine
from app.db.repositories import active, cached
from app.models.database import Analysis, Signal, now, uid
from app.models.schemas import AnalysisInput, RelevanceInput
from app.analysis.orchestrator import run_job
from app.analysis.relevance import revise_report
from app.analysis.stress import stress_test
from app.models.research import ResearchInput, ENGINES, plan_requests
from app.analysis.research_runner import run_research
from app.models.novelty import NoveltyReport, NoveltyUsage, NoveltyDailyBudget, GroqDailyBudget
from app.models.novelty import NoveltyWorkspace
from app.analysis.novelty import run_novelty_job, DISCLAIMER
from app.analysis.novelty import score_report
from app.analysis.research_guidance import contribution_brief
from copy import deepcopy
from app.analysis.novelty import cosine, safe_url
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.venture_api import router as venture_router
from app.integrity_api import router as integrity_router
from app.research_state_api import router as research_state_router


def error(status, code, message, details=None):
    return JSONResponse(status_code=status, content={'error': {'code': code, 'message': message, 'details': details or {}}})


def finish_novelty_usage(db, analysis_id, calls_used, status):
    usage=db.scalar(select(NoveltyUsage).where(NoveltyUsage.analysis_id==analysis_id))
    if not usage or usage.status!='reserved': return
    budget=db.get(NoveltyDailyBudget,usage.day_utc)
    usage.calls_used=min(usage.calls_reserved,max(0,calls_used));usage.status=status
    if budget:
        budget.calls_reserved=max(0,budget.calls_reserved-usage.calls_reserved)


def hosted_search_configured():
    return (settings.live_serpapi_enabled and bool(settings.serpapi_key.get_secret_value())
            and len(settings.ip_hash_secret.get_secret_value().encode())>=32
            and settings.hosted_reports_per_ip_per_day>0
            and settings.hosted_serpapi_daily_budget>settings.hosted_serpapi_reserve>=0)


def novelty_report_current(row):
    if not row or row.status!='complete' or not row.report:
        return False
    created=row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=timezone.utc)
    return created>=now()-(timedelta(days=SAVED_REPORT_RETENTION_DAYS) if row.saved else timedelta(hours=1))


def cleanup_expired_reports(db):
    retention=now()-timedelta(days=SAVED_REPORT_RETENTION_DAYS);temporary=now()-timedelta(hours=1)
    db.execute(delete(NoveltyReport).where(((NoveltyReport.saved.is_(True))&(NoveltyReport.created_at<retention))|((NoveltyReport.saved.is_(False))&(NoveltyReport.created_at<temporary))))
    db.execute(delete(NoveltyWorkspace).where(NoveltyWorkspace.report_id.not_in(select(NoveltyReport.id))))


class NoveltyInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=5, max_length=160)
    abstract: str = Field(min_length=50, max_length=2000)
    field: str = Field(default='', max_length=160)
    keywords: list[str] = Field(min_length=3, max_length=10)
    claims: list[str] = Field(default_factory=list, max_length=3)
    earliest_year: int | None = Field(default=None, ge=1800, le=2100)
    known_related_work: list[str] = Field(default_factory=list, max_length=10)
    refresh: bool = False
    use_groq: bool = False
    save_report: bool = True
    is_public: bool = False

    @model_validator(mode='after')
    def validate_public_save(self):
        if self.is_public and not self.save_report:
            raise ValueError('A public report must be saved')
        return self

    @field_validator('title','abstract','field', mode='before')
    @classmethod
    def clean_text(cls, v):
        if not isinstance(v, str): raise ValueError('Text is required')
        if any(ord(c)<32 and c not in '\n\t\r' for c in v): raise ValueError('Control characters are not allowed')
        return v.strip()

    @field_validator('keywords','claims','known_related_work')
    @classmethod
    def clean_entries(cls, values):
        values=[' '.join(v.strip().split()) for v in values]
        if any(not v or len(v)>400 for v in values): raise ValueError('Each entry must contain 1–400 characters')
        if len({v.casefold() for v in values}) != len(values): raise ValueError('Entries must be unique')
        return values

    @field_validator('keywords')
    @classmethod
    def keyword_lengths(cls, values):
        if any(len(v)<3 or len(v)>100 for v in values): raise ValueError('Keywords must contain 3–100 characters')
        return values

    @field_validator('claims')
    @classmethod
    def claim_lengths(cls, values):
        if any(len(v)<15 for v in values): raise ValueError('Each claim must contain at least 15 characters')
        return values


class RevisionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=5, max_length=160)
    abstract: str = Field(min_length=50, max_length=2000)
    claims: list[str] = Field(min_length=1, max_length=3)

    @field_validator('claims')
    @classmethod
    def valid_claims(cls, values):
        if any(len(value.strip()) < 15 or len(value) > 400 for value in values):
            raise ValueError('Each claim must contain 15–400 characters')
        return [value.strip() for value in values]


class ReviewCommentInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    author: str = Field(min_length=2, max_length=80)
    claim_id: str | None = Field(default=None, max_length=40)
    kind: str = Field(pattern='^(comment|challenge|missing_source|reviewed)$')
    text: str = Field(min_length=5, max_length=1000)
    source_url: str | None = Field(default=None, max_length=800)


class WatchInput(BaseModel):
    watched: bool


class RefreshOptions(BaseModel):
    model_config=ConfigDict(extra='forbid')
    use_groq: bool | None = None


@asynccontextmanager
async def lifespan(app):
    # One Render process: rows left running after a restart cannot resume safely.
    try:
        with Session.begin() as db:
            db.execute(update(Analysis).where(Analysis.status.in_(['queued', 'running'])).values(status='failed', error_message='The server restarted. Please start a new analysis.', completed_at=now()))
            for job in db.scalars(select(Signal).where(Signal.signal_type == 'research_extension', Signal.status.in_(['queued','running']))):
                job.status = 'failed'
                job.payload = {**job.payload, 'error':'The server restarted. Start a new research run; any completed batches are retained.'}
            for report in db.scalars(select(NoveltyReport).where(NoveltyReport.status.in_(['queued','running']))):
                report.status='failed';report.stage='failed';report.progress=100
                report.error_message='The server restarted. Please start a new analysis.'
                finish_novelty_usage(db,report.id,8,'interrupted')
            cleanup_expired_reports(db)
            oldest_day=(now()-timedelta(days=7)).date().isoformat()
            db.execute(delete(NoveltyUsage).where(NoveltyUsage.day_utc<oldest_day))
            db.execute(delete(NoveltyDailyBudget).where(NoveltyDailyBudget.day_utc<oldest_day))
            db.execute(delete(GroqDailyBudget).where(GroqDailyBudget.day_utc<oldest_day))
        app.state.database_ready=True
    except SQLAlchemyError:
        # Keep the independent sample report available when report storage is offline.
        app.state.database_ready=False
    cleanup_task=asyncio.create_task(retention_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        try:await cleanup_task
        except asyncio.CancelledError:pass


async def retention_loop():
    while True:
        await asyncio.sleep(3600)
        def clean():
            try:
                with Session.begin() as db:cleanup_expired_reports(db)
            except SQLAlchemyError:pass
        await asyncio.to_thread(clean)


app = FastAPI(title='ResearchScope · Research evidence workspace', lifespan=lifespan)
app.include_router(venture_router)
app.include_router(integrity_router)
app.include_router(research_state_router)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=['GET', 'POST', 'DELETE'], allow_headers=['Content-Type','Authorization','X-Review-Token','X-SerpApi-Key','X-Groq-Key'])
hits = defaultdict(deque)
salt = secrets.token_bytes(32)
research_lock = Lock()
pdf_upload_slot = asyncio.Semaphore(1)


@app.middleware('http')
async def headers(request, call_next):
    pdf=request.method=='POST' and request.url.path.endswith('/document-review')
    if pdf:
        if pdf_upload_slot.locked():return error(429,'PDF_BUSY','Another document is being reviewed. Try again shortly.')
        await pdf_upload_slot.acquire()
    try:
        if request.method == 'POST':
            body = bytearray()
            limit = 5_000_000 if pdf else 1_600_000 if request.url.path.endswith('/research-state') else 16384
            try:
                async with asyncio.timeout(15):
                    async for chunk in request.stream():
                        if len(body)+len(chunk) > limit:
                            return error(413, 'REQUEST_TOO_LARGE', 'Request is too large.')
                        body.extend(chunk)
            except TimeoutError:
                return error(408,'UPLOAD_TIMEOUT','The upload took too long. Try again.')
            request._body = bytes(body)
        response = await call_next(request)
    finally:
        if pdf:pdf_upload_slot.release()
    response.headers.update({'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer', 'Cache-Control': 'no-store'})
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return error(422, 'VALIDATION_ERROR', 'Please check the highlighted input fields.', {'fields': [{'field': '.'.join(map(str, e['loc'][1:])), 'message': e['msg']} for e in exc.errors()]})


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    message = exc.detail if (exc.status_code==422 or request.url.path.startswith(('/api/venture/', '/api/research-integrity/')) or request.url.path.endswith('/research-state')) and isinstance(exc.detail,str) else 'The requested route or method is unavailable.'
    return error(exc.status_code, 'HTTP_ERROR', message)


@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    return error(503, 'DATABASE_UNAVAILABLE', 'Report storage is temporarily unavailable. Try again later.')


@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    return error(500, 'INTERNAL_ERROR', 'The request could not be completed.')


@app.get('/health')
def health():
    with engine.connect() as connection:
        connection.execute(text('SELECT 1'))
    return {'status': 'ok', 'database': 'connected', 'live_serpapi_enabled': settings.live_serpapi_enabled}


@app.get('/api/search-allowance')
def search_allowance(request: Request):
    subject = user_subject(request)
    tomorrow = datetime.now(IST).date() + timedelta(days=1)
    return {'limit': 20, 'remaining': user_remaining(subject),
            'resets_at': datetime.combine(tomorrow, datetime.min.time(), tzinfo=IST).isoformat(),
            'identity': 'account' if subject.startswith('account:') else 'shared_ip',
            'shared_remaining': hosted_remaining()}


@app.get('/api/demo-status')
def novelty_demo_status():
    configured=hosted_search_configured()
    mode='unavailable';busy=True;used=0
    if configured:
        day=datetime.now(timezone.utc).date().isoformat()
        try:
            with Session() as db:
                budget=db.get(NoveltyDailyBudget,day)
                reserved=budget.calls_reserved if budget else 0;used=budget.calls_used if budget else 0
                busy=db.scalar(select(NoveltyReport.id).where(NoveltyReport.status.in_(['queued','running'])).limit(1)) or db.scalar(select(Analysis.id).where(Analysis.status.in_(['queued','running'])).limit(1)) or db.scalar(select(Signal.id).where(Signal.signal_type=='research_extension',Signal.status.in_(['queued','running'])).limit(1))
            mode='at_capacity' if busy or reserved+used+8>settings.hosted_serpapi_daily_budget-settings.hosted_serpapi_reserve else 'available'
        except SQLAlchemyError:
            mode='unavailable'
    quota_unavailable=False
    if configured:
        try:quota_unavailable=not busy and used+8>settings.hosted_serpapi_daily_budget-settings.hosted_serpapi_reserve
        except SQLAlchemyError:pass
    message={'available':'Hosted demo available','at_capacity':'Hosted demo temporarily at capacity','unavailable':'Sample mode available'}[mode]
    return {'hosted_mode':mode, 'sample_mode':True, 'personal_mode':True, 'quota_exhausted':quota_unavailable,
            'groq_mode':'available' if settings.groq_enabled and bool(settings.groq_api_key.get_secret_value()) else 'unavailable',
            'message':message}


def sample_novelty_report():
    # Purposefully synthetic: every evidence URL is example.invalid and visibly labelled.
    claims=['Crop disease inference runs on low-power phones.','Farm images remain private during model improvement.','Low-confidence predictions receive expert review.']
    papers=[{'id':'sample-paper-1','source_type':'scholar','title':'Illustrative paper: compact crop vision on mobile devices','summary_text':'Fictional sample evidence about lightweight leaf image classification on resource constrained phones. This record exists only to demonstrate the interface.','authors':['Demo author'],'source_url':'https://example.invalid/paper/mobile-crop','publication_date':'2024','citation_count':0,'versions':1,'similarity_score':71,'matched_claims':[{'claim_id':'claim-1','similarity_score':72}],'evidence_strength':50,'details':{}},
            {'id':'sample-paper-2','source_type':'scholar','title':'Illustrative paper: private agricultural model updates','summary_text':'Fictional sample evidence about sharing model updates without transferring farm photographs. No real study or result is represented.','authors':['Demo author'],'source_url':'https://example.invalid/paper/private-updates','publication_date':'2022','citation_count':0,'versions':1,'similarity_score':54,'matched_claims':[{'claim_id':'claim-2','similarity_score':61}],'evidence_strength':50,'details':{}}]
    patents=[{'id':'sample-patent-1','source_type':'patent','title':'Illustrative patent record: crop image review workflow','summary_text':'Fictional patent sample describing confidence thresholds and expert referral. Not a real patent or legal record.','source_url':'https://example.invalid/patent/review-workflow','patent_id':'SAMPLE-ONLY','priority_date':'2021','publication_date':'2023','legal_status':'Illustrative only','inventors':['Demo inventor'],'assignees':['Demo organization'],'similarity_score':43,'matched_claims':[{'claim_id':'claim-3','similarity_score':49}],'evidence_strength':40,'details':{'abstract':'Fictional interface demonstration record.','claims':['Sample only: send uncertain predictions to a reviewer.'],'classifications':[],'family':{},'citations':[]}}]
    data={'title':'Privacy-preserving crop disease detection on low-power phones','abstract':'A mobile system that detects crop disease from leaf images while keeping farm images on the device. The system uses a compact vision model, optional federated updates, and confidence-based referral when prediction certainty is low.','field':'Computer science / agriculture','keywords':['crop disease detection','on-device learning','privacy','low-power smartphone','federated learning'],'claims':claims,'earliest_year':None,'known_related_work':[]}
    report=__import__('app.analysis.novelty',fromlist=['score_report']).score_report(data,papers,patents,[],[
        {'engine':'google_scholar','query':'SYNTHETIC DEMO QUERY — not searched','timestamp':'2026-10-06T00:00:00+00:00'},
        {'engine':'google_patents','query':'SYNTHETIC DEMO QUERY — not searched','timestamp':'2026-10-06T00:00:00+00:00'}],['Sample mode: all evidence is fictional and no provider search was run.'])
    report['id']='sample'; report['credential_mode']='sample'; report['sample_mode']=True;report['is_public']=False;report['saved']=True
    report['ai_analysis']['status']='not_configured'
    report['ai_analysis']['executive_summary']='This prepared sample uses fictional evidence solely to show the report layout. It is not research evidence.'
    report['summary']['disclaimer']=DISCLAIMER
    return report


@app.get('/api/sample-report')
def get_sample_novelty_report():
    return sample_novelty_report()


@app.get('/api/novelty/analyses')
def novelty_recent():
    with Session() as db:
        rows=db.scalars(select(NoveltyReport).where(NoveltyReport.status=='complete',NoveltyReport.is_public.is_(True),NoveltyReport.saved.is_(True),NoveltyReport.created_at>=now()-timedelta(days=SAVED_REPORT_RETENTION_DAYS)).order_by(desc(NoveltyReport.created_at)).limit(20))
        return [{'id':r.id,'title':r.title,'field':r.field,'overlap_score':r.report.get('overlap_score'),'confidence_score':r.report.get('confidence_score'),'created_at':r.created_at} for r in rows]


@app.post('/api/novelty/analyses')
def create_novelty_analysis(data:NoveltyInput, request:Request, background:BackgroundTasks):
    return start_novelty_analysis(data, request, background, credentials_for(request))


def start_novelty_analysis(data, request, background, credentials, original_fingerprint=None):
    if not credentials and not hosted_search_configured():
        return error(503,'HOSTED_DEMO_UNAVAILABLE','Live analysis is not configured. Use the sample or your own provider key.')
    subject = user_subject(request) if not credentials else None
    normalized=data.model_dump(exclude={'refresh','save_report','is_public'})
    # Unlisted requests never disclose another user's cached report or queued ID.
    fingerprint=original_fingerprint or hashlib.sha256(json.dumps({'input':normalized,'is_public':data.is_public,
        'save_report':data.save_report,'mode':'personal' if credentials else 'hosted',
        'scope':secrets.token_hex(16) if not data.is_public or credentials else 'public'},sort_keys=True).encode()).hexdigest()
    address=request.client.host if request.client else 'unknown'
    ip_hash=hmac.new(settings.ip_hash_secret.get_secret_value().encode() or salt,address.encode(),hashlib.sha256).hexdigest()
    day=datetime.now(timezone.utc).date().isoformat()
    tokens={}
    with research_lock, Session.begin() as db:
        cleanup_expired_reports(db)
        oldest_day=(now()-timedelta(days=7)).date().isoformat()
        db.execute(delete(NoveltyUsage).where(NoveltyUsage.day_utc<oldest_day))
        db.execute(delete(NoveltyDailyBudget).where(NoveltyDailyBudget.day_utc<oldest_day))
        if data.is_public and not credentials and not data.refresh:
            previous=db.scalar(select(NoveltyReport).where(NoveltyReport.fingerprint==fingerprint,NoveltyReport.is_public.is_(True),NoveltyReport.status=='complete',NoveltyReport.saved.is_(True)).order_by(desc(NoveltyReport.created_at)))
            if previous and (previous.created_at.replace(tzinfo=previous.created_at.tzinfo or timezone.utc)) >= now()-timedelta(hours=24):
                return {'id':previous.id,'status':'complete','cached':True,'report_url':f'/reports/{previous.id}'}
        if db.scalar(select(NoveltyReport.id).where(NoveltyReport.status.in_(['queued','running'])).limit(1)) or db.scalar(select(Analysis.id).where(Analysis.status.in_(['queued','running'])).limit(1)) or db.scalar(select(Signal.id).where(Signal.signal_type=='research_extension',Signal.status.in_(['queued','running'])).limit(1)):
            return error(429,'SERVER_BUSY','Another analysis is running. Try again shortly.')
        if credentials:
            key='personal:'+ip_hash
            current=time.monotonic()
            while hits[key] and current-hits[key][0]>=3600:hits[key].popleft()
            if len(hits[key])>=settings.rate_limit_per_hour:
                return error(429,'RATE_LIMIT','Personal search limit reached. Try again in one hour.')
        else:
            if user_remaining(subject) < 1:
                return error(429,'DAILY_USER_LIMIT','Your 20 daily searches are used. Enter your own SerpApi key or wait until midnight IST.')
        budget=None
        if not credentials:
            budget=db.get(NoveltyDailyBudget,day)
            if budget is None:
                budget=NoveltyDailyBudget(day_utc=day,calls_reserved=0,calls_used=0);db.add(budget);db.flush()
            available=max(0,settings.hosted_serpapi_daily_budget-settings.hosted_serpapi_reserve)
            if budget.calls_reserved+budget.calls_used+8>available:
                return error(429,'SHARED_QUOTA_EXHAUSTED','The shared daily allowance cannot fund another report. Use your own keys or wait for the UTC reset.')
        row=NoveltyReport(fingerprint=fingerprint,title=normalized['title'],field=normalized.get('field',''),input_data=normalized,status='queued',saved=data.save_report,is_public=data.is_public)
        db.add(row);db.flush();ident=row.id
        if row.saved and not row.is_public:
            owner=secrets.token_urlsafe(32);reviewer=secrets.token_urlsafe(32)
            db.add(NoveltyWorkspace(report_id=ident,owner_token_hash=hashlib.sha256(owner.encode()).hexdigest(),review_token_hash=hashlib.sha256(reviewer.encode()).hexdigest(),comments=[],watched=False))
            tokens={'owner_token':owner,'review_token':reviewer}
        db.add(NoveltyUsage(day_utc=day,ip_hash=ip_hash,analysis_id=ident,calls_reserved=0 if credentials else 8,calls_used=0,status='reserved'))
        if budget:budget.calls_reserved+=8
        if credentials:hits[key].append(current)
    background.add_task(run_novelty_job,ident,credentials,subject)
    ai_mode='enabled' if (bool(credentials.groq.get_secret_value()) if credentials else settings.groq_enabled and bool(settings.groq_api_key.get_secret_value())) else 'unavailable'
    return JSONResponse(status_code=202,content={'id':ident,'status':'queued','cached':False,'credential_mode':'personal' if credentials else 'hosted','ai_enrichment':ai_mode,'report_url':f'/reports/{ident}',**tokens})


@app.post('/api/novelty/analyses/{analysis_id}/refresh')
def refresh_novelty_analysis(analysis_id:UUID, request:Request, background:BackgroundTasks, options:RefreshOptions|None=None):
    with Session() as db:
        row=db.get(NoveltyReport,str(analysis_id))
        if not novelty_report_current(row) or not row.saved:
            return error(404,'NOT_FOUND','A saved completed report is required.')
        workspace=db.get(NoveltyWorkspace,str(analysis_id))
        if not workspace or not owner_authorized(request,workspace):
            return error(403,'OWNER_LINK_REQUIRED','Open the owner workspace link to refresh this watched report.')
        original=deepcopy(row.input_data)
        if options and options.use_groq is not None:original['use_groq']=options.use_groq
        original['save_report']=row.saved
        original['is_public']=row.is_public
        fingerprint=row.fingerprint
        personal=row.report.get('credential_mode')=='personal'
    credentials=credentials_for(request)
    if personal and not credentials:
        return error(409,'PERSONAL_KEYS_REQUIRED','Re-enter your personal keys to refresh this report.')
    return start_novelty_analysis(NoveltyInput(**original,refresh=True),request,background,credentials,fingerprint)


@app.get('/api/novelty/analyses/{analysis_id}')
def get_novelty_analysis(analysis_id:UUID):
    with Session.begin() as db:
        row=db.get(NoveltyReport,str(analysis_id))
        if not row:return error(404,'NOT_FOUND','This report was not found.')
        retention=timedelta(days=SAVED_REPORT_RETENTION_DAYS) if row.saved else timedelta(hours=1)
        created=row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=timezone.utc)
        if created<now()-retention:
            db.delete(row)
            db.execute(delete(NoveltyWorkspace).where(NoveltyWorkspace.report_id==str(analysis_id)))
            return error(404,'NOT_FOUND','This report has expired.')
        if row.status=='complete':return row.report
        return {'id':row.id,'status':row.status,'stage':row.stage,'progress':row.progress,'error_message':row.error_message}


@app.post('/api/novelty/analyses/{analysis_id}/revision-preview')
def novelty_revision_preview(analysis_id:UUID, revision:RevisionInput):
    with Session() as db:
        row=db.get(NoveltyReport,str(analysis_id))
        if not novelty_report_current(row):
            return error(404,'NOT_FOUND','A completed report is required.')
        source=deepcopy(row.report)
    return make_revision_preview(source,revision,str(analysis_id))


@app.post('/api/sample-report/revision-preview')
def sample_revision_preview(revision:RevisionInput):
    return make_revision_preview(sample_novelty_report(),revision,'sample')


def make_revision_preview(source,revision,baseline_id):
    data={**source['input'], **revision.model_dump()}
    candidate=score_report(data,deepcopy(source['papers']),deepcopy(source['patents']),deepcopy(source['web_results']),
                           source['queries'],source['warnings'])
    old_claims={claim['text']:claim['coverage_score'] for claim in source['claims']}
    return {'baseline_id':baseline_id,'baseline_overlap':source['overlap_score'],
            'preview_overlap':candidate['overlap_score'],'delta':candidate['overlap_score']-source['overlap_score'],
            'claim_comparison':[{'claim':claim['text'],'previous_coverage':old_claims.get(claim['text']),
                                 'preview_coverage':claim['coverage_score']} for claim in candidate['claims']],
            'guidance':candidate['research_guidance'],
            'limitation':'This preview rescored the original retrieved snippets. It did not search for new work; lower overlap is not proof of a stronger contribution.'}


@app.get('/api/novelty/analyses/{analysis_id}/brief')
def novelty_contribution_brief(analysis_id:UUID):
    with Session() as db:
        row=db.get(NoveltyReport,str(analysis_id))
        if not novelty_report_current(row):
            return error(404,'NOT_FOUND','A completed report is required.')
        return contribution_brief(row.report)


@app.post('/api/novelty/analyses/{analysis_id}/document-review')
async def novelty_document_review(analysis_id:UUID, request:Request):
    with Session() as db:
        row=db.get(NoveltyReport,str(analysis_id))
        if not novelty_report_current(row):
            return error(404,'NOT_FOUND','A completed report is required.')
        claims=deepcopy(row.report['claims'])
    return await extract_document_review(request,claims)


@app.post('/api/sample-report/document-review')
async def sample_document_review(request:Request):
    return await extract_document_review(request,sample_novelty_report()['claims'])


async def extract_document_review(request,claims):
    if request.headers.get('content-type','').split(';')[0].strip() != 'application/pdf':
        return error(415,'PDF_REQUIRED','Upload a PDF file.')
    raw=await request.body()
    if not raw.startswith(b'%PDF-') or len(raw)>5_000_000:
        return error(422,'INVALID_PDF','Choose a PDF smaller than 5 MB.')
    try:
        document=await extract_pdf(raw)
        passages=document['passages']
        results=[]
        for claim in claims:
            ranked=sorted(({**passage,'similarity':round(cosine(claim['text'],passage['text'])*100)} for passage in passages),
                          key=lambda passage:passage['similarity'],reverse=True)
            results.append({'claim_id':claim['id'],'claim':claim['text'],'passages':[p for p in ranked[:3] if p['similarity']>=10]})
        return {'page_count':document['page_count'],'pages_checked':min(30,document['page_count']),
                'claims':results,'limitation':'Extracted PDF text may omit figures, tables, or scanned pages. Verify every passage in the original document. The uploaded PDF is not saved.'}
    except PdfBusy:
        return error(429,'PDF_BUSY','Another document is being reviewed. Try again shortly.')
    except PdfUnavailable:
        return error(503,'PDF_WORKER_UNAVAILABLE','PDF review requires the Linux backend worker. Use the hosted app for document review.')
    except Exception:
        return error(422,'PDF_EXTRACTION_FAILED','Text extraction failed or exceeded its resource limit. Choose a simpler, unlocked PDF.')


def review_authorized(request, workspace):
    supplied=request.headers.get('X-Review-Token','')
    if not supplied or len(supplied)>200:return False
    digest=hashlib.sha256(supplied.encode()).hexdigest()
    return hmac.compare_digest(digest,workspace.review_token_hash) or hmac.compare_digest(digest,workspace.owner_token_hash)


def owner_authorized(request,workspace):
    supplied=request.headers.get('X-Review-Token','')
    return bool(supplied) and len(supplied)<=200 and hmac.compare_digest(hashlib.sha256(supplied.encode()).hexdigest(),workspace.owner_token_hash)


def workspace_view(db, report, workspace):
    latest=db.scalar(select(NoveltyReport).where(NoveltyReport.fingerprint==report.fingerprint,
        NoveltyReport.status=='complete', NoveltyReport.created_at>report.created_at)
        .order_by(desc(NoveltyReport.created_at)).limit(1)) if workspace.watched else None
    alerts=[]
    if latest and latest.report:
        for key,label in (('papers','paper'),('patents','patent')):
            old={item.get('source_url') or item['title'].casefold() for item in report.report[key]}
            for item in latest.report[key]:
                if (item.get('source_url') or item['title'].casefold()) not in old:
                    alerts.append({'kind':f'newly_retrieved_{label}','title':item['title'],'source_url':item.get('source_url'),'report_id':latest.id})
        if abs(latest.report['overlap_score']-report.report['overlap_score'])>=5:
            alerts.append({'kind':'overlap_change','title':f"Search overlap changed from {report.report['overlap_score']} to {latest.report['overlap_score']}",
                           'report_id':latest.id})
    return {'comments':workspace.comments or [],'watched':workspace.watched,
            'latest_report_id':latest.id if latest else None,'alerts':alerts[:20]}


@app.post('/api/novelty/analyses/{analysis_id}/workspace')
def create_novelty_workspace(analysis_id:UUID):
    return error(403,'OWNER_LINK_REQUIRED','Owner credentials are issued only when the report is created. An ordinary report link cannot create or claim a workspace.')


@app.post('/api/novelty/analyses/{analysis_id}/workspace/rotate')
def rotate_workspace(analysis_id:UUID, request:Request):
    with Session.begin() as db:
        report=db.get(NoveltyReport,str(analysis_id))
        workspace=db.scalar(select(NoveltyWorkspace).where(NoveltyWorkspace.report_id==str(analysis_id)).with_for_update())
        if not novelty_report_current(report) or not workspace or not owner_authorized(request,workspace):
            return error(403,'OWNER_LINK_REQUIRED','Only the current owner may replace workspace links.')
        owner=secrets.token_urlsafe(32);reviewer=secrets.token_urlsafe(32)
        changed=db.execute(update(NoveltyWorkspace).where(NoveltyWorkspace.report_id==str(analysis_id),NoveltyWorkspace.owner_token_hash==workspace.owner_token_hash).values(
            owner_token_hash=hashlib.sha256(owner.encode()).hexdigest(),review_token_hash=hashlib.sha256(reviewer.encode()).hexdigest()))
        if changed.rowcount!=1:return error(409,'WORKSPACE_CHANGED','Another owner replaced these links. Reload before continuing.')
        return {'owner_token':owner,'review_token':reviewer,'workspace':workspace_view(db,report,workspace)}


@app.get('/api/novelty/analyses/{analysis_id}/workspace')
def get_novelty_workspace(analysis_id:UUID, request:Request):
    with Session() as db:
        report=db.get(NoveltyReport,str(analysis_id));workspace=db.get(NoveltyWorkspace,str(analysis_id))
        if not novelty_report_current(report) or not workspace:
            return error(404,'NOT_FOUND','No review workspace exists for this report.')
        if not review_authorized(request,workspace):
            return error(403,'REVIEW_LINK_REQUIRED','Open the owner or reviewer link to read feedback.')
        return workspace_view(db,report,workspace)


@app.post('/api/novelty/analyses/{analysis_id}/workspace/comments')
def add_novelty_comment(analysis_id:UUID, item:ReviewCommentInput, request:Request):
    with Session.begin() as db:
        report=db.get(NoveltyReport,str(analysis_id));workspace=db.get(NoveltyWorkspace,str(analysis_id))
        if not novelty_report_current(report) or not workspace or not review_authorized(request,workspace):
            return error(403,'REVIEW_LINK_REQUIRED','Open the review invite link to add feedback.')
        if item.claim_id and item.claim_id not in {claim['id'] for claim in report.report['claims']}:
            return error(422,'UNKNOWN_CLAIM','Select a claim from this report.')
        cleaned_url=safe_url(item.source_url) if item.source_url else None
        if item.source_url and not cleaned_url:
            return error(422,'INVALID_LINK','Source links must use HTTP or HTTPS.')
        comments=list(workspace.comments or [])
        if len(comments)>=100:return error(429,'REVIEW_LIMIT','This workspace has reached its feedback limit.')
        comments.append({'id':secrets.token_hex(8),'author':item.author.strip(),'claim_id':item.claim_id,
                         'kind':item.kind,'text':item.text.strip(),'source_url':cleaned_url,
                         'created_at':now().isoformat()})
        changed=db.execute(update(NoveltyWorkspace).where(NoveltyWorkspace.report_id==str(analysis_id),NoveltyWorkspace.comments==workspace.comments,NoveltyWorkspace.owner_token_hash==workspace.owner_token_hash,NoveltyWorkspace.review_token_hash==workspace.review_token_hash).values(comments=comments))
        if changed.rowcount!=1:return error(409,'WORKSPACE_CHANGED','Feedback changed. Reload before saving your comment.')
        return {'comments':comments}


@app.post('/api/novelty/analyses/{analysis_id}/workspace/watch')
def set_novelty_watch(analysis_id:UUID, item:WatchInput, request:Request):
    with Session.begin() as db:
        report=db.get(NoveltyReport,str(analysis_id));workspace=db.get(NoveltyWorkspace,str(analysis_id))
        if not novelty_report_current(report) or not workspace or not owner_authorized(request,workspace):
            return error(403,'OWNER_LINK_REQUIRED','Open the owner workspace link to change watch settings.')
        changed=db.execute(update(NoveltyWorkspace).where(NoveltyWorkspace.report_id==str(analysis_id),NoveltyWorkspace.owner_token_hash==workspace.owner_token_hash).values(watched=item.watched))
        if changed.rowcount!=1:return error(403,'OWNER_LINK_REQUIRED','The owner link was replaced. Open the current link.')
        db.refresh(workspace)
        return workspace_view(db,report,workspace)


@app.post('/api/analyses')
def create_analysis(data: AnalysisInput, request: Request, background: BackgroundTasks):
    credentials=credentials_for(request)
    subject=user_subject(request) if settings.live_serpapi_enabled and not credentials else None
    # Keep demo data attached to its actual synthetic scenario, never arbitrary markets.
    if not settings.live_serpapi_enabled and not credentials and (data.business_category.casefold() != 'coworking space' or data.city.casefold() != 'pune' or data.country != 'India' or {k.casefold() for k in data.keywords} != {'coworking pune', 'shared office pune', 'flexible office pune'}):
        return error(422, 'FIXTURE_SCENARIO_ONLY', 'Sample mode supports the Pune coworking example. Enable live search on the backend for other markets.')
    fingerprint = data.fingerprint(settings.live_serpapi_enabled or bool(credentials))
    if credentials:fingerprint=hashlib.sha256((fingerprint+secrets.token_hex(16)).encode()).hexdigest()
    with research_lock, Session() as db:
        running = active(db, fingerprint)
        if running:
            return error(409, 'ANALYSIS_RUNNING', 'This analysis is already running.', {'id': running.id, 'report_url': f'/reports/{running.id}'})
        previous = cached(db, fingerprint) if not data.refresh else None
        if previous:
            return {'id': previous.id, 'status': 'complete', 'cached': True, 'report_url': f'/reports/{previous.id}'}
        if subject and user_remaining(subject)<1:
            return error(429,'DAILY_USER_LIMIT','Your 20 daily searches are used. Enter your own SerpApi key or wait until midnight IST.')
        if not credentials and settings.live_serpapi_enabled and hosted_remaining()<1:
            return error(429,'SHARED_QUOTA_EXHAUSTED','Shared search allowance exhausted. Use your own keys or wait for the UTC reset.')
        current = time.monotonic()
        for key in list(hits):
            while hits[key] and current - hits[key][0] >= 3600:
                hits[key].popleft()
            if not hits[key]:
                del hits[key]
        key = hashlib.sha256(salt + (request.client.host if request.client else 'unknown').encode()).hexdigest()
        if len(hits[key]) >= settings.rate_limit_per_hour:
            return error(429, 'RATE_LIMIT', 'Analysis limit reached. Try again in one hour.')
        if db.scalar(select(NoveltyReport.id).where(NoveltyReport.status.in_(['queued','running'])).limit(1)) or db.scalar(select(Analysis).where(Analysis.status.in_(['queued', 'running'])).limit(1)) or db.scalar(select(Signal.id).where(Signal.signal_type=='research_extension',Signal.status.in_(['queued','running'])).limit(1)):
            return error(429, 'SERVER_BUSY', 'Another report is running. Please try again shortly.')
        row = Analysis(fingerprint=fingerprint, **data.model_dump(exclude={'refresh', 'options'}))
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            running = active(db, fingerprint)
            return error(409, 'ANALYSIS_RUNNING', 'This analysis is already running.', {'id': running.id} if running else {})
        hits[key].append(current)
        background.add_task(run_job, row.id, data, credentials, subject)
        return JSONResponse(status_code=202, content={'id': row.id, 'status': 'queued', 'cached': False, 'report_url': f'/reports/{row.id}'})


@app.get('/api/analyses')
def recent():
    with Session() as db:
        rows = db.scalars(select(Analysis).where(Analysis.status == 'complete').order_by(Analysis.completed_at.desc()).limit(20))
        return [{'id': r.id, 'business_category': r.business_category, 'city': r.city, 'country': r.country, 'overall_score': r.overall_score, 'confidence_score': r.confidence_score, 'interpretation': r.interpretation, 'created_at': r.created_at, 'data_mode': r.report['data_mode']} for r in rows]


@app.get('/api/analyses/{analysis_id}')
def get_analysis(analysis_id: UUID):
    with Session() as db:
        row = db.get(Analysis, str(analysis_id))
        if not row:
            return error(404, 'NOT_FOUND', 'This report was not found.')
        if row.status == 'complete':
            return row.report
        return {'id': row.id, 'status': row.status, 'stage': row.stage, 'progress': row.progress, 'warnings': row.warnings, 'sections': row.sections, 'error_message': row.error_message, 'search_usage': (row.report or {}).get('search_usage')}


@app.post('/api/analyses/{analysis_id}/relevance')
def review_relevance(analysis_id: UUID, changes: RelevanceInput, request: Request):
    with Session.begin() as db:
        original = db.get(Analysis, str(analysis_id))
        if not original or original.status != 'complete':
            return error(404, 'NOT_FOUND', 'A completed source report is required.')
        normalized = {'competitor_ranks':sorted(set(changes.competitor_ranks)), 'news_indices':sorted(set(changes.news_indices)), 'reason':changes.reason}
        fingerprint = hashlib.sha256((str(analysis_id)+json.dumps(normalized,sort_keys=True)).encode()).hexdigest()
        previous = db.scalar(select(Analysis).where(Analysis.fingerprint==fingerprint,Analysis.status=='complete'))
        if previous:
            return {'id':previous.id,'report_url':f'/reports/{previous.id}'}
        key = hashlib.sha256(salt + (request.client.host if request.client else 'unknown').encode()).hexdigest()
        current = time.monotonic()
        while hits[key] and current-hits[key][0] >= 3600:
            hits[key].popleft()
        if len(hits[key]) >= settings.rate_limit_per_hour:
            return error(429,'RATE_LIMIT','Analysis limit reached. Try again in one hour.')
        samples = original.report.get('sampled_reviews')
        if samples is None:
            signal = db.scalar(select(Signal).where(Signal.analysis_id==original.id,Signal.signal_type=='reviews'))
            if not signal:
                return error(409,'MISSING_EVIDENCE','This older report lacks review inputs for safe recalculation. Create a fresh analysis.')
            samples = signal.payload['items']
        revision_id = uid()
        try:
            revised = revise_report(original.report,changes,samples,revision_id,now().isoformat())
        except ValueError as exc:
            return error(422,'INVALID_EXCLUSION',str(exc))
        row = Analysis(id=revision_id,fingerprint=fingerprint,**{k:getattr(original,k) for k in ('business_category','city','country','keywords','known_competitors')},
                       status='complete',stage='complete',progress=100,completed_at=now(),report=revised,
                       **{k:revised[k] for k in ('overall_score','confidence_score','interpretation','recommendation','component_scores','warnings','sections','methodology_version')})
        db.add(row)
        hits[key].append(current)
        return {'id':revision_id,'report_url':f'/reports/{revision_id}'}


@app.get('/api/analyses/{analysis_id}/stress')
def get_stress_test(analysis_id: UUID):
    with Session() as db:
        row = db.get(Analysis, str(analysis_id))
        if not row or row.status != 'complete':
            return error(404, 'NOT_FOUND', 'A completed report is required.')
        if row.report.get('methodology_version') != '1.0':
            return error(409, 'UNSUPPORTED_METHOD', 'This scoring version does not support stress testing.')
        samples = row.report.get('sampled_reviews')
        if samples is None:
            signal = db.scalar(select(Signal).where(Signal.analysis_id == row.id, Signal.signal_type == 'reviews'))
            if not signal:
                return error(409, 'MISSING_EVIDENCE', 'This older report lacks review inputs. Create a fresh analysis.')
            samples = signal.payload['items']
        return stress_test(row.report, samples)


def research_summary(row):
    created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=timezone.utc)
    return {'id':row.id,'status':row.status,'tool':row.payload['tool'],'created_at':created,
            'input':row.payload['input'],'data_mode':row.payload['data_mode']}


@app.get('/api/analyses/{analysis_id}/research')
def list_research(analysis_id: UUID):
    with Session() as db:
        results = db.scalars(select(Signal).where(Signal.analysis_id==str(analysis_id),Signal.signal_type=='research_extension').order_by(Signal.created_at.desc()).limit(50))
        return [research_summary(row) for row in results]


@app.get('/api/analyses/{analysis_id}/research/{job_id}')
def get_research(analysis_id: UUID, job_id: UUID):
    with Session() as db:
        row = db.get(Signal,str(job_id))
        if not row or row.analysis_id != str(analysis_id) or row.signal_type != 'research_extension':
            return error(404,'NOT_FOUND','Research run not found for this report.')
        return {**research_summary(row),**row.payload}


@app.post('/api/analyses/{analysis_id}/research')
def create_research(analysis_id: UUID, data: ResearchInput, request: Request, background: BackgroundTasks):
    credentials=credentials_for(request)
    with research_lock, Session.begin() as db:
        report = db.get(Analysis,str(analysis_id))
        if not report or report.status != 'complete':
            return error(404,'NOT_FOUND','A completed report is required.')
        mode = 'live' if credentials else report.report['data_mode']
        if report.report.get('credential_mode')=='personal' and not credentials:
            return error(409,'PERSONAL_KEYS_REQUIRED','Re-enter your keys to search from this personal report.')
        if mode == 'live' and not settings.live_serpapi_enabled and not credentials:
            return error(409,'LIVE_DISABLED','Live searches are disabled. Enable them before researching a live report.')
        try:
            plans = plan_requests(data,report.report)
        except ValueError as exc:
            return error(422,'INVALID_RESEARCH',str(exc))
        canonical = data.canonical()
        fingerprint = hashlib.sha256(json.dumps({'report':str(analysis_id),'input':canonical,'version':1,'mode':mode},sort_keys=True).encode()).hexdigest()
        recent = db.scalars(select(Signal).where(Signal.analysis_id==report.id,Signal.signal_type=='research_extension',Signal.created_at >= now()-timedelta(hours=1)).order_by(Signal.created_at.desc())).all()
        for previous in ([] if credentials else recent):
            if previous.payload.get('credential_mode')!='personal' and previous.payload.get('fingerprint') == fingerprint and (previous.status in ('queued','running') or (previous.status == 'complete' and not data.refresh)):
                return {'id':previous.id,'cached':previous.status=='complete'}
        if db.scalar(select(NoveltyReport.id).where(NoveltyReport.status.in_(['queued','running'])).limit(1)) or db.scalar(select(Signal.id).where(Signal.signal_type=='research_extension',Signal.status.in_(['queued','running'])).limit(1)) or db.scalar(select(Analysis.id).where(Analysis.status.in_(['queued','running'])).limit(1)):
            return error(429,'SERVER_BUSY','Another search is running. Open its saved run or try again shortly.')
        subject=user_subject(request) if mode=='live' and not credentials else None
        if subject and user_remaining(subject)<1:
            return error(429,'DAILY_USER_LIMIT','Your 20 daily searches are used. Enter your own SerpApi key or wait until midnight IST.')
        if mode=='live' and not credentials and hosted_remaining()<1:
            return error(429,'SHARED_QUOTA_EXHAUSTED','Shared search allowance exhausted. Use your own keys or wait for the UTC reset.')
        current = time.monotonic()
        for key in list(hits):
            while hits[key] and current-hits[key][0] >= 3600:
                hits[key].popleft()
            if not hits[key]:
                del hits[key]
        key = hashlib.sha256(salt+(request.client.host if request.client else 'unknown').encode()).hexdigest()
        if len(hits[key]) >= settings.rate_limit_per_hour:
            return error(429,'RATE_LIMIT','Search-run limit reached. Try again in one hour.')
        payload = {'tool':data.tool,'input':canonical,'data_mode':mode,'credential_mode':'personal' if credentials else 'hosted','fingerprint':fingerprint,'planned_requests':len(plans),
                   'completed_requests':0,'batches':[], 'usage':{'mode':mode,'logical_requests':{},'provider_attempts':{},'total_requests':0,'total_provider_attempts':0,'billing_note':'Requests are not confirmed billable credits.'},
                   'sample_notice':'Fixed synthetic examples for interface testing; they do not answer custom searches.' if mode=='fixture' else ''}
        row = Signal(analysis_id=report.id,engine=ENGINES[data.tool],signal_type='research_extension',status='queued',payload=payload)
        db.add(row)
        db.flush()
        hits[key].append(current)
        background.add_task(run_research,row.id,data.tool,plans,mode,payload,credentials,subject)
        return {'id':row.id,'cached':False}
