import {useEffect,useRef,useState} from 'react';
import {closeKeyPrompt,openKeyPrompt,offerQuotaKeys,personalKeysActive,setPersonalKeys} from '../api/providerKeys';
import {request} from '../api/client';
import '../styles/provider-keys.css';

export function ProviderKeysDialog(){
  const dialog=useRef<HTMLDialogElement>(null);
  const [reason,setReason]=useState(''),[serpapi,setSerpapi]=useState(''),[groq,setGroq]=useState(''),[show,setShow]=useState(false),[ai,setAi]=useState(false),[error,setError]=useState(''),[active,setActive]=useState(personalKeysActive);
  const [remaining,setRemaining]=useState<number|null>(null);
  const clear=()=>{setSerpapi('');setGroq('');setAi(false);setShow(false);setError('');setReason('');};
  useEffect(()=>{
    const prompt=(event:Event)=>{setReason((event as CustomEvent<string>).detail);dialog.current?.showModal();};
    const changed=()=>setActive(personalKeysActive());
    window.addEventListener('provider-key-prompt',prompt);window.addEventListener('provider-keys-changed',changed);
    return()=>{window.removeEventListener('provider-key-prompt',prompt);window.removeEventListener('provider-keys-changed',changed);closeKeyPrompt(false);};
  },[]);
  useEffect(()=>{
    let mounted=true;
    const refresh=async()=>{
      if(personalKeysActive())return;
      try{const allowance=await request<{remaining:number}>('/api/search-allowance');if(mounted){setRemaining(allowance.remaining);if(allowance.remaining===0)offerQuotaKeys();}}catch{if(mounted)setRemaining(null);}
    };
    void refresh();const timer=window.setInterval(()=>void refresh(),30000);
    return()=>{mounted=false;window.clearInterval(timer);};
  },[active]);
  function close(accepted=false){dialog.current?.close();clear();closeKeyPrompt(accepted);}
  function save(event:React.FormEvent){event.preventDefault();const values=[serpapi.trim(),ai?groq.trim():''];if(!values[0]||ai&&!values[1]||values.some(value=>value&&!/^[!-~]{16,256}$/.test(value))){setError('Enter a SerpApi key with 16–256 characters. When AI explanations are enabled, enter your Groq key too.');return;}setPersonalKeys({serpapi:values[0],groq:values[1]});close(true);}
  return <><div className="provider-key-control">{!active&&remaining!==null&&<span>{remaining}/20 hosted calls left today · resets midnight IST</span>}<button type="button" onClick={()=>void openKeyPrompt()}> {active?'Personal keys active · replace':'Use my API keys'}</button>{active&&<button type="button" onClick={()=>setPersonalKeys(null)}>Clear keys</button>}</div>
    <dialog ref={dialog} className="provider-key-dialog" aria-labelledby="provider-key-title" onCancel={event=>{event.preventDefault();close();}}>
      <form onSubmit={save}><h2 id="provider-key-title">{reason==='quota'?'Shared allowance cannot fund this search':'Use your own provider keys'}</h2>
        <p>You can use up to 20 hosted SerpApi calls per day, resetting at midnight India time. Signed-in accounts have their own allowance; guests on the same IP share one. A separate shared credit cap may run out sooner. Use your personal key to continue.</p>
        <p>Your keys pass through our backend to the providers for this search. They remain in page memory and are never saved to the database. Reloading clears them. Provider charges and limits apply to your account.</p>
        <label>SerpApi API key <span>(required)</span><input autoFocus type={show?'text':'password'} autoComplete="off" spellCheck={false} minLength={16} maxLength={256} required value={serpapi} onChange={event=>setSerpapi(event.target.value)}/></label>
        <label className="provider-key-checkbox"><input type="checkbox" checked={ai} onChange={event=>setAi(event.target.checked)}/>Enable AI explanations with my Groq key</label>
        {ai&&<label>Groq API key<input type={show?'text':'password'} autoComplete="off" spellCheck={false} minLength={16} maxLength={256} required value={groq} onChange={event=>setGroq(event.target.value)}/></label>}
        <label className="provider-key-checkbox"><input type="checkbox" checked={show} onChange={event=>setShow(event.target.checked)}/>Show keys</label>
        <p>Research reports use at most 8 search attempts. Market analyses use at most 30; extensions use at most 9 including retries. AI enrichment uses at most 2 Groq attempts per research report.</p>
        {error&&<p role="alert">{error}</p>}<div className="provider-key-actions"><button type="submit">Use my keys</button><button type="button" onClick={()=>{close();location.assign('/research-scope/reports/sample');}}>Open sample report</button><button type="button" onClick={()=>close()}>Cancel</button></div>
      </form>
    </dialog></>;
}
