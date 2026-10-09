import asyncio
import logging
from urllib.parse import urlsplit, urlencode
from app.db.session import Session
from app.models.database import Analysis, Competitor, Signal, Evidence, now, uid
from app.models.schemas import AnalysisInput, Report
from app.errors import EngineError, MESSAGES
from app.serpapi_clients.base import SearchClient
from app.serpapi_clients import maps, reviews, trends, news, ads
from app.analysis.scoring import score
from app.analysis.recommendations import RuleBasedAnalyzer
from app.analysis.topics import review_matrix
from app.analysis.reputation import compare_reviews

logger = logging.getLogger('market.jobs')
ENGINES = {'maps': 'google_maps', 'reviews': 'google_maps_reviews', 'trends': 'google_trends', 'news': 'google_news', 'ads': 'google_ads_transparency_center'}


async def run_job(analysis_id, request: AnalysisInput, credentials=None, subject=None):
    client = SearchClient(credentials=credentials, subject=subject)
    sections = {k: {'status': 'pending', 'count': 0} for k in ENGINES}
    warnings = [] if client.live else ['Sample report: all observations are synthetic fixtures, not live market evidence. Fixture data describes only the Pune coworking example.']

    def update(stage, progress):
        with Session.begin() as db:
            row = db.get(Analysis, analysis_id)
            row.status, row.stage, row.progress = 'running', stage, progress
            row.sections, row.warnings = dict(sections), list(warnings)

    async def collect(key, call):
        sections[key]['status'] = 'running'
        try:
            values = await call
            sections[key] = {'status': 'complete' if values else 'empty', 'count': len(values)}
            if not values:
                warnings.append(f'{key.title()}: insufficient data; no results returned.')
            return values
        except EngineError as e:
            sections[key] = {'status': 'failed', 'count': 0, 'message': MESSAGES[e.code]}
            if e.code == 'AUTH_ERROR' or key == 'maps':
                raise
            warnings.append(f'{key.title()}: {MESSAGES[e.code]}')
            return []
        except Exception:
            if key == 'maps':
                raise EngineError() from None
            sections[key] = {'status': 'failed', 'count': 0, 'message': MESSAGES['INVALID_RESPONSE']}
            warnings.append(f'{key.title()}: {MESSAGES["INVALID_RESPONSE"]}')
            return []

    try:
        sections['maps']['status'] = 'running'
        update('maps', 5)
        places = await collect('maps', maps.fetch(client, request))
        selected = sorted([p for p in places if p['data_id']], key=lambda p: p['review_count'] * (p['rating'] or 0), reverse=True)[:3]
        sections['reviews']['status'] = 'running' if selected else 'skipped'
        sections['trends']['status'] = sections['news']['status'] = 'running'
        update('reviews', 25)

        async def review_group():
            results = await asyncio.gather(*(reviews.fetch(client, p) for p in selected), return_exceptions=True)
            rows, failures = [], []
            for r in results:
                if isinstance(r, EngineError) and r.code == 'AUTH_ERROR':
                    raise r
                if isinstance(r, Exception):
                    failures.append(r)
                else:
                    rows.extend(r)
            if failures:
                sections['reviews'] = {'status': 'failed', 'count': len(rows), 'message': 'Some review requests failed; available excerpts are preserved. Score uses neutral 50.'}
                warnings.append(sections['reviews']['message'])
            else:
                sections['reviews'] = {'status': 'complete' if rows else 'empty' if selected else 'skipped', 'count': len(rows)}
            return rows

        async def with_progress(key, call):
            result = await call
            done = sum(sections[k]['status'] not in ('pending', 'running') for k in ('reviews', 'trends', 'news'))
            update(key, 25 + done * 15)
            return result

        collected = await asyncio.gather(
            with_progress('reviews', review_group()),
            with_progress('trends', collect('trends', trends.fetch(client, request))),
            with_progress('news', collect('news', news.fetch(client, request))), return_exceptions=True)
        # Drain all concurrent work before persisting a terminal state. Otherwise a
        # late progress update can overwrite a failed job with running status.
        for value in collected:
            if isinstance(value, Exception):
                raise value
        samples, series, articles = collected
        if len(samples) < 6:
            warnings.append('Low review sample size: fewer than six reviews. This sample does not represent all customers.')
        sections['ads']['status'] = 'running'
        update('ads', 70)
        targets = list(request.known_competitors)
        for p in places:
            if p['website']:
                host = urlsplit(p['website']).hostname
                if host and host.removeprefix('www.') not in targets:
                    targets.append(host.removeprefix('www.'))
        targets = targets[:3]
        if not request.options.ads:
            targets = []
        advertising = []
        failures = False
        for target in targets:
            if client.halted:
                failures = True
                warnings.append('Ads: Search allowance unavailable')
                break
            try:
                advertising.extend(await ads.fetch(client, target))
            except EngineError as e:
                if e.code == 'AUTH_ERROR':
                    raise
                failures = True
                warnings.append(f'Ads: {MESSAGES[e.code]}')
        advertising = list({(a['advertiser_id'], a['creative_id']): a for a in advertising}.values())
        sections['ads'] = {'status': 'failed' if failures else 'complete' if advertising else 'unavailable' if targets else 'skipped', 'count': len(advertising)}
        if not advertising:
            warnings.append('Advertising: no reliable active match. Neutral 50 does not imply an absence of advertising.')
        async def extra(key, call):
            if not getattr(request.options, key):
                sections[key] = {'status': 'skipped', 'count': 0, 'message': 'Not requested in search planner.'}
                return []
            try:
                values = await call()
                sections[key] = {'status': 'complete' if values else 'empty', 'count': len(values)}
                return values
            except Exception:
                sections[key] = {'status': 'unavailable', 'count': 0, 'message': 'Optional research data could not be retrieved.'}
                warnings.append(f'{key.title()}: optional research data unavailable; completed sections are preserved.')
                return []

        sections['keywords'] = {'status': 'running', 'count': 0}
        sections['seasonality'] = {'status': 'running', 'count': 0}
        update('research', 85)
        related, history = await asyncio.gather(
            extra('keywords', lambda: trends.related_queries(client, request)),
            extra('seasonality', lambda: trends.seasonality(client, request)))
        reputation = []
        sections['hours'] = {'status': 'running' if request.options.hours else 'skipped', 'count': 0}
        sections['reputation'] = {'status': 'running' if request.options.reputation else 'skipped', 'count': 0}
        update('research', 87)
        hours_failed = history_failed = False
        for place in selected:
            if request.options.hours and not place.get('operating_hours'):
                try:
                    place['operating_hours'] = await maps.fetch_hours(client, place)
                except Exception:
                    hours_failed = True
            if request.options.reputation:
                status, additional = 'complete', []
                try:
                    additional = await reviews.history(client, place)
                except Exception:
                    history_failed, status = True, 'unavailable'
                own = [r for r in samples if r['data_id'] == place['data_id']]
                reputation.append(compare_reviews(place, own + additional, now(), status))
        if request.options.hours:
            count = sum(bool(p.get('operating_hours')) for p in places)
            sections['hours'] = {'status': 'partial' if hours_failed else 'complete' if count else 'empty', 'count': count}
        if request.options.reputation:
            sections['reputation'] = {'status': 'partial' if history_failed else 'complete' if reputation else 'empty', 'count': len(reputation)}
        if hours_failed or history_failed:
            warnings.append('Some hours or review-history requests failed. Available observations are preserved.')
        update('scoring', 90)
        result = score(places, series, samples, articles, advertising, sections)
        if not result['methodology']['components']['demand']['keywords']:
            sections['trends']['status'] = 'unavailable' if sections['trends']['status'] == 'complete' else sections['trends']['status']
        if not result['methodology']['components']['advertising_gap']['active_advertisers'] and sections['ads']['status'] == 'complete':
            sections['ads']['status'] = 'unavailable'
        recommendation = RuleBasedAnalyzer().recommend(result, sections, articles)
        evidence = []
        for key, rows in [('maps', places), ('reviews', samples), ('news', articles), ('ads', advertising)]:
            for item in rows:
                evidence.append(dict(id=uid(), engine=ENGINES[key], evidence_type=key,
                                     title=item.get('title') or item.get('name') or item.get('competitor') or item.get('advertiser'),
                                     snippet=item.get('text') or item.get('snippet'), source_name=item.get('source') or ENGINES[key],
                                     source_url=item.get('source_url'), published_at=item.get('published_at') or item.get('last_shown'),
                                     data_id=item.get('data_id')))
        if series:
            evidence.append(dict(id=uid(), engine=ENGINES['trends'], evidence_type='trends', title='Google Trends keyword comparison', snippet=None, source_name='Google Trends',
                                 source_url='https://trends.google.com/trends/explore?' + urlencode({'q': ','.join(request.keywords), 'geo': request.country_code, 'date': 'today 12-m'}), published_at=None))
        for key, values, title, query, period in [
            ('keywords', related, 'Related queries for ' + request.keywords[0], request.keywords[0], 'today 12-m'),
            ('seasonality', history, 'Five-year Google Trends history', ','.join(request.keywords), 'today 5-y')]:
            if values:
                evidence.append(dict(id=uid(), engine='google_trends', evidence_type=key, title=title, snippet=None,
                                     source_name='Google Trends', source_url='https://trends.google.com/trends/explore?' + urlencode({'q': query, 'geo': request.country_code, 'date': period}), published_at=None))
        with Session.begin() as db:
            row = db.get(Analysis, analysis_id)
            report = Report(id=analysis_id, status='complete', input=request.model_dump(exclude={'refresh'}), **result,
                            recommendation=recommendation, competitors=places, trend_series=series, related_queries=related,
                            seasonality_series=history, review_matrix=review_matrix(samples), news=articles, advertising=advertising,
                            sampled_reviews=samples, reputation=reputation, search_usage=client.usage(),
                            evidence=evidence, warnings=warnings, methodology_version='1.0', sections=sections,
                            data_mode='live' if client.live else 'fixture', credential_mode='personal' if credentials else 'hosted', created_at=row.created_at.replace(tzinfo=row.created_at.tzinfo or now().tzinfo).isoformat()).model_dump()
            ids = {}
            for place in places:
                record = Competitor(id=uid(), analysis_id=analysis_id, serpapi_data_id=place['data_id'], **{k: place[k] for k in ('name', 'business_type', 'address', 'latitude', 'longitude', 'rating', 'review_count', 'price', 'website', 'rank')}, raw_subset={'source_url': place['source_url']})
                db.add(record)
                ids[place['data_id']] = record.id
            db.flush()
            for e in evidence:
                db.add(Evidence(analysis_id=analysis_id, competitor_id=ids.get(e.get('data_id')), **{k: v for k, v in e.items() if k != 'data_id'}))
            component = {'maps': 'competition_gap', 'reviews': 'unmet_need', 'trends': 'demand', 'news': 'market_momentum', 'ads': 'advertising_gap'}
            for key, values in [('maps', places), ('reviews', samples), ('trends', series), ('news', articles), ('ads', advertising)]:
                db.add(Signal(analysis_id=analysis_id, engine=ENGINES[key], signal_type=key, score=result['component_scores'][component[key]], payload={'items': values}, status=sections[key]['status']))
            row.report, row.status, row.stage, row.progress = report, 'complete', 'complete', 100
            row.completed_at, row.sections, row.warnings = now(), sections, warnings
            for key in ('overall_score', 'confidence_score', 'interpretation', 'recommendation', 'component_scores'):
                setattr(row, key, report[key])
    except Exception as e:
        code = e.code if isinstance(e, EngineError) else 'ENGINE_UNAVAILABLE'
        logger.error('analysis=%s failed code=%s', analysis_id, code)
        with Session.begin() as db:
            row = db.get(Analysis, analysis_id)
            row.status, row.error_message, row.completed_at = 'failed', MESSAGES[code], now()
            row.sections, row.warnings = sections, warnings
            row.report = {'search_usage': client.usage()}
