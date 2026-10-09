import {useEffect,useState} from 'react';
import {Link,useParams,useSearchParams} from 'react-router-dom';
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query';
import {api,ApiError} from '../api/client';
import {researchApi} from '../api/research';
import {researchTools,toolKeys} from '../lib/researchTools';
import type {ResearchInput,ResearchTool,ResearchRun} from '../types/research';
import {ResearchInputForm} from '../components/ResearchInputForm';
import {ResearchResults} from '../components/ResearchResults';
import {SearchUsagePanel} from '../components/SearchPlanner';
import '../styles/research-workspace.css';
import {RetainedContent} from '../components/ReportWorkspace';

function SavedResults({run,reportId}:{run?:ResearchRun;reportId:string}){
 const [visited,setVisited]=useState<ResearchRun[]>([]);
 useEffect(()=>{if(run)setVisited(previous=>[...previous.filter(item=>item.id!==run.id),run])},[run]);
 const runs=run?[...visited.filter(item=>item.id!==run.id),run]:visited;
 return <>{runs.map(item=><RetainedContent key={item.id} active={item.id===run?.id}><ResearchResults run={item} reportId={reportId}/></RetainedContent>)}</>;
}

export function ResearchPage({embedded=false}:{embedded?:boolean}){
 const {id=''}=useParams(),[params,setParams]=useSearchParams(),cache=useQueryClient();
 const tool=(toolKeys.includes(params.get('tool') as ResearchTool)?params.get('tool'):'directions') as ResearchTool;
 const info=researchTools[tool];
 const reportQuery=useQuery({queryKey:['report',id],queryFn:()=>api.get(id)});
 const history=useQuery({queryKey:['research-history',id],queryFn:()=>researchApi.list(id),refetchInterval:q=>q.state.data?.some(j=>['queued','running'].includes(j.status))?3000:false});
 const matching=(history.data||[]).filter(j=>j.tool===tool);
 const runId=params.get('run')||matching[0]?.id||'';
 const result=useQuery({queryKey:['research-run',id,runId],queryFn:()=>researchApi.get(id,runId),enabled:!!runId,refetchInterval:q=>q.state.data&&['queued','running'].includes(q.state.data.status)?2000:false});
 const [feedback,setFeedback]=useState('');
 const create=useMutation({mutationFn:(data:ResearchInput)=>researchApi.create(id,data),onSuccess:(value,input)=>{setParams({tool:input.tool,run:value.id});setFeedback(value.cached?'Opened cached research; no new searches.':'Research started. You can return to this URL.');void cache.invalidateQueries({queryKey:['research-history',id]})}});
 const status=result.data?.status;
 useEffect(()=>{if(status&&!['queued','running'].includes(status))void cache.invalidateQueries({queryKey:['research-history',id]})},[status,id,cache]);
 if(reportQuery.isPending)return <p>Loading report context…</p>;
 if(reportQuery.isError)return <section className="report-section"><h1>Report unavailable</h1><p>{reportQuery.error.message}</p><button className="secondary" onClick={()=>reportQuery.refetch()}>Retry loading</button></section>;
 const report=reportQuery.data;
 if(report.status!=='complete')return <p>Complete the <Link to={`/reports/${id}`}>source analysis</Link> before using research tools.</p>;
 const busy=create.isPending||(history.data||[]).some(j=>['queued','running'].includes(j.status));
 const run=result.data?.tool===tool?result.data:undefined;
 let errorMessage=create.error?.message;
 if(create.error instanceof ApiError){const fields=create.error.details.fields as unknown;if(Array.isArray(fields))errorMessage=fields.map(f=>f.message).join(' ')}
 return <>{!embedded&&<div className="research-workspace-heading"><Link to={`/reports/${id}`}>← Back to market report</Link><h1>Explore more market evidence</h1><p>{report.input.business_category} · {report.input.city}, {report.input.country}</p><p>Choose a source, run a focused search and inspect the saved results. Research findings are supplemental; they do not change the report’s opportunity score.</p></div>}
 {report.data_mode==='fixture'&&<p className="sample-banner"><strong>Sample workspace.</strong> Every source returns fixed synthetic examples. They do not answer custom searches. No live SerpApi requests are sent.</p>}
 <div className="research-workspace">{!embedded&&<nav className="tool-directory" aria-label="Research data sources">{toolKeys.map(key=><button key={key} aria-current={tool===key?'page':undefined} onClick={()=>{setParams({tool:key});create.reset();setFeedback('')}}>{researchTools[key].title}<span className="hint">{(history.data||[]).filter(j=>j.tool===key).length} saved runs in recent history</span></button>)}</nav>}
 <div className="tool-main"><section className="report-section"><h2>{info.title}</h2><p>{info.purpose}</p><p className="hint">{info.limitation}</p>{toolKeys.map(key=><RetainedContent key={id+key} active={key===tool}><ResearchInputForm report={report} tool={key} busy={busy} onSubmit={input=>{setFeedback('');create.mutate(input)}}/></RetainedContent>)}{errorMessage&&<p role="alert">{errorMessage}</p>}<p role="status">{feedback}</p><details><summary>Source and collection scope</summary><p>One result page per request, with up to three requests per run. The report supplies the search country and, where supported, city. Search results can include other locations. Scholarship searches cover the broader research topic. Identical completed runs can be reused for one hour.</p><a href={`https://serpapi.com/${info.doc}`} target="_blank" rel="noopener noreferrer">SerpApi documentation</a></details></section>
 <section className="report-section" aria-label="Saved research"><div className="section-heading"><h2>Saved research</h2><button className="secondary" onClick={()=>history.refetch()}>Refresh history</button></div>{history.isError&&<p role="alert">Could not load research history. Retry with Refresh history.</p>}{matching.length>0&&<label>Open a saved run<select value={runId} onChange={e=>setParams({tool,run:e.target.value})}>{matching.map(j=><option key={j.id} value={j.id}>{new Date(j.created_at).toLocaleString()} · {j.status} · {j.input.query||j.input.origin||`${j.input.departure_airport} → ${j.input.arrival_airport}`}</option>)}</select></label>}
 {!runId&&<p>No saved runs for this source. Choose inputs above to start.</p>}{result.isError&&<><p role="alert">{result.error.message}</p><button className="secondary" onClick={()=>result.refetch()}>Reload this run</button></>}{runId&&result.isPending&&<p>Loading saved research…</p>}
 {run&&<><p><strong>{run.status}</strong> · collected {new Date(run.created_at).toLocaleString()} · {run.data_mode}</p>{run.sample_notice&&<p className="notice">{run.sample_notice}</p>}{['queued','running'].includes(run.status)&&<p role="status">Processed {run.completed_requests} of {run.planned_requests} planned requests. This page checks the same run; reopening it does not start another search.</p>}{run.error&&<p role="alert">{run.error}</p>}<details><summary>Inputs used for this run</summary><dl className="research-metadata">{Object.entries(run.input).map(([k,v])=><div key={k}><dt>{k.replaceAll('_',' ')}</dt><dd>{Array.isArray(v)?v.join(', '):String(v)}</dd></div>)}</dl></details></>}
 <SavedResults run={run} reportId={id}/>
 {run&&<><details><summary>Source status ({run.batches.length} batches)</summary><ul>{run.batches.map((b,i)=><li key={i}>{b.label}: {b.status} · {b.rows.length} results. {b.message}</li>)}</ul></details><SearchUsagePanel usage={run.usage}/></>}
 </section></div></div></>;
}
