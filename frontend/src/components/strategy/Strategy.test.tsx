import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {EvidenceGraph} from './EvidenceGraph';
import {Personas} from './Personas';
import {Offers} from './Offers';
import {Regulations} from './Regulations';
import {VenturePitch} from './VenturePitch';
import {conflicts,prioritizeExperiments,reportDigest,researchDigest} from '../../lib/strategy';
import type {Report} from '../../types/analysis';
import type {ResearchRun} from '../../types/research';
import fixture from '../../fixtures/report.json';
const report=fixture as Report;
beforeEach(()=>{const store=new Map();vi.stubGlobal('localStorage',{getItem:(k:string)=>store.get(k)||null,setItem:(k:string,v:string)=>store.set(k,v)})});
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.unstubAllGlobals()});
it('persists evidence-to-decision connections',()=>{
 const view=render(<EvidenceGraph report={report}/>);fireEvent.change(screen.getByLabelText('Your reasoning'),{target:{value:'Validate willingness to pay'}});fireEvent.click(screen.getAllByRole('checkbox')[0]);fireEvent.click(screen.getByText('Save connection'));view.unmount();render(<EvidenceGraph report={report}/>);expect(screen.getByRole('button',{name:'Finding: Validate willingness to pay'})).toBeInTheDocument();
});
it('does not invent conflicts when sources are unavailable',()=>{
 expect(conflicts({...report,sections:{},news:[],review_topics:[]})).toEqual([]);
});
it('flags opposite topic ratings with traceable excerpts',()=>{
 const r={...report,news:[],review_topics:[{topic:'Noise',mentions:2,competitor_count:2,repeated:true,excerpts:[{competitor:'A',rating:5,text:'Good',source_url:'https://example.org/a',published_at:null},{competitor:'B',rating:1,text:'Bad',source_url:'https://example.org/b',published_at:null}]}]};
 expect(conflicts(r).find(c=>c.id==='topic-Noise')?.links).toHaveLength(2);
});
it('persona hypotheses stay editable and persist user validation status',()=>{
 const view=render(<Personas report={report}/>);fireEvent.change(screen.getByLabelText('Audience hypothesis'),{target:{value:'People needing quiet'}});fireEvent.change(screen.getByLabelText('Need to validate'),{target:{value:'Quiet rooms for calls'}});fireEvent.click(screen.getByText('Save persona hypothesis'));fireEvent.change(screen.getByLabelText('Validation status'),{target:{value:'Interviewed'}});view.unmount();render(<Personas report={report}/>);expect(screen.getByLabelText('Validation status')).toHaveValue('Interviewed');
});
it('requires matching market conditions for a digest',()=>{
 expect(reportDigest(report,{...report,input:{...report.input,city:'Delhi'}}).compatible).toBe(false);
 expect(reportDigest(report,{...report,competitors:report.competitors.slice(1)}).lines.some(x=>x.includes('Not returned'))).toBe(true);
});
it('requires matching research inputs',()=>{
 const base={tool:'events',data_mode:'fixture',input:{tool:'events',query:'Pune'},batches:[]} as unknown as ResearchRun;
 expect(researchDigest(base,{...base,input:{tool:'events',query:'Delhi'}}).compatible).toBe(false);
});
it('keeps a greedy allocation within both budgets and excludes other currencies',()=>{
 const common={id:'a',name:'Interview',assumption:'Demand exists',impact:5,uncertainty:5,cost:100,hours:2,currency:'INR' as const,measure:'Five responses',result:''};
 const ranked=prioritizeExperiments([common,{...common,id:'b',cost:100},{...common,id:'usd',currency:'USD'}],150,3,'INR');expect(ranked.filter(r=>r.included)).toHaveLength(1);expect(ranked).toHaveLength(2);
 expect(prioritizeExperiments([{...common,cost:0},common],0,5,'INR').filter(r=>r.included)).toHaveLength(1);
});
it('saves sourced offers with terms and a verification date',()=>{
 const view=render(<Offers report={report}/>);fireEvent.change(screen.getByLabelText('Plan or package'),{target:{value:'Day pass'}});fireEvent.change(screen.getByLabelText('Source URL'),{target:{value:'https://example.org/plans'}});fireEvent.click(screen.getByText('Save offer'));view.unmount();render(<Offers report={report}/>);expect(screen.getByText(/— Day pass/)).toBeInTheDocument();expect(screen.getByText('Cancellation: Unknown')).toBeInTheDocument();
});
it('records regulatory requirements as unverified by default',()=>{
 render(<Regulations report={report}/>);fireEvent.change(screen.getByLabelText('Requirement to investigate'),{target:{value:'Premises permission'}});fireEvent.change(screen.getByLabelText('Official source URL'),{target:{value:'https://authority.example.org/requirements'}});fireEvent.click(screen.getByText('Save requirement'));expect(screen.getByText('Premises permission')).toBeInTheDocument();expect(screen.getByText(/Checked: Not recorded/)).toBeInTheDocument();
});
it('pitch preserves user edits and includes an explicit sample disclosure',()=>{
 const view=render(<VenturePitch report={report}/>);fireEvent.change(screen.getByLabelText('Customer problem'),{target:{value:'Customers need quiet rooms.'}});fireEvent.click(screen.getByText('Save pitch draft'));view.unmount();render(<VenturePitch report={report}/>);expect(screen.getByLabelText('Customer problem')).toHaveValue('Customers need quiet rooms.');expect(screen.getByText(/Synthetic demonstration data/)).toBeInTheDocument();
});

it('compares distinct results sharing a source URL without losing rows',()=>{
 const row=(title:string,detail:string)=>({id:title,title,detail,url:'https://example.org/search',meta:{},tags:[],image:null});
 const base={tool:'flights',data_mode:'fixture',created_at:'2026-10-01',input:{tool:'flights',query:'Pune'},batches:[{label:'Flights',rows:[row('Flight A','100'),row('Flight B','200')]}]} as unknown as ResearchRun;
 const later={...base,created_at:'2026-10-02',input:{query:'Pune',tool:'flights'} as ResearchRun['input'],batches:[{...base.batches[0],rows:[row('Flight A','150'),row('Flight B','200')]}]};
 expect(researchDigest(base,later).lines).toEqual(['Changed returned details: Flight A']);
 expect(researchDigest(later,base).compatible).toBe(false);
});
it('imports saved validation results and opens the pitch print workflow',()=>{
 localStorage.setItem(`venture-priorities-v1:${report.id}`,JSON.stringify([{id:'test',name:'Interview',assumption:'Demand exists',impact:5,uncertainty:4,cost:100,hours:2,currency:'INR',measure:'Five interested customers',result:'Two of five requested a trial'}]));
 const originalTitle=document.title;
 const print=vi.spyOn(window,'print').mockImplementation(()=>{expect(document.title).toBe(`${report.input.business_category} in ${report.input.city} · VentureAtlas pitch`)});
 render(<VenturePitch report={report}/>);fireEvent.click(screen.getByText('Import saved experiment results'));
 expect(screen.getByLabelText('Validation and uncertainties')).toHaveValue('Interview: Two of five requested a trial\nSuccess measure: Five interested customers');
 fireEvent.click(screen.getByText('Print or save pitch as PDF'));expect(print).toHaveBeenCalledOnce();expect(document.title).toBe(originalTitle);
});

it('exports a readable Markdown pitch with sample disclosure and references',()=>{
 let exported='';
 vi.stubGlobal('Blob',class {constructor(parts:unknown[]){exported=parts.join('')}});
 vi.stubGlobal('URL',{createObjectURL:()=> 'blob:pitch',revokeObjectURL:vi.fn()});
 vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{});
 render(<VenturePitch report={report}/>);fireEvent.click(screen.getByText('Download editable Markdown'));
 expect(exported).toContain('\n\n## Evidence references\n\n');
 expect(exported).toContain('Synthetic sample');expect(exported).toContain('Source report:');
 expect(exported).not.toContain('\\n');
});
