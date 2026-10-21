export const DEFAULT_PRIVACY=Object.freeze({
  privacy_mode:true,
  mask_prompts:true,
  blur_media:true,
  quick_hide:true,
  idle_lock_seconds:30,
  require_unlock_on_resume:true,
  neutral_project_names:true,
});

const PRIVATE_KINDS=new Set(['prompt','source','result','gallery']);

export function createPrivacyController({documentRef=globalThis.document,settings={}}={}){
  let prefs={...DEFAULT_PRIVACY,...settings};
  let locked=false;
  let quickHidden=false;
  const revealed=new Set();
  const listeners=new Set();
  const cleanups=[];
  let idleTimer=null;

  const snapshot=()=>({settings:{...prefs},locked,quickHidden,revealed:new Set(revealed)});
  const emit=()=>{const value=snapshot();for(const listener of listeners)listener(value);};
  const concealAll=()=>{revealed.clear();emit();};
  const scheduleIdle=()=>{
    if(idleTimer)clearTimeout(idleTimer);
    const seconds=Number(prefs.idle_lock_seconds);
    if(!prefs.privacy_mode||!Number.isFinite(seconds)||seconds<=0)return;
    idleTimer=setTimeout(()=>{revealed.clear();locked=true;emit();},seconds*1000);
  };
  const activity=()=>{if(!locked&&!quickHidden)scheduleIdle();};

  const visibilityHandler=()=>{
    if(!documentRef?.hidden)return;
    revealed.clear();
    if(prefs.require_unlock_on_resume)locked=true;
    emit();
  };
  documentRef?.addEventListener?.('visibilitychange',visibilityHandler);
  if(documentRef?.removeEventListener)cleanups.push(()=>documentRef.removeEventListener('visibilitychange',visibilityHandler));

  for(const type of ['pointerdown','keydown','touchstart']){
    const handler=()=>activity();
    documentRef?.addEventListener?.(type,handler,{passive:true});
    if(documentRef?.removeEventListener)cleanups.push(()=>documentRef.removeEventListener(type,handler));
  }
  scheduleIdle();

  const isHidden=kind=>{
    if(!PRIVATE_KINDS.has(kind))return false;
    if(!prefs.privacy_mode)return false;
    if(locked||quickHidden)return true;
    const masks=kind==='prompt'?prefs.mask_prompts:prefs.blur_media;
    return Boolean(masks&&!revealed.has(kind));
  };

  const reveal=kind=>{
    if(!PRIVATE_KINDS.has(kind)||locked||quickHidden)return;
    revealed.add(kind);scheduleIdle();emit();
  };
  const conceal=kind=>{revealed.delete(kind);emit();};
  const unlock=()=>{locked=false;quickHidden=false;revealed.clear();scheduleIdle();emit();};
  const lock=()=>{revealed.clear();locked=true;emit();};
  const quickHide=()=>{revealed.clear();quickHidden=true;locked=true;emit();};
  const setSettings=next=>{prefs={...prefs,...next};if(!prefs.privacy_mode){locked=false;quickHidden=false;revealed.clear();}scheduleIdle();emit();};
  const subscribe=listener=>{listeners.add(listener);return()=>listeners.delete(listener);};
  const bindHold=(element,kind)=>{
    const show=event=>{event?.preventDefault?.();reveal(kind);};
    const hide=()=>conceal(kind);
    const events=[['pointerdown',show],['pointerup',hide],['pointercancel',hide],['pointerleave',hide],['touchstart',show],['touchend',hide],['touchcancel',hide]];
    for(const [name,handler] of events)element.addEventListener(name,handler,{passive:name.startsWith('touch')?false:undefined});
    const cleanup=()=>{for(const [name,handler] of events)element.removeEventListener(name,handler);};
    cleanups.push(cleanup);return cleanup;
  };
  const destroy=()=>{if(idleTimer)clearTimeout(idleTimer);for(const cleanup of cleanups.splice(0))cleanup();listeners.clear();};

  return {snapshot,isHidden,reveal,conceal,concealAll,unlock,lock,quickHide,setSettings,subscribe,bindHold,destroy};
}
