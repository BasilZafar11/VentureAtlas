import {lazy,Suspense,useState} from 'react';
import {Link} from 'react-router-dom';
import type {Report,ScoreKey,Section} from '../types/analysis';
import {EvidenceStrength} from './EvidenceStrength';
import {ReviewMatrix,KeywordFinder,Seasonality} from './MarketResearch';
import {BreakEven} from './BreakEven';
import {ResearchNotebook} from './ResearchNotebook';
import '../styles/research.css';
import {HoursGaps,BrandCompetition,ReputationChanges} from './CompetitionTools';
import {RelevanceReview} from './RelevanceReview';
import {SearchUsagePanel} from './SearchPlanner';
import {ReportPanel,ReportWorkspace} from './ReportWorkspace';
import {ReportPagination,useReportPagination} from './ReportPagination';
import {strategySections} from '../lib/strategy';
const ResearchPage=lazy(()=>import('../pages/ResearchPage').then(m=>({default:m.ResearchPage})));
const StrategyTool=lazy(()=>import('../pages/StrategyPage').then(m=>({default:m.StrategyTool})));
const CompetitorExplorer=lazy(()=>import('./CompetitorExplorer').then(m=>({default:m.CompetitorExplorer})));
const DemandChart=lazy(()=>import('./DemandChart').then(m=>({default:m.DemandChart})));
const ScoringPriorities=lazy(()=>import('./ScoringPriorities').then(m=>({default:m.ScoringPriorities})));
const OpportunityStress=lazy(()=>import('./OpportunityStress').then(m=>({default:m.OpportunityStress})));
const AreaExplorer=lazy(()=>import('./AreaExplorer').then(m=>({default:m.AreaExplorer})));
const ConceptSandbox=lazy(()=>import('./ConceptSandbox').then(m=>({default:m.ConceptSandbox})));
const ValidationLab=lazy(()=>import('./ValidationLab').then(m=>({default:m.ValidationLab})));
const DecisionJournal=lazy(()=>import('./DecisionJournal').then(m=>({default:m.DecisionJournal})));

const labels:Record<ScoreKey,string>={demand:'Demand',competition_gap:'Competition gap',unmet_need:'Unmet need',market_momentum:'Market momentum',advertising_gap:'Advertising gap'};
const sectionFor:Record<ScoreKey,string>={demand:'trends',competition_gap:'maps',unmet_need:'reviews',market_momentum:'news',advertising_gap:'ads'};
export function External({url,children}:{url:string|null;children:React.ReactNode}){return url&&/^https?:\/\//i.test(url)?<a href={url} target="_blank" rel="noopener noreferrer">{children}<span className="sr-only"> (opens in a new tab)</span></a>:<span>{children}</span>}
const date=(value:string|null)=>value?new Date(value).toLocaleDateString(undefined,{day:'numeric',month:'short',year:'numeric'}):'Date unavailable';
function Status({section}:{section:Section}){return <span className={`status ${section.status}`}>{section.status==='complete'?`${section.count} observations`:section.status}</span>}
function Source({children}:{children:React.ReactNode}){return <p className="source">Source: {children}</p>}

export function ReportView({report:r}:{report:Report}){
 const [shared,setShared]=useState('');
 const [evidenceQuery,setEvidenceQuery]=useState('');
 const newsPage=useReportPagination(r.news,5),adsPage=useReportPagination(r.advertising,10);
 const evidencePage=useReportPagination(r.evidence.filter(e=>`${e.title} ${e.source_name}`.toLowerCase().includes(evidenceQuery.toLowerCase())),10,evidenceQuery);
 async function share(){try{await navigator.clipboard.writeText(window.location.href);setShared('Link copied')}catch{setShared('Copy this page’s URL from your address bar')}}
 return <>
  <div className="report-heading"><div><p className="muted">Market report · {date(r.created_at)}</p><h1>{r.input.business_category}<span className="location">{r.input.city}, {r.input.country}</span></h1></div><div className="report-actions"><Link className="secondary" to={`/compare?left=${encodeURIComponent(r.id)}`}>Compare report</Link><button className="secondary" onClick={share}>Copy report link</button></div><span role="status">{shared}</span></div>
  {r.relevance_audit&&<div className="notice"><strong>Revised evidence selection</strong> · This report excludes user-selected results. <Link to={`/reports/${r.relevance_audit.source_report_id}`}>View the source report</Link> or <a href="#relevance-review">inspect the exclusion record</a>.</div>}
  {r.data_mode==='fixture'&&<div className="sample-banner"><strong>Sample report</strong> · Synthetic observations for interface testing. These scores are not evidence about the real Pune market. Sample sources are illustrative.</div>}
  {r.warnings.filter(w=>!w.startsWith('Sample report')).length>0&&<details className="warnings" open><summary>Data notes ({r.warnings.filter(w=>!w.startsWith('Sample report')).length})</summary><ul>{r.warnings.filter(w=>!w.startsWith('Sample report')).map(w=><li key={w}>{w}</li>)}</ul></details>}
  <ReportWorkspace key={r.id} reportId={r.id}>
  <ReportPanel id="overview">
  <section className="score-hero" aria-labelledby="result-heading"><div className="score-dial"><span className="big-score">{r.overall_score}</span><span>/ 100 opportunity</span></div><div className="score-copy"><span className="pill">{r.interpretation}</span><h2 id="result-heading">{r.recommendation.headline}</h2><p>Search signals support research. Validate with customer interviews and financial analysis before committing resources.</p><a href="#methodology">How this score is calculated</a></div><div className="confidence"><strong>{r.confidence_score}<small>/100</small></strong><span>{r.confidence_label} confidence</span><p>Data completeness,<br/>not business certainty.</p></div></section>
  <section className="report-section" aria-label="Recommendation"><details className="overview-recommendations"><summary>Recommendations: strengths, risks and next checks</summary><div className="recommendation-grid">{([['Relative strengths',r.recommendation.strengths],['Areas to validate',r.recommendation.risks],['Next checks',r.recommendation.next_checks]] as const).map(([title,items])=><div key={title}><h3>{title}</h3>{items.length?<><ul>{items.slice(0,3).map((i,n)=><li key={n}><a href={i.href}>{i.text}</a></li>)}</ul>{items.length>3&&<details><summary>View {items.length-3} more</summary><ul>{items.slice(3).map((i,n)=><li key={n}><a href={i.href}>{i.text}</a></li>)}</ul></details>}</>:<p className="muted">Insufficient evidence for this comparison.</p>}</div>)}</div></details></section>
  <section className="report-section"><div className="section-heading"><h2>What drives the score</h2><a href="#evidence-strength">Check evidence strength</a></div><div className="score-breakdown">{(Object.keys(labels) as ScoreKey[]).map(key=><a href={`#${key}`} key={key} className="component"><div><span>{labels[key]}</span><strong>{r.component_scores[key].toFixed(0)}</strong></div><meter min={0} max={100} value={r.component_scores[key]} aria-label={`${labels[key]} score`}/><span className="hint">{r.methodology.weights[key]*100}% weight · {r.sections[sectionFor[key]].status==='complete'?'Available evidence':'Neutral fallback'}</span></a>)}</div></section>
  <div className="report-overview-links"><a href="#competition_gap">Inspect market evidence</a><Link to={`/reports/${r.id}/research`}>Open research sources</Link><Link to={`/reports/${r.id}/strategy`}>Plan your next experiment</Link></div>
  </ReportPanel>
  <ReportPanel id="evidence-strength"><EvidenceStrength report={r}/></ReportPanel>
  <ReportPanel id="research-sources"><Suspense fallback={<p role="status">Loading research tools…</p>}><ResearchPage embedded/></Suspense></ReportPanel>
  {strategySections.map(([tool,title])=><ReportPanel id={`strategy-${tool}`} key={tool}><Suspense fallback={<p role="status">Loading {title.toLowerCase()}…</p>}><div className="strategy-layout"><section className="report-section"><h2>{title}</h2><StrategyTool report={r} tool={tool}/></section></div></Suspense></ReportPanel>)}
  <ReportPanel id="opportunity-stress"><OpportunityStress key={`stress-${r.id}`} report={r}/></ReportPanel>
  <ReportPanel id="area-explorer"><AreaExplorer key={`areas-${r.id}`} report={r}/></ReportPanel>
  <ReportPanel id="concept-sandbox"><ConceptSandbox key={`concept-${r.id}`} report={r}/></ReportPanel>
  <ReportPanel id="validation-lab"><ValidationLab key={`lab-${r.id}`} report={r}/></ReportPanel>
  <ReportPanel id="decision-journal"><DecisionJournal key={`journal-${r.id}`} report={r}/></ReportPanel>
  <ReportPanel id="hours-gaps"><HoursGaps key={`hours-${r.id}`} report={r}/></ReportPanel>
  <ReportPanel id="brand-competition"><BrandCompetition key={`brands-${r.id}`} report={r}/></ReportPanel>
  <ReportPanel id="reputation-changes"><ReputationChanges report={r}/></ReportPanel>
  <ReportPanel id="relevance-review"><RelevanceReview key={`relevance-${r.id}`} report={r}/></ReportPanel>
  <ReportPanel id="search-usage"><SearchUsagePanel usage={r.search_usage}/></ReportPanel>
  <ReportPanel id="review-matrix"><ReviewMatrix report={r}/></ReportPanel>
  <ReportPanel id="break-even"><BreakEven key={`calculator-${r.id}`}/></ReportPanel>
  <ReportPanel id="keyword-opportunities"><KeywordFinder key={`keywords-${r.id}`} report={r}/></ReportPanel>
  <ReportPanel id="seasonality"><Seasonality key={`season-${r.id}`} report={r}/></ReportPanel>
  <ReportPanel id="notebook"><ResearchNotebook key={`notes-${r.id}`} report={r}/></ReportPanel>
  <ReportPanel id="priorities"><ScoringPriorities key={r.id} report={r}/></ReportPanel>
  <ReportPanel id="competition_gap"><CompetitorExplorer key={`explorer-${r.id}`} report={r}/></ReportPanel>
  <ReportPanel id="demand">
  <section className="report-section" id="demand"><div className="section-heading"><div><h2>Demand over time</h2><p>Country-level interest in {r.input.country}; keyword wording carries the city intent.</p></div><Status section={r.sections.trends}/></div><DemandChart series={r.trend_series}/><Source>Google Trends via SerpApi · one year requested</Source></section>
  </ReportPanel>
  <ReportPanel id="unmet_need"><section className="report-section" id="unmet_need"><div className="section-heading"><div><h2>Where customers see room to improve</h2><p>Topics in sampled 1–3 star reviews from up to three competitors.</p></div><Status section={r.sections.reviews}/></div>{r.review_topics.length?<div className="topic-grid">{r.review_topics.map(t=><article className="topic" key={t.topic}><div className="section-heading"><h3>{t.topic}</h3>{t.repeated&&<span className="pill">Repeated</span>}</div><p className="muted">{t.mentions} mentions · {t.competitor_count} competitors</p><details><summary>View {t.excerpts.length} supporting excerpts</summary>{t.excerpts.map((e,i)=><blockquote key={i}><p>“{e.text||'Rating only; no review text returned.'}”</p><footer><External url={e.source_url}>{e.competitor}</External> · {e.rating}/5 · {date(e.published_at)}{!e.source_url&&' · Direct review link unavailable'}</footer></blockquote>)}</details></article>)}</div>:<p className="empty">No complaint topics are available from this sample.</p>}<Source>Google Maps Reviews via SerpApi. One recent page per selected competitor; not a representative customer survey.</Source></section></ReportPanel>
  <ReportPanel id="market_momentum"><section className="report-section" id="market_momentum"><div className="section-heading"><div><h2>Market developments</h2><p>Exact keyword matches and dates determine the news signal.</p></div><Status section={r.sections.news}/></div>{r.news.length?<><div className="news-list">{newsPage.items.map((n,i)=><article key={i}><div><span className={`sentiment ${n.sentiment}`}>{n.sentiment}</span><span className="muted">{n.source} · {date(n.published_at)}</span></div><h3><External url={n.source_url}>{n.title}</External></h3>{n.snippet&&<p>{n.snippet}</p>}<p className="hint">Matched: {n.matched_keywords.join(', ')||'none'} · Recency weight: {n.weight}</p></article>)}</div><ReportPagination {...newsPage} label="articles"/></>:<p className="empty">Market news is unavailable. Momentum uses a neutral score.</p>}<Source>Google News via SerpApi. Keyword classification can miss context and negation.</Source></section></ReportPanel>
  <ReportPanel id="advertising_gap"><section className="report-section" id="advertising_gap"><div className="section-heading"><div><h2>Visible advertising activity</h2><p>Matched advertiser creatives; worldwide coverage, not local spend.</p></div><Status section={r.sections.ads}/></div>{r.advertising.length?<><div className="table-scroll"><table><thead><tr><th>Advertiser</th><th>Format</th><th>First shown</th><th>Last shown</th><th>Evidence</th></tr></thead><tbody>{adsPage.items.map((a,i)=><tr key={i}><td>{a.advertiser}</td><td>{a.format||'Unavailable'}</td><td>{date(a.first_shown)}</td><td>{date(a.last_shown)}</td><td><External url={a.source_url}>{a.source_url?'View creative':'Link unavailable'}</External></td></tr>)}</tbody></table></div><ReportPagination {...adsPage} label="advertising records"/></>:<p className="empty">No reliable active advertiser match is available. A neutral score does not imply low advertising competition.</p>}<Source>Google Ads Transparency Center via SerpApi · up to three advertiser searches</Source></section></ReportPanel>
  <ReportPanel id="evidence"><section className="report-section" id="evidence"><div className="section-heading"><h2>Evidence register</h2><span className="muted">Retrieved {date(r.created_at)}</span></div><label className="report-evidence-filter">Search source records<input type="search" value={evidenceQuery} onChange={e=>setEvidenceQuery(e.target.value)} placeholder="Title or source name"/></label>{evidencePage.total?<><ol className="evidence-list" start={(evidencePage.page-1)*evidencePage.size+1}>{evidencePage.items.map(e=><li key={e.id}><External url={e.source_url}>{e.title}</External><span className="hint">{e.source_name} · {date(e.published_at)}{!e.source_url&&' · Direct source link unavailable'}</span></li>)}</ol><ReportPagination {...evidencePage} label="source records"/></>:<p className="empty">{r.evidence.length?'No source records match. Try a different title or source name.':'No source records are available.'}</p>}</section></ReportPanel>
  <ReportPanel id="methodology">
  <section className="report-section methodology" id="methodology"><h2>Methodology & limitations</h2><p>Version {r.methodology_version} · deterministic rules · no generative AI</p><details open><summary>Overall score and confidence</summary><p>Opportunity = demand × 25% + competition gap × 25% + unmet need × 25% + market momentum × 15% + advertising gap × 10%, rounded to the nearest integer. Missing components keep their weights and use neutral 50.</p><p>{r.methodology.confidence_rule}</p><dl className="confidence-points">{Object.entries(r.methodology.confidence_points).map(([k,v])=><div key={k}><dt>{k}</dt><dd>{v} points</dd></div>)}</dl><p>75–100: Strong signals. 55–74: Mixed-positive. 40–54: Mixed. 0–39: Weak signals.</p></details>{(Object.keys(labels) as ScoreKey[]).map(k=><details key={k}><summary>{labels[k]} · {r.component_scores[k]}/100</summary><p>{r.methodology.components[k].formula}</p><pre>{JSON.stringify(Object.fromEntries(Object.entries(r.methodology.components[k]).filter(([name])=>name!=='formula')),null,2)}</pre></details>)}<p className="limitation">Search visibility is not market size. Reviews are a small, biased sample. Trends are relative interest, news matching is heuristic, and advertising matches can be incomplete. Scores do not estimate revenue, profitability, or probability of success.</p></section>
  </ReportPanel>
  </ReportWorkspace>
 </>
}
