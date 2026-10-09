// Credentials live only in this page's memory and are sent only to paid search routes.
type Keys={serpapi:string;groq:string};
let keys:Keys|null=null;
let pending:Promise<boolean>|null=null;
let finish:((accepted:boolean)=>void)|null=null;
let offered=false;
export function personalKeysActive(){return keys!==null;}
export function personalGroqActive(){return !!keys?.groq;}
export function setPersonalKeys(value:Keys|null){keys=value;window.dispatchEvent(new Event('provider-keys-changed'));}
export function closeKeyPrompt(accepted:boolean){finish?.(accepted);finish=null;pending=null;}
export function openKeyPrompt(reason='manual'):Promise<boolean>{
  if(pending)return pending;
  pending=new Promise(resolve=>{finish=resolve;});
  const request=pending;
  window.dispatchEvent(new CustomEvent('provider-key-prompt',{detail:reason}));
  return request;
}
export function offerQuotaKeys(){if(!offered&&!keys){offered=true;void openKeyPrompt('quota');}}
export async function providerFetch(url:string,options:RequestInit={}){
  const target=new URL(url,location.origin),path=target.pathname;
  const apiOrigin=new URL(import.meta.env.VITE_API_URL||location.origin,location.origin).origin;
  const paid=target.origin===apiOrigin&&options.method==='POST'&&(/^\/api\/(novelty\/)?analyses$/.test(path)||/^\/api\/novelty\/analyses\/[^/]+\/refresh$/.test(path)||/^\/api\/analyses\/[^/]+\/research$/.test(path));
  const allowance=target.origin===apiOrigin&&path==='/api/search-allowance'&&(!options.method||options.method==='GET');
  const send=(body=options.body)=>{
    const headers=new Headers(options.headers);
    if((paid||allowance)&&!headers.has('Authorization')){
      try{const session=JSON.parse(sessionStorage.getItem('venture-session')||'null');if(session?.token)headers.set('Authorization',`Bearer ${session.token}`);}catch{/* Guest allowance applies when session storage is unavailable. */}
    }
    if(paid&&keys){headers.set('X-SerpApi-Key',keys.serpapi);if(keys.groq)headers.set('X-Groq-Key',keys.groq);}
    if(paid&&keys&&/\/refresh$/.test(path)&&body==null)body=JSON.stringify({use_groq:personalGroqActive()});
    const timeout=AbortSignal.timeout(20000);
    const signal=options.signal?AbortSignal.any([options.signal,timeout]):timeout;
    return fetch(url,{...options,body,headers,signal,redirect:paid?'error':options.redirect});
  };
  let response=await send();
  if(paid&&!response.ok){
    const error=await response.clone().json().catch(()=>null);
    const code=error?.error?.code;
    if(['DAILY_USER_LIMIT','SHARED_QUOTA_EXHAUSTED','PERSONAL_KEYS_REQUIRED'].includes(code)&&await openKeyPrompt(code==='PERSONAL_KEYS_REQUIRED'?'required':'quota')&&keys){
      let body=options.body;
      // Apply consent from this newly accepted dialog only to this retry.
      if(path==='/api/novelty/analyses'&&typeof body==='string'){
        try{const data=JSON.parse(body);if(data&&typeof data==='object'&&!Array.isArray(data))body=JSON.stringify({...data,use_groq:personalGroqActive()});}catch{/* Non-JSON bodies are left for server validation. */}
      }
      response=await send(body);
    }
  }
  return response;
}
