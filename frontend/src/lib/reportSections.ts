import {researchTools,toolKeys} from './researchTools';
import {strategySections} from './strategy';

export const reportAreas=['Overview','Market','Research','Strategy','Team & exports'] as const;
export type ReportArea=typeof reportAreas[number];
export type ReportDestination={id:string;title:string;area:ReportArea;panel:string;path?:'research'|'strategy';tool?:string};
const section=(id:string,title:string,area:ReportArea):ReportDestination=>({id,title,area,panel:id});
export const reportDestinations:ReportDestination[]=[
 section('overview','Summary','Overview'),
 section('competition_gap','Competitors','Market'),section('demand','Demand over time','Market'),
 section('unmet_need','Customer needs','Market'),section('market_momentum','News','Market'),
 section('advertising_gap','Advertising','Market'),section('hours-gaps','Opening hours','Market'),
 section('brand-competition','Brand concentration','Market'),section('reputation-changes','Reputation changes','Market'),
 section('review-matrix','Strengths & weaknesses','Market'),section('keyword-opportunities','Keyword opportunities','Market'),section('seasonality','Seasonality','Market'),
 ...toolKeys.map(tool=>({id:'research-'+tool,title:researchTools[tool].title,area:'Research' as const,panel:'research-sources',path:'research' as const,tool})),
 section('evidence-strength','Evidence quality','Research'),section('relevance-review','Review relevance','Research'),
 section('evidence','Evidence register','Research'),section('search-usage','Search usage','Research'),section('methodology','Methodology','Research'),
 section('opportunity-stress','Stress test','Strategy'),section('area-explorer','Service areas','Strategy'),
 section('concept-sandbox','Concept sandbox','Strategy'),section('break-even','Break-even calculator','Strategy'),
 section('validation-lab','Validation lab','Strategy'),section('decision-journal','Decision journal','Strategy'),section('priorities','Scoring priorities','Strategy'),
 ...strategySections.map(([tool,title])=>({id:'strategy-'+tool,title,area:(tool==='team'||tool==='pitch'?'Team & exports':'Strategy') as ReportArea,panel:'strategy-'+tool,path:'strategy' as const,tool})),
 section('notebook','Personal notebook & export','Team & exports'),
];
const aliases:Record<string,string>={maps:'competition_gap',trends:'demand',reviews:'unmet_need',news:'market_momentum',ads:'advertising_gap'};
export function resolveReportDestination(pathname:string,search:string,hash:string){
 const params=new URLSearchParams(search);
 if(pathname.endsWith('/research'))return reportDestinations.find(d=>d.path==='research'&&d.tool===(params.get('tool')||'directions'))||reportDestinations.find(d=>d.path==='research')!;
 if(pathname.endsWith('/strategy'))return reportDestinations.find(d=>d.path==='strategy'&&d.tool===(params.get('tool')||'graph'))||reportDestinations.find(d=>d.path==='strategy')!;
 const anchor=hash.replace(/^#/,'');
 return reportDestinations.find(d=>d.id===(aliases[anchor]||anchor))||reportDestinations[0];
}
export function reportDestinationUrl(reportId:string,d:ReportDestination){
 const base=`/reports/${encodeURIComponent(reportId)}`;
 return d.path?`${base}/${d.path}?tool=${d.tool}`:d.id==='overview'?base:`${base}#${d.id}`;
}
