import {
  enterCinematicProjectMode,
  exitCinematicProjectMode,
  renderCinematicInspector,
  renderCinematicWorkspace,
  buildNeutralCinematicView,
} from './cinematic-studio.js';
import {createPrivacyController} from './privacy-mode.js';

let activeState=null;
let videoModulePromise=null;

function setStatus(text){
  const target=document.getElementById('status');
  if(target)target.textContent=text;
}

function currentConnection(){
  const urlInput=document.getElementById('backend-url');
  const tokenInput=document.getElementById('backend-token');
  let origin=location.origin;
  const requested=urlInput?.value?.trim();
  if(requested){
    try{origin=new URL(requested,location.origin).origin;}catch{origin=location.origin;}
  }
  return {origin,token:tokenInput?.value||''};
}

async function videoApi(path,options={}){
  const {origin,token}=currentConnection();
  const headers={
    ...(token?{'Authorization':`Bearer ${token}`}:{ }),
    ...(!(options.body instanceof FormData)?{'Content-Type':'application/json'}:{}),
    ...(options.headers||{}),
  };
  const response=await fetch(`${origin}/api/video${path}`,{...options,headers,signal:AbortSignal.timeout(30000)});
  if(!response.ok){
    let detail;
    try{detail=(await response.json()).detail;}catch{}
    throw new Error(typeof detail==='string'?detail:`Video request failed (${response.status})`);
  }
  return response.json();
}

async function fetchPrivateAsset(path){
  const {origin,token}=currentConnection();
  const response=await fetch(new URL(path,`${origin}/`).toString(),{
    headers:token?{'Authorization':`Bearer ${token}`}:{},
    cache:'no-store',signal:AbortSignal.timeout(30000),
  });
  if(!response.ok)throw new Error(`Private media request failed (${response.status})`);
  return response.blob();
}

function disposeResultUrl(state){
  const url=state?.cinematicResultUrl;
  if(url){try{URL.revokeObjectURL(url);}catch{} state.cinematicResultUrl=null;}
}

async function updateResultPreview(state,job){
  if(!job?.asset_url)return;
  try{
    const blob=await fetchPrivateAsset(job.asset_url);
    if(state!==activeState)return;
    disposeResultUrl(state);
    state.cinematicResultUrl=URL.createObjectURL(blob);
    renderAll(state);
  }catch(error){setStatus(error.message);}
}

async function pollCinematicJob(id,state){
  if(!state||state.closed)return;
  try{
    const job=await videoApi(`/jobs/${encodeURIComponent(id)}`);
    state.jobs=[job,...(state.jobs||[]).filter(item=>item.id!==id)];
    state.activeJob=job;
    renderAll(state);
    if(['queued','running'].includes(job.status)){
      state.pollTimer=setTimeout(()=>pollCinematicJob(id,state),1500);
      return;
    }
    if(job.status==='succeeded'){
      setStatus('Shot render ready.');
      await updateResultPreview(state,job);
    }else setStatus(job.error||'Shot render stopped.');
  }catch(error){setStatus(error.message);}
}

function dependencies(state){
  return {
    api:videoApi,
    setStatus,
    pollJob:pollCinematicJob,
    onExit:()=>openQuickGenerate(),
  };
}

function renderNeutral(state){
  const inspector=document.getElementById('inspector');
  const workspace=document.getElementById('video-workspace');
  if(!inspector||!workspace)return;
  const neutral=buildNeutralCinematicView();
  inspector.innerHTML=`<h1>${neutral.title}</h1><p>${neutral.message}</p><button id="cinematic-restore" class="wide primary">Return to private workspace</button>`;
  workspace.innerHTML=`<div class="video-neutral-screen"><div class="video-neutral-icon">◇</div><h1>${neutral.title}</h1><p>${neutral.message}</p><button id="cinematic-restore-workspace" class="primary">Return</button></div>`;
  for(const id of ['cinematic-restore','cinematic-restore-workspace']){
    const button=document.getElementById(id); if(button)button.onclick=()=>state.privacy.restore();
  }
}

function decorateResult(state){
  const workspace=document.getElementById('video-workspace');
  if(!workspace||state.privacy.isQuickHidden())return;
  const existing=workspace.querySelector('.cinematic-result-dock');
  if(existing)existing.remove();
  const job=state.activeJob;
  if(!job)return;
  const dock=document.createElement('section');
  dock.className='cinematic-result-dock';
  const status=`${job.stage||job.status||'Queued'}${Number.isFinite(Number(job.progress))?` · ${Number(job.progress)}%`:''}`;
  dock.innerHTML=`<div><span class="eyebrow">LATEST SHOT /</span><strong>${status}</strong></div>${state.cinematicResultUrl?`<video playsinline controls preload="metadata" src="${state.cinematicResultUrl}"></video>`:''}${job.error?`<p class="video-error"></p>`:''}`;
  if(job.error)dock.querySelector('.video-error').textContent=job.error;
  workspace.prepend(dock);
}

function renderAll(state){
  if(!state||state.closed)return;
  if(state.privacy.isQuickHidden()){renderNeutral(state);return;}
  const deps=dependencies(state);
  renderCinematicInspector(state,deps);
  renderCinematicWorkspace(state,deps);
  decorateResult(state);
}

function prepareVideoShell(){
  const inspector=document.getElementById('inspector');
  const workspace=document.getElementById('video-workspace');
  const viewport=document.getElementById('viewport');
  if(!inspector||!workspace||!viewport)return null;
  document.querySelectorAll('[data-tab]').forEach(button=>button.classList.toggle('selected',button.dataset.tab==='video'));
  viewport.classList.add('video-mode','cinematic-mode');
  workspace.hidden=false;
  document.getElementById('image-workspace')?.setAttribute('hidden','');
  const label=document.getElementById('view-label'); if(label)label.textContent='Cinematic film command center';
  const badge=document.getElementById('mode-badge'); if(badge)badge.textContent='Long-form scene orchestrator';
  return {inspector,workspace,viewport};
}

async function closeCinematic(){
  const state=activeState;
  activeState=null;
  if(!state)return;
  state.closed=true;
  if(state.pollTimer)clearTimeout(state.pollTimer);
  for(const cleanup of state.cleanups||[]){try{cleanup();}catch{}}
  disposeResultUrl(state);
  exitCinematicProjectMode(state);
  const workspace=document.getElementById('video-workspace');
  if(workspace?.__cinematicState===state)workspace.__cinematicState=null;
}

async function openCinematic(){
  const shell=prepareVideoShell();
  if(!shell)return;
  const video=await getVideoModule();
  video.exitVideoStudio?.();
  await closeCinematic();
  prepareVideoShell();
  const state={
    capabilities:null,jobs:[],activeJob:null,pollTimer:null,cleanups:[],closed:false,
    cinematic:null,privacy:null,cinematicResultUrl:null,
  };
  state.privacy=createPrivacyController({onChange:()=>renderAll(state)});
  state.cleanups.push(state.privacy.attachVisibilityGuard());
  state.cleanups.push(state.privacy.attachIdleGuard());
  activeState=state;
  shell.workspace.__cinematicState=state;
  try{
    const [capabilities,preferences,jobs]=await Promise.all([videoApi('/capabilities'),videoApi('/privacy'),videoApi('/jobs')]);
    state.capabilities=capabilities;
    state.jobs=Array.isArray(jobs)?jobs:[];
    state.activeJob=state.jobs.find(job=>job.asset_url)||state.jobs[0]||null;
    state.privacy.setPreferences(preferences);
    await enterCinematicProjectMode(state,dependencies(state));
    renderAll(state);
    if(state.activeJob?.asset_url)await updateResultPreview(state,state.activeJob);
  }catch(error){
    shell.inspector.innerHTML=`<h1>Cinematic Studio</h1><div class="notice"></div><button id="cinematic-connect" class="wide">Open connection settings</button>`;
    shell.inspector.querySelector('.notice').textContent=error.message;
    shell.workspace.innerHTML='<div class="video-empty-stage">Connect the private worker to use Cinematic Studio.</div>';
    shell.inspector.querySelector('#cinematic-connect').onclick=()=>document.getElementById('connection-dialog')?.showModal();
    setStatus(error.message);
  }
}

async function openQuickGenerate(){
  await closeCinematic();
  const viewport=document.getElementById('viewport');
  viewport?.classList.remove('cinematic-mode');
  const video=await getVideoModule();
  video.exitVideoStudio?.();
  await video.renderVideoStudio?.();
}

function getVideoModule(){
  if(!videoModulePromise)videoModulePromise=import('./video-studio.js');
  return videoModulePromise;
}

function installLauncher(){
  const nav=document.querySelector('nav[aria-label="Studio panels"]');
  if(!nav||nav.dataset.cinematicLauncher==='true')return;
  nav.dataset.cinematicLauncher='true';
  nav.addEventListener('click',event=>{
    const button=event.target.closest?.('[data-tab]');
    if(!button)return;
    if(button.dataset.tab==='video'){
      event.preventDefault();event.stopImmediatePropagation();
      openCinematic();
    }else{
      closeCinematic();
      document.getElementById('viewport')?.classList.remove('cinematic-mode');
    }
  },true);
  void getVideoModule();
}

if(typeof document!=='undefined')installLauncher();

export {openCinematic,openQuickGenerate,closeCinematic};
