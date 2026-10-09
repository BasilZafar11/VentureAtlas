import {useQuery} from '@tanstack/react-query';
import {Link,useParams} from 'react-router-dom';
import {api} from '../api/client';
import {AnalysisForm} from '../components/AnalysisForm';
import {lazy,useState} from 'react';
const ReportView=lazy(()=>import('../components/ReportView').then(m=>({default:m.ReportView})));
const researchQuestions = [
 {name:'Competition',question:'Who is already serving this market?',source:'Local businesses & reviews',description:'Explore nearby competitors, compare their ratings and see where customers find value.',next:'Look for a customer need the existing options leave unresolved.'},
 {name:'Demand',question:'Is interest growing, or just seasonal?',source:'Search interest over time',description:'Compare demand keywords and seasonal patterns before choosing when and where to launch.',next:'Check whether a spike reflects lasting interest or a short-lived event.'},
 {name:'Customers',question:'What do customers wish was better?',source:'Customer review themes',description:'Read recurring needs and complaints alongside the original evidence behind each theme.',next:'Turn a recurring complaint into an assumption you can test.'},
 {name:'Context',question:'What is changing around this opportunity?',source:'News & additional research',description:'Bring market news and research sources into the same investigation as your local evidence.',next:'Record what strengthens your idea, and what would change your mind.'},
];

export function VentureHome(){
 const [questionIndex,setQuestionIndex]=useState(0);
 const question=researchQuestions[questionIndex];
 return <div className="venture-landing">
  <section className="venture-hero" aria-labelledby="landing-title">
   <div className="venture-intro">
    <p className="venture-kicker">Market research for your next venture</p>
    <h1 id="landing-title">Know your market.<br/>Make your move.</h1>
    <p className="venture-lede">Explore competitors, understand demand, and turn market evidence into a clearer plan for your business.</p>
    <div className="venture-actions"><a className="primary" href="#start-research">Research a market</a><Link className="venture-report-link" to="/reports">Open saved reports</Link></div>
   </div>
   <section className="venture-brief" aria-label="Research guide">
    <div className="venture-brief-heading"><span>Inside your research</span><span className="venture-guide-label">Field guide</span></div>
    <div className="venture-lenses" role="group" aria-label="Choose a research topic">
     {researchQuestions.map((item,index)=><button key={item.name} type="button" aria-pressed={questionIndex===index} onClick={()=>setQuestionIndex(index)}>{item.name}</button>)}
    </div>
    <div className="venture-question" aria-live="polite" aria-atomic="true">
     <h2>{question.question}</h2><p>{question.description}</p>
     <dl><div><dt>Evidence to explore</dt><dd>{question.source}</dd></div><div><dt>Your next question</dt><dd>{question.next}</dd></div></dl>
    </div>
    <p className="venture-brief-note">A guide to the workflow. Start an analysis to see market results.</p>
   </section>
  </section>
  <section className="venture-method" aria-labelledby="method-title">
   <div><h2 id="method-title">Evidence before commitment.</h2><p>Keep the research and the reasoning together, from your first question to your next experiment.</p></div>
   <dl className="venture-method-list">
    <div><dt>Investigate the opportunity</dt><dd>Bring competitors, demand, customer needs and news into one market report.</dd></div>
    <div><dt>Challenge your assumptions</dt><dd>Inspect sources, compare reports and decide which evidence needs a closer look.</dd></div>
    <div><dt>Plan what to test</dt><dd>Connect your findings to assumptions, experiments and the decisions behind your launch.</dd></div>
   </dl>
  </section>
  <section className="venture-start" id="start-research" aria-labelledby="start-title">
   <div className="venture-start-copy"><h2 id="start-title">Every venture starts <br/>with a question.</h2><p>Which market are you considering? Choose a business category and location to begin.</p><div className="venture-sample-note"><h3>Want to try it first?</h3><p>The form starts with our Pune coworking example. Sample reports use clearly labeled synthetic data.</p></div><p className="venture-start-footnote">Search usage is shown in the planner before you begin.</p></div>
   <AnalysisForm/>
  </section>
 </div>;
}
export function VentureReport(){const {id=''}=useParams();const q=useQuery({queryKey:['report',id],queryFn:()=>api.get(id),refetchInterval:q=>q.state.data&&['queued','running'].includes(q.state.data.status)?1800:false});if(q.isPending)return <p role="status">Loading market report…</p>;if(q.isError)return <p role="alert">{q.error.message}</p>;const r=q.data;if(r.status!=='complete')return <section className="report-section"><h1>{r.status==='failed'?'Analysis stopped':'Building your market report'}</h1><p role="status">{r.status==='failed'?r.error_message:r.stage}</p><progress max={100} value={r.progress}/><Link to="/">Start an analysis</Link></section>;return <ReportView report={r}/>}
export function VentureReports(){const q=useQuery({queryKey:['recent-reports'],queryFn:api.recent});return <><h1>Saved market reports</h1>{q.isPending?<p>Loading…</p>:q.isError?<p role="alert">{q.error.message}</p>:<div className="research-evidence-list">{q.data.map(r=><article key={r.id}><h2><Link to={`/reports/${r.id}`}>{r.business_category} in {r.city}</Link></h2><p>{r.country} · {r.data_mode} · {r.overall_score}/100 · {new Date(r.created_at).toLocaleString()}</p></article>)}{!q.data.length&&<p>No saved reports. <Link to="/">Create the sample analysis.</Link></p>}</div>}</>}
