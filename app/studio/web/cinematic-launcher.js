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
let navigationVersion=0;

function isCurrent(state){return state===activeState&&!state.closed;}
function isVisible(state){return isCurrent(state)&&!state.privacy.isQuickHidden();}
function stateStatus(state,text){if(isVisible(state))setStatus(text);}

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
  const signal=AbortSignal.any([AbortSignal.timeout(30000),...(options.signal?[options.signal]:[])]);
  const response=await fetch(`${origin}/api/video${path}`,{...options,headers,cache:'no-store',signal});
  if(!response.ok){
    let detail;
    try{detail=(await response.json()).detail;}catch{}
    throw new Error(typeof detail==='string'?detail:`Video request failed (${response.status})`);
  }
  return response.json();
}

async function fetchPrivateAsset(path,signal){
  const {origin,token}=currentConnection();
  const response=await fetch(new URL(path,`${origin}/`).toString(),{
    headers:token?{'Authorization':`Bearer ${token}`}:{},
    cache:'no-store',signal:AbortSignal.any([AbortSignal.timeout(30000),signal]),
  });
  if(!response.ok)throw new Error(`Private media request failed (${response.status})`);
  return response.blob();
}

function disposeResultUrl(state){
  const url=state?.cinematicResultUrl;
  if(url){try{URL.revokeObjectURL(url);}catch{} state.cinematicResultUrl=null;}
}

async function updateResultPreview(state,job){
  if(!isVisible(state)||!job?.asset_url||state.previewController)return;
  const controller=new AbortController();
  state.previewController=controller;
  try{
    const blob=await fetchPrivateAsset(job.asset_url,controller.signal);
    if(!isVisible(state)||controller.signal.aborted||state.activeJob?.id!==job.id)return;
    disposeResultUrl(state);
    state.cinematicResultUrl=URL.createObjectURL(blob);
    renderAll(state);
  }catch(error){if(!controller.signal.aborted)stateStatus(state,error.message);}
  finally{if(state.previewController===controller)state.previewController=null;}
}

async function pollCinematicJob(id,state){
  if(!isVisible(state))return;
  if(state.jobController){
    if(state.polledJobId===id)return;
    state.jobController.abort();
  }
  if(state.pollTimer)clearTimeout(state.pollTimer);
  state.pollTimer=null;
  const controller=new AbortController();
  state.jobController=controller;
  state.polledJobId=id;
  try{
    const job=await videoApi(`/jobs/${encodeURIComponent(id)}`,{signal:controller.signal});
    if(!isVisible(state)||controller.signal.aborted||state.activeJob?.id!==id)return;
    state.jobs=[job,...(state.jobs||[]).filter(item=>item.id!==id)];
    state.activeJob=job;
    renderAll(state);
    if(['queued','running'].includes(job.status)){
      state.pollTimer=setTimeout(()=>pollCinematicJob(id,state),1500);
      return;
    }
    if(job.status==='succeeded'){
      stateStatus(state,'Shot render ready.');
      await updateResultPreview(state,job);
    }else stateStatus(state,job.error||'Shot render stopped.');
  }catch(error){if(!controller.signal.aborted)stateStatus(state,error.message);}
  finally{if(state.jobController===controller)state.jobController=null;}
}

function suspendPresentation(state){
  if(state.pollTimer)clearTimeout(state.pollTimer);
  state.pollTimer=null;
  state.jobController?.abort();state.jobController=null;
  state.previewController?.abort();state.previewController=null;
  for(const video of document.getElementById('video-workspace')?.querySelectorAll('video')||[]){
    video.pause?.();video.removeAttribute?.('src');video.load?.();
  }
  disposeResultUrl(state);
}

function resumePresentation(state){
  if(!isVisible(state)||!state.loaded)return;
  const job=state.activeJob;
  if(['queued','running'].includes(job?.status)&&!state.pollTimer)return pollCinematicJob(job.id,state);
  if(job?.asset_url&&!state.cinematicResultUrl)return updateResultPreview(state,job);
}

function dependencies(state){
  return {
    api:async(path,options={})=>{
      if(!isCurrent(state))throw new DOMException('Workspace closed','AbortError');
      const signal=AbortSignal.any([state.controller.signal,...(options.signal?[options.signal]:[])]);
      const result=await videoApi(path,{...options,signal});
      if(!isCurrent(state))throw new DOMException('Workspace closed','AbortError');
      return result;
    },
    setStatus:text=>stateStatus(state,text),
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
  dock.innerHTML=`<div><span class="eyebrow">LATEST SHOT /</span><strong></strong></div>${state.cinematicResultUrl?`<video class="${state.privacy.shouldBlurMedia('preview')?'privacy-blurred':''}" playsinline controls preload="metadata" src="${state.cinematicResultUrl}"></video><button id="cinematic-reveal-preview">${state.privacy.isRevealed('preview')?'Hide result':'Reveal result'}</button>`:''}${job.error?`<p class="video-error"></p>`:''}`;
  dock.querySelector('strong').textContent=status;
  const reveal=dock.querySelector('#cinematic-reveal-preview');
  if(reveal)reveal.onclick=()=>state.privacy.toggleReveal('preview');
  if(job.error)dock.querySelector('.video-error').textContent=job.error;
  workspace.prepend(dock);
}

function renderAll(state){
  if(!state||!isCurrent(state))return;
  if(state.privacy.isQuickHidden()){renderNeutral(state);return;}
  if(state.connectionError){
    const inspector=document.getElementById('inspector');
    const workspace=document.getElementById('video-workspace');
    inspector.innerHTML='<h1>Cinematic Studio</h1><div class="notice"></div><button id="cinematic-connect" class="wide">Open connection settings</button>';
    inspector.querySelector('.notice').textContent=state.connectionError.message;
    workspace.innerHTML='<div class="video-empty-stage">Connect the private worker to use Cinematic Studio.</div>';
    inspector.querySelector('#cinematic-connect').onclick=()=>document.getElementById('connection-dialog')?.showModal();
    return;
  }
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
  navigationVersion++;
  const state=activeState;
  activeState=null;
  if(!state)return;
  state.closed=true;
  state.controller.abort();
  suspendPresentation(state);
  for(const cleanup of state.cleanups||[]){try{cleanup();}catch{}}
  disposeResultUrl(state);
  exitCinematicProjectMode(state);
  const workspace=document.getElementById('video-workspace');
  if(workspace?.__cinematicState===state)workspace.__cinematicState=null;
}

async function openCinematic(){
  const closing=closeCinematic();
  const version=navigationVersion;
  await closing;
  const video=await getVideoModule();
  if(version!==navigationVersion)return;
  const shell=prepareVideoShell();
  if(!shell)return;
  video.exitVideoStudio?.();
  prepareVideoShell();
  const state={
    capabilities:null,jobs:[],activeJob:null,pollTimer:null,cleanups:[],closed:false,
    cinematic:null,privacy:null,cinematicResultUrl:null,controller:new AbortController(),
    previewController:null,jobController:null,loaded:false,connectionError:null,
  };
  state.privacy=createPrivacyController({onChange:()=>{
    if(!isCurrent(state))return;
    if(state.privacy.isQuickHidden()){suspendPresentation(state);setStatus('Private cinematic project is hidden.');}
    renderAll(state);
    void resumePresentation(state);
  }});
  state.cleanups.push(state.privacy.attachVisibilityGuard());
  state.cleanups.push(state.privacy.attachIdleGuard());
  activeState=state;
  shell.workspace.__cinematicState=state;
  try{
    const {api}=dependencies(state);
    const [capabilities,preferences,jobs]=await Promise.all([api('/capabilities'),api('/privacy'),api('/jobs')]);
    if(!isCurrent(state))return;
    state.capabilities=capabilities;
    state.jobs=Array.isArray(jobs)?jobs:[];
    state.activeJob=state.jobs.find(job=>job.asset_url)||state.jobs[0]||null;
    state.privacy.setPreferences(preferences);
    await enterCinematicProjectMode(state,dependencies(state));
    if(!isCurrent(state))return;
    state.loaded=true;
    renderAll(state);
    await resumePresentation(state);
  }catch(error){
    if(!isCurrent(state))return;
    state.connectionError=error;
    renderAll(state);
    stateStatus(state,error.message);
  }
}

async function openQuickGenerate(){
  const closing=closeCinematic();
  const version=navigationVersion;
  await closing;
  const viewport=document.getElementById('viewport');
  viewport?.classList.remove('cinematic-mode');
  const video=await getVideoModule();
  if(version!==navigationVersion)return;
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
