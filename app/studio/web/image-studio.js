import {createPrivacyController, revealWhileHeld} from './privacy-mode.js';
import {bindVolatileEditorDraft} from './private-media-draft.js';

const escapeHtml=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

export function renderPrivateImageJobSummary(job,index,preferences={privacy_mode:true,neutral_project_names:true}){
  const label=preferences.privacy_mode&&preferences.neutral_project_names?`Project ${Number(index)+1}`:`Image ${String(job.id||'').slice(0,8)}`;
  const progress=Number.isFinite(Number(job.progress))?` · ${Number(job.progress)}%`:'';
  return {label,status:`${job.stage||job.status||'Queued'}${progress}`,state:job.status||'queued',asset_url:job.asset_url||null,error:job.error||null};
}

function currentConnection(){
  const urlInput=document.getElementById('backend-url');
  const tokenInput=document.getElementById('backend-token');
  let origin=location.origin;
  const requested=urlInput?.value?.trim();
  if(requested){try{origin=new URL(requested,location.origin).origin;}catch{origin=location.origin;}}
  return {origin,token:tokenInput?.value||''};
}

export function buildPrivateImageAssetRequest(path,connection){
  const origin=connection?.origin||globalThis.location?.origin||'';
  const token=connection?.token||'';
  let url;
  try{url=new URL(path,`${origin}/`).toString();}catch{url=String(path||'');}
  return {url,options:{headers:token?{'Authorization':`Bearer ${token}`}:{},cache:'no-store'}};
}

async function api(path,options={}){
  const {origin,token}=currentConnection();
  const headers={...(token?{'Authorization':`Bearer ${token}`}:{}) ,...(!(options.body instanceof FormData)?{'Content-Type':'application/json'}:{}),...(options.headers||{})};
  const response=await fetch(`${origin}/api/image${path}`,{...options,headers,signal:AbortSignal.timeout(30000)});
  if(!response.ok){let detail;try{detail=(await response.json()).detail;}catch{} throw new Error(typeof detail==='string'?detail:`Image request failed (${response.status})`);}
  return response.json();
}

async function privacyApi(path='',options={}){
  const {origin,token}=currentConnection();
  const response=await fetch(`${origin}/api/video/privacy${path}`,{...options,headers:{...(token?{'Authorization':`Bearer ${token}`}:{}) ,'Content-Type':'application/json'},signal:AbortSignal.timeout(30000)});
  if(!response.ok)throw new Error(`Privacy settings request failed (${response.status})`);
  return response.json();
}

async function fetchPrivateBlob(path){
  const request=buildPrivateImageAssetRequest(path,currentConnection());
  const response=await fetch(request.url,request.options);
  if(!response.ok)throw new Error(`Private image request failed (${response.status})`);
  return response.blob();
}

function setStatus(text){const node=document.getElementById('status');if(node)node.textContent=text;}

function ensureObjectUrl(state,path){
  if(!path||state.closed||state.objectUrls.has(path)||state.loads.has(path))return;
  const task=fetchPrivateBlob(path).then(blob=>{
    if(state.closed)return;
    state.objectUrls.set(path,URL.createObjectURL(blob));
    renderWorkspace(state);
  }).catch(error=>setStatus(error.message)).finally(()=>state.loads.delete(path));
  state.loads.set(path,task);
}

function objectUrl(state,path){if(!path)return '';ensureObjectUrl(state,path);return state.objectUrls.get(path)||'';}
function releaseObjectUrl(state,path){const url=state.objectUrls.get(path);if(url){URL.revokeObjectURL(url);state.objectUrls.delete(path);}}

function neutralScreen(workspace,inspector,state){
  workspace.innerHTML='<div class="image-neutral-screen"><div class="image-neutral-icon">◇</div><h1>Workspace</h1><p>Private content is hidden.</p><button id="image-restore" class="primary">Return to private workspace</button></div>';
  inspector.innerHTML='<h1>Workspace</h1><p>Private images and prompts are concealed.</p><button id="image-restore-side" class="wide">Return</button>';
  for(const id of ['image-restore','image-restore-side']){const b=document.getElementById(id);if(b)b.onclick=()=>state.privacy.restore();}
}

function applyPrivacy(state){
  const prompt=document.getElementById('image-prompt');
  if(prompt)prompt.classList.toggle('privacy-masked-prompt',state.privacy.shouldMaskPrompt());
  const source=document.getElementById('image-source-preview');
  if(source)source.classList.toggle('privacy-blurred',state.privacy.shouldBlurMedia('source'));
  const result=document.getElementById('image-result-preview');
  if(result)result.classList.toggle('privacy-blurred',state.privacy.shouldBlurMedia('result'));
}

function renderJobs(state){
  const target=document.getElementById('image-jobs');if(!target)return;
  const prefs=state.privacy.preferences();
  target.innerHTML=state.jobs.length?state.jobs.map((job,index)=>{const s=renderPrivateImageJobSummary(job,index,prefs);return `<article class="image-job-card"><div><strong>${escapeHtml(s.label)}</strong><span>${escapeHtml(s.status)}</span></div>${s.error?`<p class="image-error">${escapeHtml(s.error)}</p>`:''}${s.asset_url?`<button data-image-job="${escapeHtml(job.id)}">Open result</button>`:''}</article>`;}).join(''):'<p class="hint">No image jobs yet.</p>';
  for(const button of target.querySelectorAll?.('[data-image-job]')||[]){button.onclick=()=>{state.activeJob=state.jobs.find(job=>job.id===button.dataset.imageJob)||null;renderWorkspace(state);};}
}

function renderWorkspace(state){
  const workspace=document.getElementById('image-workspace');if(!workspace)return;
  if(state.privacy.isQuickHidden()){neutralScreen(workspace,document.getElementById('inspector'),state);return;}
  const resultPath=state.activeJob?.asset_url||state.jobs.find(job=>job.asset_url)?.asset_url||null;
  const resultUrl=resultPath?objectUrl(state,resultPath):'';
  const sourceUrl=state.sourceUrl?objectUrl(state,state.sourceUrl):'';
  const media=resultPath?(resultUrl?`<img id="image-result-preview" src="${escapeHtml(resultUrl)}" alt="Private generated result">`:'<div class="image-empty-stage">Loading private result…</div>'):state.sourceUrl?(sourceUrl?`<img id="image-source-preview" src="${escapeHtml(sourceUrl)}" alt="Private source image">`:'<div class="image-empty-stage">Loading private source…</div>'):'<div class="image-empty-stage">Choose an image from your iPhone to begin.</div>';
  workspace.innerHTML=`<div class="image-stage"><div class="image-stage-header"><div><span class="eyebrow">PRIVATE IMAGE /</span><h1>${resultPath?'Edited result':'Source preview'}</h1></div><button id="image-quick-hide">Quick Hide</button></div><div class="image-media-shell">${media}</div><div class="image-stage-actions">${resultPath?'<button id="image-peek-result">Hold to peek</button><button id="image-reveal-result">Reveal result</button>':''}${resultUrl?`<a class="image-download" href="${escapeHtml(resultUrl)}" download="private-image.png">Download PNG</a>`:''}${state.sourceUrl?'<button id="image-peek-source">Hold to peek</button><button id="image-reveal-source">Reveal source</button>':''}</div></div>`;
  document.getElementById('image-quick-hide').onclick=()=>state.privacy.quickHide();
  const sourceReveal=document.getElementById('image-reveal-source');if(sourceReveal)sourceReveal.onclick=()=>state.privacy.toggleReveal('source');
  const sourcePeek=document.getElementById('image-peek-source');if(sourcePeek)state.cleanups.push(revealWhileHeld(sourcePeek,'source',state.privacy));
  const resultReveal=document.getElementById('image-reveal-result');if(resultReveal)resultReveal.onclick=()=>state.privacy.toggleReveal('result');
  const resultPeek=document.getElementById('image-peek-result');if(resultPeek)state.cleanups.push(revealWhileHeld(resultPeek,'result',state.privacy));
  applyPrivacy(state);
}

function firstEngine(capabilities){return (capabilities?.engines||[]).find(item=>item.available)||(capabilities?.engines||[])[0]||null;}

function renderInspector(state){
  const inspector=document.getElementById('inspector');if(!inspector||state.privacy.isQuickHidden())return;
  const engine=firstEngine(state.capabilities);const ready=Boolean(engine?.available&&state.sourceId);
  inspector.innerHTML=`<h1>Image Studio</h1><p>Edit an uploaded image locally on your PC. Your phone only controls the private worker.</p><div class="image-privacy-row"><span>Privacy Mode</span><button id="image-privacy-toggle" aria-pressed="${state.privacy.preferences().privacy_mode}">${state.privacy.preferences().privacy_mode?'On':'Off'}</button><button id="image-quick-hide-side">Quick Hide</button></div><label>Source image<input id="image-input" type="file" accept="image/png,image/jpeg,image/webp"></label>${state.sourceId?'<button id="image-source-peek-side" class="wide">Hold to peek at source</button>':''}<label>Edit prompt<textarea id="image-prompt" maxlength="2000" placeholder="Describe exactly what to change while preserving everything else you want kept."></textarea></label><div class="image-reveal-row"><button id="image-prompt-peek">Hold to peek</button><button id="image-prompt-reveal">Reveal prompt</button></div><label>Seed<input id="image-seed" type="number" min="0" max="4294967295" value="0"></label>${engine?`<div class="image-engine-card"><strong>${escapeHtml(engine.name)}</strong><span>${engine.available?'Ready':'Unavailable'}${engine.precision?` · ${escapeHtml(engine.precision)}`:''}</span><p>${escapeHtml(engine.detail||'')}</p></div>`:'<div class="notice">No local image engine detected.</div>'}<button id="image-generate" class="wide primary" ${ready?'':'disabled'}>Generate edited image</button><h2>Recent jobs</h2><div id="image-jobs"></div>`;
  bindVolatileEditorDraft(inspector,state.formDraft,{prompt:'image-prompt',seed:'image-seed'});
  const fileInput=document.getElementById('image-input');
  fileInput.onchange=async event=>{const file=event.target.files?.[0];if(!file)return;if(file.size>12*1024*1024){setStatus('Image exceeds 12 MiB.');return;}const form=new FormData();form.append('file',file);try{setStatus('Uploading private source image…');const result=await api('/images',{method:'POST',body:form});if(state.closed)return;if(state.sourceUrl)releaseObjectUrl(state,state.sourceUrl);state.sourceId=result.image_id;state.sourceUrl=result.url;state.activeJob=null;state.privacy.conceal('source');renderInspector(state);renderWorkspace(state);setStatus('Source image ready.');}catch(error){setStatus(error.message);}};
  document.getElementById('image-privacy-toggle').onclick=async()=>{const prefs=state.privacy.preferences();const next=state.privacy.setPreferences({...prefs,privacy_mode:!prefs.privacy_mode});try{await privacyApi('',{method:'PUT',body:JSON.stringify(next)});}catch(error){setStatus(error.message);}renderInspector(state);renderWorkspace(state);};
  document.getElementById('image-quick-hide-side').onclick=()=>state.privacy.quickHide();
  const promptReveal=document.getElementById('image-prompt-reveal');promptReveal.onclick=()=>state.privacy.toggleReveal('prompt');
  const promptPeek=document.getElementById('image-prompt-peek');if(promptPeek)state.cleanups.push(revealWhileHeld(promptPeek,'prompt',state.privacy));
  const sourcePeek=document.getElementById('image-source-peek-side');if(sourcePeek)state.cleanups.push(revealWhileHeld(sourcePeek,'source',state.privacy));
  const generate=document.getElementById('image-generate');
  generate.onclick=async()=>{const prompt=document.getElementById('image-prompt').value.trim();if(!prompt){setStatus('Enter an edit prompt.');return;}const seed=Number(document.getElementById('image-seed').value)||0;generate.disabled=true;try{state.privacy.concealAll();setStatus('Queued on your local image worker…');const job=await api('/generate',{method:'POST',body:JSON.stringify({image_id:state.sourceId,prompt,seed})});if(state.closed)return;state.jobs=[job,...state.jobs.filter(item=>item.id!==job.id)];state.activeJob=job;renderJobs(state);renderWorkspace(state);poll(job.id,state);}catch(error){setStatus(error.message);generate.disabled=false;}};
  renderJobs(state);applyPrivacy(state);
}

async function poll(id,state){
  try{const job=await api(`/jobs/${encodeURIComponent(id)}`);if(state.closed)return;state.jobs=[job,...state.jobs.filter(item=>item.id!==id)];state.activeJob=job;renderJobs(state);renderWorkspace(state);if(['queued','running'].includes(job.status)){state.pollTimer=setTimeout(()=>poll(id,state),1200);}else{setStatus(job.status==='succeeded'?'Edited image ready on your PC.':job.error||'Image generation stopped.');renderInspector(state);}}catch(error){setStatus(error.message);}
}

export async function renderImageStudio(){
  const inspector=document.getElementById('inspector');const workspace=document.getElementById('image-workspace');const viewport=document.getElementById('viewport');if(!inspector||!workspace||!viewport)return;
  document.querySelectorAll('[data-tab]').forEach(button=>button.classList.toggle('selected',button.dataset.tab==='image'));
  viewport.classList.add('image-mode');workspace.hidden=false;
  const viewLabel=document.getElementById('view-label');if(viewLabel)viewLabel.textContent='Private image studio';
  const badge=document.getElementById('mode-badge');if(badge)badge.textContent='Local image editing';
  const state={capabilities:null,jobs:[],sourceId:null,sourceUrl:null,activeJob:null,pollTimer:null,cleanups:[],privacy:null,objectUrls:new Map(),loads:new Map(),formDraft:{},closed:false};
  state.privacy=createPrivacyController({onChange:()=>{if(state.closed)return;if(state.privacy.isQuickHidden())neutralScreen(workspace,inspector,state);else if(!document.getElementById('image-prompt')){renderInspector(state);renderWorkspace(state);}else applyPrivacy(state);}});
  state.cleanups.push(state.privacy.attachVisibilityGuard());state.cleanups.push(state.privacy.attachIdleGuard());workspace.__imageState=state;
  try{const [capabilities,jobs,preferences]=await Promise.all([api('/capabilities'),api('/jobs'),privacyApi()]);if(state.closed)return;state.capabilities=capabilities;state.jobs=Array.isArray(jobs)?jobs:[];state.activeJob=state.jobs.find(job=>job.asset_url)||state.jobs[0]||null;state.privacy.setPreferences(preferences);renderInspector(state);renderWorkspace(state);setStatus(firstEngine(capabilities)?.available?'Local image engine ready.':'Image Studio connected; local image model still needs setup.');}catch(error){inspector.innerHTML=`<h1>Image Studio</h1><div class="notice">${escapeHtml(error.message)}</div><button id="image-connect" class="wide">Open connection settings</button>`;workspace.innerHTML='<div class="image-empty-stage">Connect the private worker to use Image Studio.</div>';const connect=document.getElementById('image-connect');if(connect)connect.onclick=()=>document.getElementById('connection-dialog')?.showModal();setStatus(error.message);}
}

export function exitImageStudio(){
  const workspace=document.getElementById('image-workspace');const viewport=document.getElementById('viewport');if(!workspace||!viewport)return;const state=workspace.__imageState;if(state?.pollTimer)clearTimeout(state.pollTimer);if(state){state.closed=true;state.formDraft={};}for(const cleanup of state?.cleanups||[]){try{cleanup();}catch{}}for(const url of state?.objectUrls?.values?.()||[]){try{URL.revokeObjectURL(url);}catch{}}state?.objectUrls?.clear?.();if(state?.privacy)state.privacy.concealAll();workspace.__imageState=null;workspace.innerHTML='';workspace.hidden=true;viewport.classList.remove('image-mode');
}

function installImageTab(){
  const nav=document.querySelector('nav[aria-label="Studio panels"]');if(!nav||nav.dataset.imageInstalled==='true')return;nav.dataset.imageInstalled='true';nav.addEventListener('click',event=>{const button=event.target.closest?.('[data-tab]');if(!button)return;if(button.dataset.tab==='image'){event.preventDefault();event.stopImmediatePropagation();exitImageStudio();renderImageStudio();}else{exitImageStudio();}},true);
}

if(typeof document!=='undefined')installImageTab();
