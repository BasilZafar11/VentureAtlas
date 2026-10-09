import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {closeKeyPrompt,openKeyPrompt,personalKeysActive,providerFetch,setPersonalKeys} from './providerKeys';
import {noveltyApi,workspaceCapabilities} from './novelty';

const credentials={serpapi:'personal-serpapi-key-123456',groq:'personal-groq-key-123456'};
const json=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json'}});
let promptListener:EventListener|undefined;
beforeEach(()=>{closeKeyPrompt(false);setPersonalKeys(null);vi.stubEnv('VITE_API_URL',location.origin);vi.stubGlobal('fetch',vi.fn().mockResolvedValue(json({ok:true})));});
afterEach(()=>{if(promptListener)window.removeEventListener('provider-key-prompt',promptListener);promptListener=undefined;closeKeyPrompt(false);setPersonalKeys(null);vi.restoreAllMocks();vi.unstubAllGlobals();vi.unstubAllEnvs();});
function acceptPrompt(accepted=true){promptListener=()=>{if(accepted)setPersonalKeys(credentials);closeKeyPrompt(accepted);};window.addEventListener('provider-key-prompt',promptListener);}

describe('temporary provider credentials',()=>{
  it('uses account identity only on own paid and allowance routes',async()=>{
    vi.stubGlobal('sessionStorage',{getItem:vi.fn(()=>JSON.stringify({token:'dummy-session',username:'founder'}))});
    for(const path of ['/api/analyses','/api/search-allowance','https://unrelated.example/api/analyses']){
      await providerFetch(path,{method:path.endsWith('allowance')?'GET':'POST',body:path.endsWith('allowance')?undefined:'{}'});
    }
    const headers=vi.mocked(fetch).mock.calls.map(([,options])=>new Headers(options!.headers));
    expect(headers[0].get('Authorization')).toBe('Bearer dummy-session');
    expect(headers[1].get('Authorization')).toBe('Bearer dummy-session');
    expect(headers[2].has('Authorization')).toBe(false);
  });
  it('offers a personal key when this user exhausts the daily allowance',async()=>{
    vi.mocked(fetch).mockResolvedValueOnce(json({error:{code:'DAILY_USER_LIMIT'}},429)).mockResolvedValueOnce(json({id:'queued'}));
    acceptPrompt();
    const response=await providerFetch('/api/analyses',{method:'POST',body:'{}'});
    expect(response.ok).toBe(true);
    expect(new Headers(vi.mocked(fetch).mock.calls[1][1]!.headers).get('X-SerpApi-Key')).toBe(credentials.serpapi);
  });
  it('applies current personal AI consent when refreshing a report',async()=>{
    setPersonalKeys(credentials);
    await providerFetch('/api/novelty/analyses/report/refresh',{method:'POST'});
    expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]!.body as string)).toEqual({use_groq:true});
    setPersonalKeys({...credentials,groq:''});
    await providerFetch('/api/novelty/analyses/report/refresh',{method:'POST'});
    expect(JSON.parse(vi.mocked(fetch).mock.calls[1][1]!.body as string)).toEqual({use_groq:false});
  });
  it.each<[string,string,boolean]>([
    ['/api/novelty/analyses','POST',true],['/api/analyses','POST',true],
    ['/api/novelty/analyses/report/refresh','POST',true],['/api/analyses/report/research','POST',true],
    ['/api/novelty/analyses','GET',false],['/api/demo-status','GET',false],
    ['/api/novelty/analyses/report/workspace/rotate','POST',false],
    ['/api/novelty/analyses/report/document-review','POST',false],
    ['/api/venture/sessions','POST',false],['/api/research-integrity/access','GET',false],
    ['https://unrelated.example/api/novelty/analyses','POST',false],
  ])('confines keys to the paid endpoint %s %s',async(path,method,paid)=>{
    setPersonalKeys(credentials);
    await providerFetch(path,{method,body:method==='POST'?'{}':undefined});
    const options=vi.mocked(fetch).mock.calls[0][1]!;
    const headers=new Headers(options.headers);
    expect(headers.get('X-SerpApi-Key')).toBe(paid?credentials.serpapi:null);
    expect(headers.get('X-Groq-Key')).toBe(paid?credentials.groq:null);
    if(paid)expect(options.redirect).toBe('error');
    expect(String(vi.mocked(fetch).mock.calls[0][0])).not.toContain(credentials.serpapi);
    expect(String(options.body||'')).not.toContain(credentials.serpapi);
  });
  it('keeps keys out of browser storage and clears them for following searches',async()=>{
    const store=vi.spyOn(Storage.prototype,'setItem');
    setPersonalKeys(credentials);expect(personalKeysActive()).toBe(true);
    await providerFetch('/api/novelty/analyses',{method:'POST',body:'{}'});
    setPersonalKeys(null);expect(personalKeysActive()).toBe(false);
    await providerFetch('/api/novelty/analyses',{method:'POST',body:'{}'});
    expect(store).not.toHaveBeenCalled();
    expect(new Headers(vi.mocked(fetch).mock.calls[1][1]!.headers).has('X-SerpApi-Key')).toBe(false);
  });
  it('retries exhausted hosted searches once with personal keys and accepted AI consent',async()=>{
    vi.mocked(fetch).mockResolvedValueOnce(json({error:{code:'SHARED_QUOTA_EXHAUSTED'}},429));
    acceptPrompt();
    await providerFetch('/api/novelty/analyses',{method:'POST',body:JSON.stringify({title:'Study',use_groq:false})});
    expect(fetch).toHaveBeenCalledTimes(2);
    const first=vi.mocked(fetch).mock.calls[0][1]!,retry=vi.mocked(fetch).mock.calls[1][1]!;
    expect(new Headers(first.headers).has('X-SerpApi-Key')).toBe(false);
    expect(new Headers(retry.headers).get('X-SerpApi-Key')).toBe(credentials.serpapi);
    expect(JSON.parse(retry.body as string)).toEqual({title:'Study',use_groq:true});
    await providerFetch('/api/novelty/analyses',{method:'POST',body:JSON.stringify({use_groq:false})});
    expect(JSON.parse(vi.mocked(fetch).mock.calls[2][1]!.body as string).use_groq).toBe(false);
  });
  it('returns the quota response without spending another attempt when cancelled',async()=>{
    const rejected=json({error:{code:'SHARED_QUOTA_EXHAUSTED'}},429);
    vi.mocked(fetch).mockResolvedValueOnce(rejected);acceptPrompt(false);
    expect(await providerFetch('/api/analyses',{method:'POST',body:'{}'})).toBe(rejected);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('does not retry invalid personal keys or server-busy responses with hosted credentials',async()=>{
    setPersonalKeys(credentials);
    const prompt=vi.fn();promptListener=prompt;window.addEventListener('provider-key-prompt',prompt);
    for(const code of ['PROVIDER_AUTH_ERROR','SERVER_BUSY']){
      const rejected=json({error:{code}},429);vi.mocked(fetch).mockResolvedValueOnce(rejected);
      expect(await providerFetch('/api/novelty/analyses',{method:'POST',body:'{}'})).toBe(rejected);
    }
    expect(fetch).toHaveBeenCalledTimes(2);expect(prompt).not.toHaveBeenCalled();
  });
  it('propagates caller cancellation into the request timeout signal',async()=>{
    const controller=new AbortController();
    await providerFetch('/api/demo-status',{signal:controller.signal});
    const signal=vi.mocked(fetch).mock.calls[0][1]!.signal!;
    expect(signal.aborted).toBe(false);controller.abort();expect(signal.aborted).toBe(true);
  });
  it('shares one prompt between waiting requests and resolves immediate dismissal',async()=>{
    const prompt=vi.fn();promptListener=prompt;window.addEventListener('provider-key-prompt',prompt);
    const first=openKeyPrompt(),second=openKeyPrompt();expect(second).toBe(first);expect(prompt).toHaveBeenCalledTimes(1);
    closeKeyPrompt(false);await expect(first).resolves.toBe(false);
  });
  it('rotates with the explicitly supplied owner and preserves fresh links when storage is blocked',async()=>{
    const previous=location.href;
    history.replaceState(history.state,'','/reports/rotation-test#owner=revoked-owner');
    const store=vi.fn(()=>{throw new DOMException('Blocked','SecurityError');});
    vi.stubGlobal('localStorage',{getItem:vi.fn(()=>null),setItem:store,removeItem:vi.fn(),clear:vi.fn()});
    const change=vi.fn();window.addEventListener('workspace-capabilities-changed',change);
    vi.mocked(fetch).mockResolvedValueOnce(json({owner_token:'new-owner',review_token:'new-reviewer',workspace:{comments:[],alerts:[],watched:false,latest_report_id:null}}));
    try{
      const result=await noveltyApi.createWorkspace('rotation-test','typed-owner');
      expect(new Headers(vi.mocked(fetch).mock.calls[0][1]!.headers).get('X-Review-Token')).toBe('typed-owner');
      expect(result.owner_token).toBe('new-owner');expect(location.hash).toBe('#owner=new-owner');
      expect(workspaceCapabilities('rotation-test')).toEqual({owner:'new-owner',reviewer:'new-reviewer',token:'new-owner'});
      expect((change.mock.calls[0][0] as CustomEvent<string>).detail).toBe('rotation-test');
      expect(store).toHaveBeenCalled();
    }finally{window.removeEventListener('workspace-capabilities-changed',change);history.replaceState(history.state,'',previous);}
  });
});
