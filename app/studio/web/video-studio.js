import {createPrivacyController,DEFAULT_PRIVACY} from './privacy-mode.js';

export function neutralJobLabel(job,index,privacy={}){
  if(privacy.privacy_mode&&privacy.neutral_project_names)return `Project ${index+1}`;
  return `Video ${index+1}`;
}

export function deriveControlSupport(capabilities={}){
  const engines=Array.isArray(capabilities.engines)?capabilities.engines:[];
  const available=engines.find(engine=>engine?.available) || engines[0] || null;
  return {
    engine:available?.name||null,
    motionStrength:Boolean(available?.supports_motion_strength),
    cameraMotion:Boolean(available?.supports_camera_motion),
    resolutions:Array.isArray(available?.resolutions)&&available.resolutions.length?[...available.resolutions]:['720p'],
    profiles:Array.isArray(available?.profiles)&&available.profiles.length?[...available.profiles]:capabilities.recommended_profile?[capabilities.recommended_profile]:['auto'],
  };
}

const hasDOM=typeof document!=='undefined'&&typeof window!=='undefined';
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state={
  active:false,
  backend:hasDOM?location.origin:'',
  token:'',
  capabilities:null,
  privacySettings:{...DEFAULT_PRIVACY},
  privacy:null,
  imageId:null,
  sourceUrl:null,
  jobs:[],
  selectedJob:null,
  resultUrl:null,
  sessionPin:'',
  draftPrompt:'',
  privacySecureState:null,
  pollTimers:new Map(),
};

function status(text){
  if(!hasDOM)return;
  const el=document.getElementById('status');if(el)el.textContent=text;
}

function videoHeaders(options={}){
  return {
    ...(state.token?{'Authorization':`Bearer ${state.token}`} : {}),
    ...(!(options.body instanceof FormData)?{'Content-Type':'application/json'}:{}),
    ...(options.headers||{}),
  };
}

async function videoApi(path,options={},asBlob=false){
  const base=(state.backend||location.origin).replace(/\/$/,'');
  const response=await fetch(`${base}/api/video${path}`,{
    ...options,
    headers:videoHeaders(options),
    signal:AbortSignal.timeout(30000),
  });
  if(!response.ok){
    let detail='';try{detail=(await response.json()).detail;}catch{}
    if(Array.isArray(detail))detail=detail.map(item=>item.msg).join('; ');
    throw Error(typeof detail==='string'&&detail?detail:`Video worker request failed (${response.status})`);
  }
  return asBlob?response.blob():response.json();
}

function disposeUrl(key){
  const url=state[key];
  if(url&&String(url).startsWith('blob:'))URL.revokeObjectURL(url);
  state[key]=null;
}

function viewElements(){
  return {
    inspector:document.getElementById('inspector'),
    viewport:document.getElementById('viewport'),
    label:document.getElementById('view-label'),
    badge:document.getElementById('mode-badge'),
  };
}

function ensurePrivacy(){
  if(state.privacy)return state.privacy;
  state.privacy=createPrivacyController({documentRef:document,settings:state.privacySettings});
  state.privacySecureState=Boolean(state.privacy.snapshot().locked||state.privacy.snapshot().quickHidden);
  state.privacy.subscribe(snap=>{
    if(!state.active)return;
    const secure=Boolean(snap.locked||snap.quickHidden);
    if(secure!==state.privacySecureState){state.privacySecureState=secure;renderVideoSurface();return;}
    applyPrivacyPresentation();
  });
  return state.privacy;
}

async function loadVideoState(){
  try{
    const [capabilities,privacy,jobs]=await Promise.all([
      videoApi('/capabilities'),videoApi('/privacy'),videoApi('/jobs'),
    ]);
    state.capabilities=capabilities;
    state.privacySettings={...DEFAULT_PRIVACY,...privacy};
    ensurePrivacy().setSettings(state.privacySettings);
    state.jobs=Array.isArray(jobs)?jobs:[];
    renderVideoSurface();
    status(capabilities.available?'Local video runtime ready.':'Video Studio loaded; local model/runtime is not ready yet.');
  }catch(error){
    renderConnectionFailure(error.message);
    status(error.message);
  }
}

function renderConnectionFailure(message){
  const {inspector,viewport}=viewElements();
  if(inspector)inspector.innerHTML=`<h1>Video Studio</h1><p>Private local image-to-video.</p><div class="notice">${esc(message)}</div><button class="wide" id="video-connect">Connect private worker</button>`;
  if(viewport){
    const shell=document.getElementById('video-workspace');
    if(shell)shell.innerHTML='<section class="video-neutral"><span class="eyebrow">PRIVATE VIDEO</span><h1>Worker connection required</h1><p>Connect your private PC worker to continue.</p></section>';
  }
  document.getElementById('video-connect')?.addEventListener('click',()=>document.getElementById('connection-dialog')?.showModal());
}

function applyPrivacyPresentation(){
  if(!state.privacy)return;
  const prompt=document.getElementById('video-prompt');if(prompt)prompt.type=state.privacy.isHidden('prompt')?'password':'text';
  for(const el of document.querySelectorAll('#video-source-mini,.video-preview-card img'))el.classList.toggle('privacy-blur',state.privacy.isHidden('source'));
  for(const el of document.querySelectorAll('.video-preview-card video'))el.classList.toggle('privacy-blur',state.privacy.isHidden('result'));
}

function renderVideoSurface(){
  if(!state.active)return;
  renderInspector();
  renderViewport();
}

function renderInspector(){
  const {inspector}=viewElements();if(!inspector)return;
  const privacy=ensurePrivacy();
  const snap=privacy.snapshot();
  if(snap.quickHidden||snap.locked){
    inspector.innerHTML=`<h1>Workspace</h1><p>Session controls.</p><div class="notice">Private workspace is locked.</div>`;
    return;
  }
  const support=deriveControlSupport(state.capabilities||{});
  const runtimeReady=Boolean(state.capabilities?.available&&support.engine);
  inspector.innerHTML=`
    <div class="video-inspector-head"><div><span class="eyebrow">LOCAL / PRIVATE</span><h1>Video Studio</h1></div><button id="video-quick-hide" class="video-compact" ${state.privacySettings.quick_hide?'':'disabled'}>Quick Hide</button></div>
    <p>Animate one image on your PC. Nothing is uploaded to a paid generation provider.</p>
    <label>Source image<input id="video-source" type="file" accept="image/png,image/jpeg,image/webp"></label>
    <div class="video-source-mini ${privacy.isHidden('source')?'privacy-blur':''}" id="video-source-mini">${state.sourceUrl?`<img src="${esc(state.sourceUrl)}" alt="Selected source image">`:'<span>No image selected</span>'}</div>
    ${state.sourceUrl?'<button id="reveal-source" class="wide">Hold to reveal source</button>':''}
    <label>Motion prompt<input id="video-prompt" type="${privacy.isHidden('prompt')?'password':'text'}" maxlength="12000" autocomplete="off" autocapitalize="sentences" spellcheck="false" placeholder="Describe motion and camera behavior"></label>
    <button id="reveal-prompt" class="wide">Hold to reveal prompt</button>
    <div class="video-grid-two">
      <label>Profile<select id="video-profile">${support.profiles.map(p=>`<option value="${esc(p)}">${esc(p.replace('_',' '))}</option>`).join('')}</select></label>
      <label>Resolution<select id="video-resolution">${support.resolutions.map(r=>`<option value="${esc(r)}">${esc(r)}</option>`).join('')}</select></label>
      <label>Duration<input id="video-duration" type="number" min="1" max="12" value="4"></label>
      <label>FPS<input id="video-fps" type="number" min="1" max="60" value="24"></label>
    </div>
    <label>Seed<input id="video-seed" type="number" min="0" value="0"></label>
    <label ${support.motionStrength?'':'hidden'}>Motion strength<input id="video-motion" type="range" min="0" max="1" step="0.05" value="0.5" ${support.motionStrength?'':'disabled'}></label>
    <label ${support.cameraMotion?'':'hidden'}>Camera motion<select id="video-camera" ${support.cameraMotion?'':'disabled'}><option value="">Model default</option><option value="push_in">Push in</option><option value="pull_out">Pull out</option><option value="pan_left">Pan left</option><option value="pan_right">Pan right</option></select></label>
    ${runtimeReady?'':`<div class="notice">${esc((state.capabilities?.blockers||['No production local video engine is registered yet.']).join(' '))}</div>`}
    <button id="video-generate" class="wide primary" ${runtimeReady&&state.imageId?'':'disabled'}>Generate locally</button>
    <h2>Privacy</h2>
    <label class="check"><input id="privacy-enabled" type="checkbox" ${state.privacySettings.privacy_mode?'checked':''}>Privacy Mode</label>
    <label class="check"><input id="privacy-prompts" type="checkbox" ${state.privacySettings.mask_prompts?'checked':''}>Mask prompt</label>
    <label class="check"><input id="privacy-media" type="checkbox" ${state.privacySettings.blur_media?'checked':''}>Blur media</label>
    <label class="check"><input id="privacy-neutral" type="checkbox" ${state.privacySettings.neutral_project_names?'checked':''}>Neutral job names</label>
    <label>Optional session PIN<input id="video-pin" type="password" inputmode="numeric" autocomplete="off" maxlength="12" placeholder="Memory only"></label>
    <button id="set-video-pin" class="wide">Set session PIN</button>
    <h2>Recent</h2><div id="video-jobs">${renderJobCards()}</div>`;

  const promptInput=document.getElementById('video-prompt');
  if(promptInput){promptInput.value=state.draftPrompt;promptInput.addEventListener('input',event=>{state.draftPrompt=event.target.value;});}
  const source=document.getElementById('video-source');
  source?.addEventListener('change',uploadSource);
  const holdSource=document.getElementById('reveal-source');if(holdSource)privacy.bindHold(holdSource,'source');
  const holdPrompt=document.getElementById('reveal-prompt');if(holdPrompt)privacy.bindHold(holdPrompt,'prompt');
  document.getElementById('video-quick-hide')?.addEventListener('click',()=>privacy.quickHide());
  document.getElementById('video-generate')?.addEventListener('click',generateVideo);
  document.getElementById('set-video-pin')?.addEventListener('click',()=>{
    state.sessionPin=document.getElementById('video-pin')?.value||'';
    if(document.getElementById('video-pin'))document.getElementById('video-pin').value='';
    status(state.sessionPin?'Session PIN set in memory.':'Session PIN cleared.');
  });
  for(const [id,key] of [['privacy-enabled','privacy_mode'],['privacy-prompts','mask_prompts'],['privacy-media','blur_media'],['privacy-neutral','neutral_project_names']]){
    document.getElementById(id)?.addEventListener('change',event=>savePrivacy({[key]:event.target.checked}));
  }
  for(const button of document.querySelectorAll('[data-video-job]'))button.addEventListener('click',()=>openJob(button.dataset.videoJob));
}

function renderJobCards(){
  if(!state.jobs.length)return '<div class="empty">No video jobs yet.</div>';
  return state.jobs.slice(0,20).map((job,index)=>{
    const label=neutralJobLabel(job,index,state.privacySettings);
    const progress=Number.isFinite(job.progress)?` · ${job.progress}%`:'';
    return `<div class="job-card video-job-card"><strong>${esc(label)}</strong><div>${esc(job.stage||job.status)}${esc(progress)}</div>${job.error?`<div class="video-error">${esc(job.error)}</div>`:''}${job.asset_url?`<button data-video-job="${esc(job.id)}" class="wide">Open result</button>`:''}</div>`;
  }).join('');
}

function renderViewport(){
  const shell=document.getElementById('video-workspace');if(!shell)return;
  const privacy=ensurePrivacy(),snap=privacy.snapshot();
  if(snap.quickHidden||snap.locked){
    shell.innerHTML=`<section class="video-neutral"><span class="eyebrow">WORKSPACE /</span><h1>Workspace Overview</h1><p>Session locked. Resume to return to your workspace.</p>${state.sessionPin?'<label>Session PIN<input id="video-unlock-pin" type="password" inputmode="numeric" autocomplete="off"></label>':''}<button id="video-unlock" class="primary">Resume workspace</button></section>`;
    document.getElementById('video-unlock')?.addEventListener('click',()=>{
      const supplied=document.getElementById('video-unlock-pin')?.value||'';
      if(state.sessionPin&&supplied!==state.sessionPin){status('Incorrect session PIN.');return;}
      privacy.unlock();
    });
    return;
  }
  shell.innerHTML=`<section class="video-stage">
    <div class="video-preview-card"><span class="eyebrow">SOURCE</span>${state.sourceUrl?`<img class="video-large-preview ${privacy.isHidden('source')?'privacy-blur':''}" src="${esc(state.sourceUrl)}" alt="Source image">`:'<div class="video-placeholder">Choose an image on the left.</div>'}</div>
    <div class="video-preview-card"><span class="eyebrow">RESULT</span>${state.resultUrl?`<video class="video-large-preview ${privacy.isHidden('result')?'privacy-blur':''}" src="${esc(state.resultUrl)}" controls playsinline preload="metadata"></video><div class="row"><button id="reveal-result">Hold to reveal</button><button id="download-video">Download MP4</button></div>`:'<div class="video-placeholder">Generated video appears here.</div>'}</div>
  </section>`;
  const resultReveal=document.getElementById('reveal-result');if(resultReveal)privacy.bindHold(resultReveal,'result');
  document.getElementById('download-video')?.addEventListener('click',downloadCurrentResult);
}

async function uploadSource(event){
  const file=event.target.files?.[0];if(!file)return;
  if(file.size>12*1024*1024){status('Image exceeds 12 MiB.');return;}
  disposeUrl('sourceUrl');state.sourceUrl=URL.createObjectURL(file);state.imageId=null;renderVideoSurface();
  try{
    const form=new FormData();form.append('file',file);
    const result=await videoApi('/images',{method:'POST',body:form});
    state.imageId=result.image_id;renderVideoSurface();status('Source image secured on your private worker.');
  }catch(error){state.imageId=null;renderVideoSurface();status(error.message);}
}

async function generateVideo(){
  const button=document.getElementById('video-generate');if(button)button.disabled=true;
  try{
    if(!state.imageId)throw Error('Choose and upload a source image first.');
    const support=deriveControlSupport(state.capabilities||{});
    const prompt=document.getElementById('video-prompt')?.value??state.draftPrompt;
    state.draftPrompt=prompt;
    if(!prompt.trim())throw Error('Enter a motion prompt.');
    const body={
      image_id:state.imageId,
      prompt,
      engine_profile:document.getElementById('video-profile')?.value||'auto',
      resolution:document.getElementById('video-resolution')?.value||'720p',
      duration_seconds:Number(document.getElementById('video-duration')?.value||4),
      fps:Number(document.getElementById('video-fps')?.value||24),
      seed:Number(document.getElementById('video-seed')?.value||0),
    };
    if(support.motionStrength)body.motion_strength=Number(document.getElementById('video-motion')?.value||0.5);
    if(support.cameraMotion&&document.getElementById('video-camera')?.value)body.camera_motion=document.getElementById('video-camera').value;
    const job=await videoApi('/generate',{method:'POST',body:JSON.stringify(body)});
    state.jobs=[job,...state.jobs.filter(item=>item.id!==job.id)];renderVideoSurface();pollVideoJob(job.id);status('Local video generation queued.');
  }catch(error){status(error.message);}
  finally{if(button)button.disabled=false;}
}

export async function pollVideoJob(id){
  if(!state.active)return;
  try{
    const job=await videoApi(`/jobs/${encodeURIComponent(id)}`);
    state.jobs=[job,...state.jobs.filter(item=>item.id!==id)];renderVideoSurface();
    if(['queued','running'].includes(job.status)){
      const timer=setTimeout(()=>pollVideoJob(id),2500);state.pollTimers.set(id,timer);
    }else{
      state.pollTimers.delete(id);
      status(job.status==='succeeded'?'Video generation complete.':job.error||'Video generation stopped.');
      if(job.status==='succeeded')await openJob(id);
    }
  }catch(error){status(error.message);state.pollTimers.delete(id);}
}

async function openJob(id){
  const job=state.jobs.find(item=>item.id===id);if(!job?.asset_url)return;
  try{
    const blob=await videoApi(job.asset_url.replace(/^\/api\/video/,''),{},true);
    disposeUrl('resultUrl');state.resultUrl=URL.createObjectURL(blob);state.selectedJob=id;renderViewport();status('Video loaded privately.');
  }catch(error){status(error.message);}
}

function downloadCurrentResult(){
  if(!state.resultUrl)return;
  const a=document.createElement('a');a.href=state.resultUrl;a.download='forma-video.mp4';a.rel='noopener';a.click();
}

async function savePrivacy(changes){
  try{
    const saved=await videoApi('/privacy',{method:'PUT',body:JSON.stringify(changes)});
    state.privacySettings={...DEFAULT_PRIVACY,...saved};ensurePrivacy().setSettings(state.privacySettings);renderVideoSurface();
  }catch(error){status(error.message);}
}

export async function renderVideoStudio(){
  if(!hasDOM)return;
  state.active=true;
  document.body.classList.add('video-mode');
  for(const button of document.querySelectorAll('nav [data-tab]'))button.classList.toggle('selected',button.dataset.tab==='video');
  const {viewport,label,badge}=viewElements();
  if(label)label.textContent='Video Studio';if(badge)badge.textContent='Local · private';
  if(viewport&&!document.getElementById('video-workspace')){
    const shell=document.createElement('div');shell.id='video-workspace';viewport.appendChild(shell);
  }
  ensurePrivacy();renderVideoSurface();await loadVideoState();
}

function leaveVideoStudio(){
  if(!state.active)return;
  state.active=false;
  document.body.classList.remove('video-mode');
  for(const timer of state.pollTimers.values())clearTimeout(timer);state.pollTimers.clear();
  document.getElementById('video-workspace')?.remove();
  disposeUrl('resultUrl');
}

function installNavigation(){
  const nav=document.querySelector('nav');if(!nav)return;
  nav.addEventListener('click',event=>{
    const button=event.target.closest?.('[data-tab]');if(!button)return;
    if(button.dataset.tab==='video'){
      event.preventDefault();event.stopImmediatePropagation();renderVideoStudio();return;
    }
    if(state.active)leaveVideoStudio();
  },true);
  document.getElementById('connect-confirm')?.addEventListener('click',()=>{
    state.backend=document.getElementById('backend-url')?.value.trim()||location.origin;
    state.token=document.getElementById('backend-token')?.value||'';
    if(state.active)setTimeout(()=>loadVideoState(),0);
  },true);
}

if(hasDOM){
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',installNavigation,{once:true});
  else installNavigation();
}
