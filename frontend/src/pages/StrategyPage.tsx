import {useQuery} from '@tanstack/react-query';
import {Link,useParams,useSearchParams} from 'react-router-dom';
import {api} from '../api/client';
import {strategySections} from '../lib/strategy';
import {EvidenceGraph} from '../components/strategy/EvidenceGraph';
import {Conflicts} from '../components/strategy/Conflicts';
import {ResearchGaps} from '../components/strategy/ResearchGaps';
import {Personas} from '../components/strategy/Personas';
import {TeamWorkspace} from '../components/strategy/TeamWorkspace';
import {MarketChanges} from '../components/strategy/MarketChanges';
import {Offers} from '../components/strategy/Offers';
import {Regulations} from '../components/strategy/Regulations';
import {ExperimentPriorities} from '../components/strategy/ExperimentPriorities';
import {VenturePitch} from '../components/strategy/VenturePitch';
import '../styles/strategy.css';
import type {Report} from '../types/analysis';
export function StrategyTool({report:r,tool:selected}:{report:Report;tool:string}){
 return selected==='conflicts'?<Conflicts report={r}/>:selected==='gaps'?<ResearchGaps report={r}/>:selected==='personas'?<Personas report={r}/>:selected==='team'?<TeamWorkspace report={r}/>:selected==='changes'?<MarketChanges report={r}/>:selected==='offers'?<Offers report={r}/>:selected==='regulations'?<Regulations report={r}/>:selected==='experiments'?<ExperimentPriorities report={r}/>:selected==='pitch'?<VenturePitch report={r}/>:<EvidenceGraph report={r}/>;
}
export function StrategyPage(){
 const {id=''}=useParams(),[params,setParams]=useSearchParams();
 const selected=params.get('tool')||'graph';
 const q=useQuery({queryKey:['report',id],queryFn:()=>api.get(id)});
 if(q.isPending)return <p>Loading decision workspace…</p>;
 if(q.isError)return <p role="alert">{q.error.message}</p>;
 if(q.data.status!=='complete')return <p>A completed report is required.</p>;
 const r=q.data;
 const content=selected==='conflicts'?<Conflicts report={r}/>:selected==='gaps'?<ResearchGaps report={r}/>:selected==='personas'?<Personas report={r}/>:selected==='team'?<TeamWorkspace report={r}/>:selected==='changes'?<MarketChanges report={r}/>:selected==='offers'?<Offers report={r}/>:selected==='regulations'?<Regulations report={r}/>:selected==='experiments'?<ExperimentPriorities report={r}/>:selected==='pitch'?<VenturePitch report={r}/>:<EvidenceGraph report={r}/>;
 return <><Link to={`/reports/${id}`}>Back to market report</Link><h1>VentureAtlas decision workspace</h1><p>{r.input.business_category} in {r.input.city} · {r.data_mode}</p>{r.data_mode==='fixture'&&<p className="sample-banner">Synthetic sample evidence. Your notes and assumptions are user-entered.</p>}<div className="strategy-layout"><nav aria-label="Decision tools">{strategySections.map(([key,title])=><button key={key} aria-current={key===selected?'page':undefined} onClick={()=>setParams({tool:key})}>{title}</button>)}</nav><section key={id+selected} className="report-section"><h2>{strategySections.find(([k])=>k===selected)?.[1]||'Evidence connections'}</h2>{content}</section></div></>;
}
