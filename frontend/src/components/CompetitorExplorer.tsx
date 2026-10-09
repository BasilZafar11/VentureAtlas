import {useState} from 'react';
import type {Competitor,Report,Topic} from '../types/analysis';
import {CompetitorMap} from './CompetitorMap';
import {ReportPagination,useReportPagination} from './ReportPagination';

export function topicMatches(place:Competitor,topic:Topic){
 const matches=topic.competitors??topic.excerpts;
 return matches.some(match=>match.data_id&&place.data_id?match.data_id===place.data_id:match.competitor===place.name);
}
export function filterCompetitors(places:Competitor[],rating:number,reviews:number,topic?:Topic){
 return places.filter(p=>(rating===0||(p.rating!==null&&p.rating>=rating))&&p.review_count>=reviews&&(!topic||topicMatches(p,topic)));
}
function SourceLink({url,children}:{url:string|null;children:React.ReactNode}){
 return url&&/^https?:\/\//.test(url)?<a href={url} target="_blank" rel="noopener noreferrer">{children}<span className="sr-only"> (opens in a new tab)</span></a>:<span>{children}</span>;
}
export function CompetitorExplorer({report}:{report:Report}){
 const [rating,setRating]=useState(0),[reviews,setReviews]=useState(0),[topicName,setTopic]=useState('');
 const selected=report.review_topics.find(t=>t.topic===topicName);
 const places=filterCompetitors(report.competitors,rating,reviews,selected);
 const pagination=useReportPagination(places,10,`${rating}:${reviews}:${topicName}`);
 const mapped=places.filter(p=>p.latitude!==null&&p.longitude!==null).length;
 return <section className="report-section" id="competition_gap">
  <div className="section-heading"><div><h2>The competitive landscape</h2><p>Explore the businesses visible in this city’s search sample.</p></div><span className="status">{report.sections.maps.status}</span></div>
  <div className="competitor-filters"><label>Minimum rating<select aria-label="Minimum rating" value={rating} onChange={e=>setRating(Number(e.target.value))}><option value="0">Any rating, including unrated</option>{[3,3.5,4,4.5].map(n=><option key={n} value={n}>{n}+ stars</option>)}</select></label>
  <label>Minimum review count<select aria-label="Minimum review count" value={reviews} onChange={e=>setReviews(Number(e.target.value))}>{[0,50,100,200,500].map(n=><option key={n} value={n}>{n===0?'Any review count':`${n}+ reviews`}</option>)}</select></label>
  <label>Complaint topic<select aria-label="Complaint topic" value={topicName} onChange={e=>setTopic(e.target.value)}><option value="">All topics</option>{report.review_topics.map(t=><option key={t.topic} value={t.topic}>{t.topic}</option>)}</select></label>
  <button className="secondary" onClick={()=>{setRating(0);setReviews(0);setTopic('')}}>Reset filters</button></div>
  <p role="status">Showing {places.length} of {report.competitors.length} competitors · {mapped} with map coordinates.</p>
  <p className="hint">The map shows all filtered competitors; the table shows ten per page. Saved scores stay unchanged. One search page is not a market census. No match does not prove an area is underserved.</p>
  {selected&&<p className="notice">Complaint matches use sampled negative reviews. Businesses without matching sampled evidence are excluded, not confirmed complaint-free.{!selected.competitors&&' This older report only stores representative excerpts; topic filtering is limited to those excerpts.'}</p>}
  {places.length?<><CompetitorMap key={places.map(p=>p.data_id||p.rank).join('|')} competitors={places}/><div className="table-scroll"><table><caption className="sr-only">Filtered competitor names, ratings, review volumes and addresses</caption><thead><tr><th>Competitor</th><th>Rating</th><th>Reviews</th><th>Location</th><th>Website</th></tr></thead><tbody>{pagination.items.map(c=><tr key={c.rank}><td><span className="rank">{c.rank}</span><SourceLink url={c.source_url}>{c.name}</SourceLink></td><td>{c.rating??'Unrated'}{c.rating!==null&&' / 5'}</td><td>{c.review_count.toLocaleString()}</td><td>{c.address??'Unavailable'}</td><td>{c.website?<SourceLink url={c.website}>Visit site</SourceLink>:'Unavailable'}</td></tr>)}</tbody></table></div><ReportPagination {...pagination} label="competitors"/></>:<p className="empty">{report.competitors.length?'No competitors match these filters. Lower the thresholds or reset filters to see the full sample.':'No competitors were returned. This is insufficient data, not proof of an empty market.'}</p>}
  <p className="source">Source: Google Maps via SerpApi; complaint topics from sampled Google Maps Reviews. {report.data_mode==='fixture'&&'All observations in this report are synthetic.'}</p>
 </section>;
}
