import {describe,it,expect} from 'vitest';
import {reportDestinations,reportDestinationUrl,resolveReportDestination} from './reportSections';

describe('report navigation',()=>{
 it('round-trips every report section through its public URL',()=>{
  for(const section of reportDestinations){
   const url=new URL(reportDestinationUrl('saved-report',section),'https://example.com');
   expect(resolveReportDestination(url.pathname,url.search,url.hash).id).toBe(section.id);
  }
 });
 it('keeps legacy anchors and saved research run links usable',()=>{
  for(const [anchor,id] of Object.entries({maps:'competition_gap',trends:'demand',reviews:'unmet_need',news:'market_momentum',ads:'advertising_gap'})){
   expect(resolveReportDestination('/reports/id','',`#${anchor}`).id).toBe(id);
  }
  expect(resolveReportDestination('/reports/id/research','?tool=scholar&run=existing-run','').id).toBe('research-scholar');
  expect(resolveReportDestination('/reports/id/strategy','?tool=pitch','').area).toBe('Team & exports');
 });
 it('opens the overview for an unknown anchor and a valid tool for unknown tool names',()=>{
  expect(resolveReportDestination('/reports/id','','#missing').id).toBe('overview');
  expect(resolveReportDestination('/reports/id/research','?tool=missing','').tool).toBe('directions');
  expect(resolveReportDestination('/reports/id/strategy','?tool=missing','').tool).toBe('graph');
 });
});
