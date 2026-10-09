import {createContext,Suspense,useContext,useEffect,useLayoutEffect,useRef,useState,type ReactNode} from 'react';
import {Link,useLocation,useNavigate,useBlocker,UNSAFE_DataRouterContext} from 'react-router-dom';
import {reportAreas,reportDestinations,reportDestinationUrl,resolveReportDestination,type ReportArea} from '../lib/reportSections';
import '../styles/report-workspace.css';

const ActivePanel=createContext('overview');
export function ReportPanel({id,children}:{id:string;children:ReactNode}){
 const active=useContext(ActivePanel)===id;
 return <RetainedContent active={active}>{children}</RetainedContent>;
}
export function RetainedContent({active,children}:{active:boolean;children:ReactNode}){
 const [visited,setVisited]=useState(active);
 useEffect(()=>{if(active)setVisited(true)},[active]);
 return active||visited?<div className="report-panel" hidden={!active}><Suspense fallback={<p role="status">Loading section…</p>}>{children}</Suspense></div>:null;
}
function WorkspaceExitGuard({dirty,reportId}:{dirty:boolean;reportId:string}){
 const base=`/reports/${encodeURIComponent(reportId)}`;
 const blocker=useBlocker(({nextLocation})=>dirty&&nextLocation.pathname!==base&&!nextLocation.pathname.startsWith(base+'/'));
 return blocker.state==='blocked'?<div className="workspace-exit-backdrop"><div className="workspace-exit-dialog" role="alertdialog" aria-modal="true" aria-labelledby="exit-title" aria-describedby="exit-description" onKeyDown={event=>{
  if(event.key==='Escape'){event.preventDefault();blocker.reset()}
  if(event.key==='Tab'){
   const buttons=event.currentTarget.querySelectorAll('button');
   const first=buttons[0],last=buttons[buttons.length-1];
   if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}
   else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}
  }
 }}><h2 id="exit-title">Leave this report?</h2><p id="exit-description">You changed inputs in this workspace. Save or export any drafts you want to keep before leaving.</p><div className="report-actions"><button autoFocus className="primary" onClick={()=>blocker.reset()}>Stay in report</button><button className="secondary" onClick={()=>blocker.proceed()}>Leave report</button></div></div></div>:null;
}

export function ReportWorkspace({reportId,children}:{reportId:string;children:ReactNode}){
 const location=useLocation(),navigate=useNavigate();
 const selected=resolveReportDestination(location.pathname,location.search,location.hash);
 const sections=reportDestinations.filter(d=>d.area===selected.area);
 const content=useRef<HTMLDivElement>(null),positions=useRef(new Map<string,number>());
 const previous=useRef(selected.id),lastScroll=useRef(0);
 const [dirty,setDirty]=useState(false);
 const dataRouter=useContext(UNSAFE_DataRouterContext);
 useEffect(()=>{
  const record=()=>{lastScroll.current=window.scrollY};
  record();
  window.addEventListener('scroll',record,{passive:true});
  return ()=>window.removeEventListener('scroll',record);
 },[]);
 useLayoutEffect(()=>{
  if(previous.current===selected.id)return;
  positions.current.set(previous.current,lastScroll.current);
  previous.current=selected.id;
  const frame=requestAnimationFrame(()=>{
   const offset=window.innerWidth<=760?120:24;
   const top=positions.current.get(selected.id)??Math.max(0,(content.current?.getBoundingClientRect().top||0)+window.scrollY-offset);
   window.scrollTo({top,behavior:'instant'});
   lastScroll.current=top;
   content.current?.focus({preventScroll:true});
  });
  return ()=>cancelAnimationFrame(frame);
 },[selected.id]);
 useEffect(()=>{
  if(!dirty)return;
  const warn=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue=''};
  window.addEventListener('beforeunload',warn);
  return ()=>window.removeEventListener('beforeunload',warn);
 },[dirty]);
 function chooseArea(area:ReportArea){navigate(reportDestinationUrl(reportId,reportDestinations.find(d=>d.area===area)!))}
 return <div className="report-workspace" onChangeCapture={event=>{if(!(event.target as HTMLElement).closest('.competitor-filters,.report-mobile-navigation,.report-evidence-filter'))setDirty(true)}}>
  {dataRouter&&<WorkspaceExitGuard dirty={dirty} reportId={reportId}/>}
  <aside className="report-sidebar">
   <nav aria-label="Report areas">{reportAreas.map(area=><button key={area} aria-current={selected.area===area?'page':undefined} onClick={()=>chooseArea(area)}>{area}</button>)}</nav>
   <nav className="report-section-nav" aria-label={`${selected.area} sections`}>{sections.map(d=><Link key={d.id} to={reportDestinationUrl(reportId,d)} aria-current={selected.id===d.id?'page':undefined}>{d.title}</Link>)}</nav>
  </aside>
  <div className="report-mobile-navigation">
   <label>Report area<select value={selected.area} onChange={e=>chooseArea(e.target.value as ReportArea)}>{reportAreas.map(area=><option key={area}>{area}</option>)}</select></label>
   <label>Section<select value={selected.id} onChange={e=>navigate(reportDestinationUrl(reportId,reportDestinations.find(d=>d.id===e.target.value)!))}>{sections.map(d=><option key={d.id} value={d.id}>{d.title}</option>)}</select></label>
  </div>
  <div className="report-workspace-content" ref={content} tabIndex={-1} aria-label={`${selected.area}: ${selected.title}`}>
   <p className="report-breadcrumb">{selected.area} / {selected.title}</p>
   <ActivePanel.Provider value={selected.panel}>{children}</ActivePanel.Provider>
  </div>
 </div>;
}
