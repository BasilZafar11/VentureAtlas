import {useState} from 'react';
export function useReportPagination<T>(items:T[],size=10,filterKey=''){
 const [selection,setSelection]=useState({page:1,key:filterKey});
 const pages=Math.max(1,Math.ceil(items.length/size));
 const page=Math.min(selection.key===filterKey?selection.page:1,pages);
 return {items:items.slice((page-1)*size,page*size),page,pages,total:items.length,size,setPage:(page:number)=>setSelection({page:Math.max(1,Math.min(page,pages)),key:filterKey})};
}
export function ReportPagination({page,pages,total,size,setPage,label}:{page:number;pages:number;total:number;size:number;setPage:(page:number)=>void;label:string}){
 if(!total)return null;
 function turnPage(next:number,button:HTMLButtonElement){
  setPage(next);
  button.closest('.report-section')?.scrollIntoView?.({block:'start',behavior:'instant'});
 }
 return <nav className="report-pagination" aria-label={`${label} pages`}><p aria-live="polite">Showing {(page-1)*size+1}–{Math.min(page*size,total)} of {total} {label}</p>{pages>1&&<div><button type="button" className="secondary" disabled={page===1} onClick={event=>turnPage(page-1,event.currentTarget)}>Previous</button><span>Page {page} of {pages}</span><button type="button" className="secondary" disabled={page===pages} onClick={event=>turnPage(page+1,event.currentTarget)}>Next</button></div>}</nav>;
}
