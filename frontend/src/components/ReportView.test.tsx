import {createMemoryRouter,RouterProvider} from 'react-router-dom';
import {render as testingRender,screen,cleanup,fireEvent,act} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
const render=(ui:React.ReactNode)=>testingRender(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>);
import {afterEach,beforeEach,describe,it,expect,vi} from 'vitest';
import {ReportView} from './ReportView';
import {inputSchema,example} from './AnalysisForm';
import fixture from '../fixtures/report.json';
import type {Report} from '../types/analysis';
import type {ResearchRun} from '../types/research';
vi.mock('./CompetitorMap',()=>({CompetitorMap:()=> <div>Competitor map</div>}));
vi.mock('./DemandChart',()=>({DemandChart:()=> <div>Demand chart</div>}));
vi.mock('./ServiceAreaMap',()=>({default:()=> <div>Service area map</div>}));
vi.mock('../api/client',()=>({api:{get:vi.fn(()=>Promise.resolve(fixture))},ApiError:class extends Error{},request:vi.fn()}));
vi.mock('../api/research',()=>({researchApi:{list:vi.fn(()=>Promise.resolve([])),get:vi.fn(),create:vi.fn()}}));
beforeEach(()=>{vi.spyOn(window,'scrollTo').mockImplementation(()=>{})});
afterEach(()=>{cleanup();vi.restoreAllMocks()});
function workspace(path='',report=fixture as Report){
 const router=createMemoryRouter([{path:'/reports/:id',element:<ReportView report={report}/>,children:[{path:'research',element:null},{path:'strategy',element:null}]},{path:'/compare',element:<h1>Compare destination</h1>}],{initialEntries:[`/reports/${report.id}${path}`]});
 render(<RouterProvider router={router}/>);
 return router;
}
describe('report',()=>{
 it('starts with a concise overview and opens evidence on demand',async()=>{
  workspace();expect(screen.getByText('Sample report')).toBeInTheDocument();
  expect(screen.queryByRole('heading',{name:'The competitive landscape'})).not.toBeInTheDocument();
  expect(screen.queryByRole('heading',{name:'Evidence register'})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Market'}));
  expect(await screen.findByRole('heading',{name:'The competitive landscape'})).toBeVisible();
  expect(screen.getAllByText('Demo River Workspace').length).toBeGreaterThan(0);
  fireEvent.change(screen.getByLabelText('Report area'),{target:{value:'Research'}});
  fireEvent.change(screen.getByLabelText('Section'),{target:{value:'evidence'}});
  expect(await screen.findByRole('heading',{name:'Evidence register'})).toBeVisible();
  fireEvent.click(screen.getByRole('link',{name:'Methodology'}));
  expect(screen.getByRole('heading',{name:'Methodology & limitations'})).toBeVisible();
 });
 it('opens legacy news anchors and keeps failure explanations in their section',async()=>{
  const r=structuredClone(fixture) as Report;r.news=[];r.advertising=[];r.review_topics=[];r.sections.news={status:'failed',count:0};r.warnings=['News: unavailable'];
  workspace('#news',r);expect(screen.getByText('News: unavailable')).toBeVisible();
  expect(screen.getByText('Market news is unavailable. Momentum uses a neutral score.')).toBeVisible();
  fireEvent.click(screen.getByRole('link',{name:'Advertising'}));
  expect(screen.getByText(/No reliable active advertiser match is available/)).toBeVisible();
  expect(screen.getByText('Market news is unavailable. Momentum uses a neutral score.')).not.toBeVisible();
 });
 it('preserves calculator inputs across sections and browser history',async()=>{
  const router=workspace('#break-even');
  fireEvent.change(screen.getByLabelText('Monthly rent'),{target:{value:'32000'}});
  fireEvent.click(screen.getByRole('button',{name:'Research'}));
  expect(router.state.location.pathname).toContain('/research');
  await act(()=>router.navigate(-1));
  expect(screen.getByLabelText('Monthly rent')).toHaveValue(32000);
  await act(()=>router.navigate(1));
  expect(await screen.findByRole('heading',{name:'Travel-time catchments'})).toBeVisible();
 });
 it('warns before leaving edited inputs and allows staying in the report',async()=>{
  workspace('#break-even');fireEvent.change(screen.getByLabelText('Monthly rent'),{target:{value:'32000'}});
  fireEvent.click(screen.getByRole('link',{name:'Compare report'}));
  expect(await screen.findByRole('alertdialog')).toBeVisible();
  fireEvent.keyDown(screen.getByRole('alertdialog'),{key:'Escape'});
  expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('link',{name:'Compare report'}));
  fireEvent.click(screen.getByRole('button',{name:'Stay in report'}));
  expect(screen.getByLabelText('Monthly rent')).toHaveValue(32000);
  fireEvent.click(screen.getByRole('link',{name:'Compare report'}));fireEvent.click(screen.getByRole('button',{name:'Leave report'}));
  expect(await screen.findByRole('heading',{name:'Compare destination'})).toBeVisible();
 });
 it('paginates source records and resets the page when filtering',async()=>{
  const r=structuredClone(fixture) as Report;r.evidence=Array.from({length:25},(_,i)=>({...r.evidence[0],id:`source-${i}`,title:`Evidence item ${i}`}));
  workspace('#evidence',r);expect(screen.getByText('Showing 1–10 of 25 source records')).toBeVisible();
  fireEvent.click(screen.getByRole('button',{name:'Next'}));expect(screen.getByText('Showing 11–20 of 25 source records')).toBeVisible();
  fireEvent.change(screen.getByLabelText('Search source records'),{target:{value:'Evidence item 24'}});
  expect(screen.getByText('Evidence item 24')).toBeVisible();expect(screen.getByText('Showing 1–1 of 1 source records')).toBeVisible();
 });
 it('keeps separate research form drafts without starting searches',async()=>{
  workspace('/research?tool=scholar');
  const topic=await screen.findByLabelText('Research topic');fireEvent.change(topic,{target:{value:'A topic I am still editing'}});
  fireEvent.click(screen.getByRole('link',{name:'Customer-question discovery'}));
  await screen.findByLabelText('Search phrase');
  fireEvent.click(screen.getByRole('link',{name:'Research evidence shelf'}));
  expect(screen.getByLabelText('Research topic')).toHaveValue('A topic I am still editing');
  const {researchApi}=await import('../api/research');expect(researchApi.create).not.toHaveBeenCalled();
 });
 it('keeps unsaved observations when switching saved research runs',async()=>{
  const {researchApi}=await import('../api/research');
  const makeRun=(id:string):ResearchRun=>({id,tool:'scholar',status:'complete',created_at:'2026-10-09',data_mode:'fixture',input:{tool:'scholar',query:'Workplaces'},planned_requests:1,completed_requests:1,sample_notice:'Synthetic',batches:[{label:'First',status:'complete',message:'',source_url:null,rows:[{id:'row-'+id,title:'Paper '+id,url:null,detail:'',meta:{},tags:[],image:null}]}],usage:{mode:'fixture',logical_requests:{},provider_attempts:{},total_requests:1,total_provider_attempts:0,billing_note:''}});
  const runs=[makeRun('first'),makeRun('second')];
  vi.mocked(researchApi.list).mockResolvedValue(runs);
  vi.mocked(researchApi.get).mockImplementation(async(_id,run)=>runs.find(item=>item.id===run)!);
  workspace('/research?tool=scholar&run=first');
  fireEvent.change(await screen.findByLabelText('Your observations'),{target:{value:'An unsaved observation'}});
  fireEvent.change(await screen.findByLabelText('Open a saved run'),{target:{value:'second'}});
  await screen.findByText('Paper second');
  fireEvent.change(screen.getByLabelText('Open a saved run'),{target:{value:'first'}});
  expect(await screen.findByDisplayValue('An unsaved observation')).toBeVisible();
 });
 it('paginates competitors and resets pagination after changing filters',async()=>{
  const r=structuredClone(fixture) as Report;
  r.competitors=Array.from({length:23},(_,i)=>({...r.competitors[0],rank:i+1,name:`Competitor ${i+1}`,rating:i===22?5:3}));
  workspace('#competition_gap',r);
  expect(await screen.findByText('Showing 1–10 of 23 competitors')).toBeVisible();
  fireEvent.click(screen.getByRole('button',{name:'Next'}));
  expect(screen.getByText('Showing 11–20 of 23 competitors')).toBeVisible();
  fireEvent.change(screen.getByLabelText('Minimum rating'),{target:{value:'4.5'}});
  expect(screen.getByText('Showing 1–1 of 1 competitors')).toBeVisible();
  expect(screen.getByText('Competitor 23')).toBeVisible();
 });
 it('validates the demo and rejects missing, repeated or too many keywords',()=>{expect(inputSchema.safeParse({...example,refresh:false}).success).toBe(true);for(const keywords of [[],['aa','AA'],['a','b','c','d','e','f']])expect(inputSchema.safeParse({...example,keywords,refresh:false}).success).toBe(false)});
});
