"""SerpApi-backed research overlap workflow and deterministic evidence scoring."""
import hashlib
import json
import math
import re
from difflib import SequenceMatcher
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import serpapi

from app.config import settings
from app.db.session import Session
from app.models.novelty import NoveltyReport
from app.analysis import groq_enrichment
from app.analysis.research_guidance import build_guidance
from app.analysis.normalizers import safe_url as sanitized_source_url
from app.search_budget import claim_provider_attempt, DailySearchLimit

STOP = set('a an and are as at be been by for from in into is it of on or that the their this to was were with'.split())
DISCLAIMER = 'ResearchScope provides search assistance. It does not determine legal patentability, guarantee scientific novelty, or replace professional literature review or patent counsel.'


class ProviderAuthError(Exception): pass
class ProviderCapacityError(Exception): pass
class ProviderUnavailableError(Exception): pass


def words(text):
    return [w for w in re.findall(r"[a-z0-9]+(?:[-'][a-z0-9]+)*", (text or '').lower()) if w not in STOP]


def cosine(a, b):
    docs = [Counter(words(a)), Counter(words(b))]
    if not docs[0] or not docs[1]:
        return 0.0
    df = Counter(w for d in docs for w in d)
    # Document frequency is intentionally binary across the two documents.
    df = Counter({w: sum(w in d for d in docs) for w in df})
    vocab = set(docs[0]) | set(docs[1])
    vecs = []
    for doc in docs:
        vecs.append({w: (1 + math.log(n)) * (math.log(3 / (df[w] + 1)) + 1) for w, n in doc.items()})
    dot = sum(vecs[0].get(w, 0) * vecs[1].get(w, 0) for w in vocab)
    norm = math.sqrt(sum(v*v for v in vecs[0].values()) * sum(v*v for v in vecs[1].values()))
    return dot / norm if norm else 0.0


def safe_url(url):
    return sanitized_source_url(url)


def rows(raw, key):
    result = raw.get(key, []) if isinstance(raw, dict) else []
    return result if isinstance(result, list) else []


def names(value):
    values=value if isinstance(value,list) else [value]
    result=[]
    for entry in values:
        if isinstance(entry,dict): entry=entry.get('name') or entry.get('value') or entry.get('inventor') or entry.get('assignee')
        if isinstance(entry,str) and entry.strip(): result.append(entry.strip()[:160])
    return list(dict.fromkeys(result))[:12]


def bounded_list(value,limit):
    return value[:limit] if isinstance(value,list) else []


def detail_records(value,limit=10):
    result=[]
    for entry in bounded_list(value,limit):
        if isinstance(entry,str): result.append(entry[:600]);continue
        if not isinstance(entry,dict): continue
        clean={}
        for key in ('title','name','text','claim','claim_text','patent_id','publication_number','number','date','publication_date','priority_date','filing_date','status','description','snippet','classification','code','family_id'):
            value=entry.get(key)
            if isinstance(value,(str,int,float)): clean[key]=str(value)[:1000]
        for key in ('link','url','source_url','pdf'):
            link=safe_url(entry.get(key))
            if link: clean[key]=link
        if clean: result.append(clean)
    return result


def normalize(items, source, limit=20):
    found, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get('title') or item.get('patent_title') or '').strip()[:400]
        link = safe_url(item.get('link') or item.get('patent_link') or item.get('google_patent_link'))
        summary = str(item.get('snippet') or item.get('abstract') or item.get('description') or '').strip()[:4000]
        if not title:
            continue
        ident = str(item.get('result_id') or item.get('patent_id') or link or title.casefold())
        if ident in seen:
            continue
        seen.add(ident)
        publication = item.get('publication_info') if isinstance(item.get('publication_info'),dict) else {}
        inline_links=item.get('inline_links') if isinstance(item.get('inline_links'),dict) else {}
        cited = inline_links.get('cited_by') if isinstance(inline_links.get('cited_by'),dict) else {}
        pub_authors=publication.get('authors',[]) if isinstance(publication.get('authors'),list) else []
        authors=item.get('authors') if isinstance(item.get('authors'),list) else pub_authors
        found.append({'id': hashlib.sha1((source + ident).encode()).hexdigest()[:16], 'source_type': source,
                      'external_id': ident[:200], 'title': title, 'summary_text': summary,
                      'authors': [str(a.get('name') if isinstance(a,dict) else a)[:160] for a in authors[:12]],
                      'inventors': names(item.get('inventors')),
                      'assignees': names(item.get('assignees') or item.get('assignee')),
                      'source_url': link, 'pdf_url': safe_url(item.get('pdf')),
                      'publication_date': str(item.get('publication_date') or item.get('filing_date') or publication.get('summary') or '')[:160],
                      'priority_date': str(item.get('priority_date') or '')[:80],
                      'citation_count': cited.get('total') if isinstance(cited.get('total'), int) else None,
                      'patent_id': str(item.get('patent_id') or item.get('publication_number') or '')[:100],
                      'legal_status': str(item.get('status') or item.get('grant_status') or '')[:80],
                      'classifications': item.get('classifications', []) if isinstance(item.get('classifications'), list) else [],
                      'details': {}, 'versions': item.get('versions', {}).get('total') if isinstance(item.get('versions'), dict) else None})
        if len(found) >= limit:
            break
    return found


def dedupe(items, source):
    merged=[]
    for item in items:
        title=' '.join(re.findall(r'[a-z0-9]+',item['title'].casefold()))
        identity=item.get('patent_id') or item.get('external_id')
        duplicate=None
        for current in merged:
            current_title=' '.join(re.findall(r'[a-z0-9]+',current['title'].casefold()))
            same_id=bool(identity and identity in (current.get('patent_id'),current.get('external_id')))
            same_url=source=='web' and item.get('source_url') and item['source_url']==current.get('source_url')
            similar=source=='scholar' and title and SequenceMatcher(None,title,current_title).ratio()>.95
            if same_id or same_url or similar:
                duplicate=current;break
        if duplicate is None:
            merged.append(item);continue
        for key in ('summary_text','source_url','pdf_url','publication_date','priority_date','legal_status','patent_id'):
            if not duplicate.get(key) and item.get(key):duplicate[key]=item[key]
        duplicate['authors']=list(dict.fromkeys(duplicate.get('authors',[])+item.get('authors',[])))[:12]
        duplicate['assignees']=list(dict.fromkeys(duplicate.get('assignees',[])+item.get('assignees',[])))[:12]
        for key in ('citation_count','versions'):
            values=[v for v in (duplicate.get(key),item.get(key)) if isinstance(v,int)]
            duplicate[key]=max(values) if values else None
    return merged[:20]


def collapse_patent_families(items):
    families={}; singles=[]
    for item in items:
        family=item.get('family_id')
        if family:
            families.setdefault(family,[]).append(item)
        else: singles.append(item)
    for family,members in families.items():
        if len(members)==1:
            singles.extend(members);continue
        representative=min(members,key=lambda p:p.get('priority_date') or '9999')
        representative['family_id']=family
        representative['family_members']=[{'title':m['title'],'patent_id':m.get('patent_id'),'source_url':m.get('source_url'),'priority_date':m.get('priority_date')} for m in members]
        singles.append(representative)
    return singles[:20]


def score_report(data, papers, patents, web, queries, warnings):
    document = ' '.join([data['title'], data['abstract'], data.get('field', ''), *data['keywords'], *data['claims']])
    claims = data['claims']
    for item in papers + patents + web:
        evidence = ' '.join([item['title'], item['summary_text'], ' '.join(str(c) for c in item.get('classifications', []))])
        tf = cosine(document, evidence)
        covs = [cosine(c, evidence) for c in claims]
        evidence_terms=' '.join(words(evidence))
        phrases=list(dict.fromkeys(' '.join(words(p)) for p in [data['title'],*data['keywords']] if words(p)))
        phrase = sum(phrase in evidence_terms for phrase in phrases) / max(1,len(phrases))
        item['similarity_score'] = round(max(0, min(100, (tf * .6 + (sum(covs)/len(covs) if covs else tf)*.25 + phrase*.15)*100)))
        item['matched_claims'] = [{'claim_id': f'claim-{i+1}', 'similarity_score': round(v*100)} for i, v in enumerate(covs) if v >= .10]
        item['evidence_strength'] = min(100, 30 + (20 if item.get('source_url') else 0) + (20 if item.get('citation_count') is not None else 0) + (30 if item.get('details') else 0))
    core = sorted(papers + patents, key=lambda x: (x['similarity_score'], x['evidence_strength']), reverse=True)
    values = [x['similarity_score'] for x in core]
    top = max(values, default=0)
    mean5 = sum(sorted(values, reverse=True)[:5]) / min(5, len(values)) if values else 0
    breadth = min(sum(v >= 60 for v in values)/5, 1)*100
    overlap = round(top*.5 + mean5*.3 + breadth*.2)
    confidence = (20 if len(papers) >= 10 else round(20*len(papers)/10) + 0) + (20 if len(patents) >= 10 else round(20*len(patents)/10))
    confidence += 20 * sum(bool(p.get('details', {}).get('abstract')) for p in patents[:3]) / max(1, min(3, len(patents))) if patents else 0
    confidence += 15 if len(queries) >= 2 and papers and patents else 0
    confidence += 10 if len(claims) >= 2 else 0
    confidence += 5 if web else 0
    fields = [bool(x.get('source_url')) and bool(x.get('summary_text')) for x in core]
    confidence += 10 if fields and sum(fields)/len(fields) >= .8 else 0
    confidence = max(0, min(100, round(confidence)))
    label = 'High' if confidence >= 80 else 'Medium' if confidence >= 50 else 'Low'
    interpretation = 'Strong overlap detected' if overlap >= 75 else 'Substantial related work found' if overlap >= 55 else 'Moderate overlap found' if overlap >= 35 else 'Limited overlap found in searched sources'
    claim_reports=[]
    for i, claim in enumerate(claims):
        matches=sorted([{'evidence_id': item['id'], 'source_type': item['source_type'], 'title': item['title'], 'url': item.get('source_url'), 'similarity_score': round(cosine(claim, item['title']+' '+item['summary_text'])*100), 'excerpt':item['summary_text'][:500]} for item in core],key=lambda m:m['similarity_score'],reverse=True)[:5]
        best=matches[0]['similarity_score'] if matches else 0
        claim_reports.append({'id':f'claim-{i+1}','text':claim,'source':data.get('claims_source','user'),'coverage_score':best,'coverage_label':'High' if best>=70 else 'Medium' if best>=45 else 'Low','matched_terms':list(set(words(claim)) & set(words(matches[0]['excerpt'] if matches else ''))),'matches':matches})
    years=[]
    for item in core:
        date=item.get('priority_date') or item.get('publication_date') or ''
        match=re.search(r'\b(19|20)\d{2}\b',date)
        if match: years.append({'year':int(match.group()),'source_type':item['source_type'],'title':item['title'],'url':item.get('source_url')})
    assignees=Counter(a for item in patents for a in item.get('assignees',[]) if isinstance(a,str) and a.strip())
    inventors=Counter(a for item in patents for a in item.get('inventors',[]) if isinstance(a,str) and a.strip())
    authors=Counter(a for item in papers for a in item.get('authors',[]) if isinstance(a,str) and a.strip())
    report = {'status':'complete','input':{k:v for k,v in data.items() if k!='credentials'},'queries':queries,
            'overlap_score':overlap,'novelty_signal':100-overlap,'confidence_score':confidence,'confidence_label':label,
            'interpretation':interpretation,'credential_mode':'hosted','ai_analysis':{'status':'unavailable','model':None,'prompt_version':'1.0','executive_summary':'A language model was not configured. Similarity and claim coverage below were calculated deterministically from retrieved evidence.','claim_explanations':[],'areas_needing_deeper_search':[],'warnings':['AI explanation unavailable; evidence and scores remain complete.']},
            'summary':{'strongest_overlaps':core[:3],'least_covered_claims':sorted(claim_reports,key=lambda c:c['coverage_score'])[:3], 'disclaimer':DISCLAIMER},
            'claims':claim_reports,'papers':sorted(papers,key=lambda x:x['similarity_score'],reverse=True)[:20],
            'patents':sorted(patents,key=lambda x:x['similarity_score'],reverse=True)[:20], 'web_results':sorted(web,key=lambda x:x['similarity_score'],reverse=True)[:10],
            'timeline':sorted(years,key=lambda x:x['year']), 'assignee_summary':[{'name':n,'count':c} for n,c in assignees.most_common(8)],
            'inventor_summary':[{'name':n,'count':c} for n,c in inventors.most_common(8)],'author_summary':[{'name':n,'count':c} for n,c in authors.most_common(8)],'warnings':warnings,
            'methodology_version':'1.0','created_at':datetime.now(timezone.utc).isoformat()}
    report['research_guidance'] = build_guidance(report)
    return report


def provider_search(client, engine, *, personal=False, subject=None, **params):
    if settings.live_serpapi_enabled and not personal:
        try:claim_provider_attempt(subject) if subject else claim_provider_attempt()
        except DailySearchLimit:raise ProviderCapacityError() from None
    try:
        result = dict(client.search({'engine':engine,**params}))
    except Exception as exc:
        status=getattr(exc,'status_code',None)
        if status in (401,403): raise ProviderAuthError() from None
        if status==429: raise ProviderCapacityError() from None
        raise ProviderUnavailableError() from None
    message=str(result.get('error') or '').casefold()
    if any(word in message for word in ('api key','unauthorized','authentication')): raise ProviderAuthError()
    if any(word in message for word in ('quota','rate limit','credits','searches left','run out')): raise ProviderCapacityError()
    if engine == 'google_patents' and message == "google patents hasn't returned any results for this query.":
        return {**{key: value for key, value in result.items() if key != 'error'}, 'organic_results': []}
    if message: raise ProviderUnavailableError()
    return result


def run_novelty_job(report_id, credentials=None, subject=None):
    with Session() as db:
        row = db.get(NoveltyReport, report_id)
        if not row: return
        data = dict(row.input_data)
        public_report=row.is_public;saved_report=row.saved
        row.status, row.stage, row.progress = 'running','preparing_queries',5
        db.commit()
    warnings=[]; papers=[]; patents=[]; web=[]; queries=[]; provider_calls=[0];provider_halted=[False]
    def search(engine, **params):
        if provider_halted[0] or provider_calls[0]>=8: raise ProviderCapacityError()
        provider_calls[0]+=1
        try:return provider_search(client,engine,personal=bool(credentials),subject=subject,**params)
        except ProviderCapacityError:
            provider_halted[0]=True
            raise
    structured={}
    ai={'status':'unavailable','model':settings.groq_model if settings.groq_enabled else None,'prompt_version':'1.0','call_count':0,
        'executive_summary':'A language model was not configured. Similarity and claim coverage were calculated deterministically from retrieved evidence.',
        'claim_explanations':[],'areas_needing_deeper_search':[],'warnings':[]}
    try:
        key=credentials.serpapi.get_secret_value() if credentials else settings.serpapi_key.get_secret_value()
        groq_available=bool(credentials.groq.get_secret_value()) if credentials else settings.groq_enabled and bool(settings.groq_api_key.get_secret_value())
        if (not settings.live_serpapi_enabled and not credentials) or not key:
            raise RuntimeError('Live research is not configured on this server. Open the prepared sample report or configure a backend SerpApi key.')
        client=serpapi.Client(api_key=key, timeout=settings.request_timeout_seconds)
        ai['model']=settings.groq_model if groq_available else None
        original_claims=bool(data.get('claims'))
        if data.get('use_groq',False) and groq_available:
            with Session.begin() as db: db.query(NoveltyReport).filter_by(id=report_id).update({'stage':'structuring_claims','progress':10})
            try:
                structured=groq_enrichment.structure(data,credentials=credentials); ai['call_count']+=1
                data['claims']=structured['claims']
                data['claims_source']='user' if original_claims else 'AI extracted'
                warnings.extend(str(w)[:240] for w in structured['warnings'][:3])
            except Exception:
                ai['warnings'].append('AI claim structuring unavailable; deterministic claim extraction was used.')
        if not data.get('claims'):
            sentences=re.split(r'(?<=[.!?])\s+',data['abstract'])
            candidates=[sentence.strip() for sentence in sentences if len(sentence.strip())>=15]
            data['claims']=sorted(candidates,key=lambda sentence:len(set(words(sentence))),reverse=True)[:3]
            data['claims_source']='machine extracted'
        elif 'claims_source' not in data:
            data['claims_source']='user' if original_claims else 'machine extracted'
        first=['"'+data['title']+'"', *([data['field']] if data.get('field') else []), *data['keywords'][:3]]
        second=[data['title'], *data['keywords'][3:5], *data['claims'][:1], *data.get('known_related_work',[])[:1]]
        if data.get('earliest_year'):
            year=f"after:{data['earliest_year']}"
            first.append(year);second.append(year)
        qs=[' '.join(first), ' '.join(second)]
        qs=[q[:350] for q in qs]
        scholar_q=[(q+' '+' '.join(structured.get('scholar_terms',[])[:3] if index==0 else []))[:350] for index,q in enumerate(qs)]
        patent_q=[(q+' '+' '.join(structured.get('patent_terms',[])[:3] if index==1 else []))[:350] for index,q in enumerate(qs)]
        web_query=(qs[0]+' '+' '.join(structured.get('web_terms',[])[:3])+' implementation OR software')[:350]
        search_pairs={'google_scholar':scholar_q,'google_patents':patent_q,'google':[web_query]}
        queries=[{'engine':engine,'query':query,'timestamp':datetime.now(timezone.utc).isoformat()} for engine,searches in search_pairs.items() for query in searches]
        for q in scholar_q:
            with Session.begin() as db: db.query(NoveltyReport).filter_by(id=report_id).update({'stage':'searching_papers','progress':25})
            try: papers += normalize(rows(search('google_scholar',q=q,num=10), 'organic_results'),'scholar')
            except ProviderCapacityError: warnings.append('Provider call allowance reached; remaining optional searches were skipped.')
            except ProviderAuthError: raise
            except Exception: warnings.append('A Scholar search was unavailable; any completed paper results are retained.')
        if not papers: warnings.append('No paper records were returned.')
        for q in patent_q:
            with Session.begin() as db: db.query(NoveltyReport).filter_by(id=report_id).update({'stage':'searching_patents','progress':45})
            try: patents += normalize(rows(search('google_patents',q=q), 'organic_results'),'patent')
            except ProviderCapacityError: warnings.append('Provider call allowance reached; remaining optional searches were skipped.')
            except ProviderAuthError: raise
            except Exception: warnings.append('A patent search was unavailable; any completed patent results are retained.')
        if not patents: warnings.append('No patent records were returned.')
        papers=dedupe(papers,'scholar')
        patents=dedupe(patents,'patent')
        for patent in sorted(patents,key=lambda x: x.get('source_url') is not None,reverse=True)[:3]:
            try:
                with Session.begin() as db: db.query(NoveltyReport).filter_by(id=report_id).update({'stage':'patent_details','progress':58})
                details=search('google_patents_details',patent_id=patent['patent_id'] or patent['external_id'])
                family_raw=details.get('family') if isinstance(details.get('family'),dict) else {}
                family_id=details.get('family_id') or family_raw.get('family_id') or family_raw.get('id')
                family={'family_id':str(family_id)[:100] if family_id else None,
                        'applications':detail_records(family_raw.get('applications') or family_raw.get('members'),20)}
                patent['details']={'abstract':str(details.get('abstract') or '')[:4000],
                    'claims':detail_records(details.get('claims'),20),'family':family,
                    'patent_citations':detail_records(details.get('patent_citations'),10),
                    'non_patent_citations':detail_records(details.get('non_patent_citations'),10),
                    'cited_by_documents':detail_records(details.get('cited_by_documents'),10),
                    'similar_documents':detail_records(details.get('similar_documents'),10),
                    'worldwide_applications':detail_records(details.get('worldwide_applications'),20),
                    'legal_events':detail_records(details.get('legal_events'),20),
                    'classifications':detail_records(details.get('classifications'),20)}
                family=patent['details']['family']
                family_id=details.get('family_id') or family.get('family_id') or family.get('id')
                if family_id: patent['family_id']=str(family_id)[:100]
                patent['summary_text']=(patent['summary_text']+' '+patent['details']['abstract']+' '+' '.join(str(c) for c in patent['details']['claims'][:5]))[:4000]
            except ProviderCapacityError:
                warnings.append('Provider call allowance reached; remaining optional searches were skipped.')
            except ProviderAuthError: raise
            except Exception:
                warnings.append(f"Patent details unavailable for {patent['title']}.")
        try:
            with Session.begin() as db: db.query(NoveltyReport).filter_by(id=report_id).update({'stage':'searching_web','progress':72})
            web=normalize(rows(search('google',q=web_query,num=10),'organic_results'),'web',10)
        except ProviderCapacityError: warnings.append('Provider call allowance reached; remaining optional searches were skipped.')
        except ProviderAuthError: raise
        except Exception: warnings.append('Public web search was unavailable; the academic and patent results are retained.')
        web=dedupe(web,'web')[:10]
        patents=collapse_patent_families(patents)
        with Session.begin() as db: db.query(NoveltyReport).filter_by(id=report_id).update({'stage':'comparing_claims','progress':84})
        report=score_report(data,papers,patents,web,queries,warnings)
        if data.get('use_groq',False) and groq_available:
            with Session.begin() as db: db.query(NoveltyReport).filter_by(id=report_id).update({'stage':'explaining_evidence','progress':93})
            try:
                explanation=groq_enrichment.explain(data,report,credentials=credentials); ai['call_count']+=1
                ai.update({'status':'complete' if ai['call_count']==2 else 'partial',
                           'executive_summary':explanation['executive_summary'],
                           'claim_explanations':explanation['claim_explanations'],
                           'areas_needing_deeper_search':explanation['areas_needing_deeper_search'],
                           'report_limitations':explanation['report_limitations']})
            except Exception:
                ai['warnings'].append('AI explanation unavailable; evidence and scores remain complete.')
        if ai['call_count'] and ai['status']=='unavailable': ai['status']='partial'
        report['ai_analysis']=ai
        report['credential_mode']='personal' if credentials else 'hosted'
        report['is_public']=public_report;report['saved']=saved_report
        report['warnings']=list(dict.fromkeys(report['warnings']+ai['warnings']))
        with Session.begin() as db: db.query(NoveltyReport).filter_by(id=report_id).update({'stage':'building_report','progress':98})
        with Session.begin() as db:
            row=db.get(NoveltyReport,report_id); row.report=report; row.status='complete'; row.stage='complete'; row.progress=100
            from app.main import finish_novelty_usage
            finish_novelty_usage(db,report_id,provider_calls[0],'complete')
    except ProviderAuthError:
        with Session.begin() as db:
            row=db.get(NoveltyReport,report_id)
            if row:
                row.status='failed';row.stage='failed';row.progress=100
                row.error_message='SerpApi authentication failed. Re-enter your personal key and start again.' if credentials else 'SerpApi authentication failed. Check the backend credential configuration.'
                from app.main import finish_novelty_usage
                finish_novelty_usage(db,report_id,provider_calls[0],'failed')
    except Exception:
        with Session.begin() as db:
            row=db.get(NoveltyReport,report_id)
            if row:
                row.status='failed'; row.stage='failed'; row.progress=100
                row.error_message='Search providers could not complete the report. Check server configuration or try again later.'
                from app.main import finish_novelty_usage
                finish_novelty_usage(db,report_id,provider_calls[0],'failed')
