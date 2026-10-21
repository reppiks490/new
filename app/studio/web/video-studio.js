import {
  DEFAULT_PRIVACY_PREFERENCES,
  createPrivacyController,
  revealWhileHeld,
} from './privacy-mode.js';

const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
}[char]));

export function neutralJobLabel(index) {
  return `Project ${Number(index) + 1}`;
}

export function availableVideoControls(capability = {}) {
  return {
    profiles: [...(capability.profiles || [])],
    resolutions: [...(capability.supported_resolutions || [])],
    fps: [...(capability.supported_fps || [])],
    motionStrength: Boolean(capability.supports_motion_strength),
    cameraMotions: [...(capability.camera_motion_presets || [])],
  };
}

export function renderPrivateJobSummary(job, index, preferences = DEFAULT_PRIVACY_PREFERENCES) {
  const label = preferences.privacy_mode && preferences.neutral_project_names
    ? neutralJobLabel(index)
    : `Video ${String(job.id || '').slice(0, 8)}`;
  const progress = Number.isFinite(Number(job.progress)) ? ` · ${Number(job.progress)}%` : '';
  return {
    label,
    status: `${job.stage || job.status || 'Queued'}${progress}`,
    state: job.status || 'queued',
    asset_url: job.asset_url || null,
    error: job.error || null,
  };
}

function currentConnection() {
  const urlInput = document.getElementById('backend-url');
  const tokenInput = document.getElementById('backend-token');
  let origin = location.origin;
  const requested = urlInput?.value?.trim();
  if (requested) {
    try { origin = new URL(requested, location.origin).origin; } catch { origin = location.origin; }
  }
  return {origin, token: tokenInput?.value || ''};
}


function videoAssetUrl(path) {
  if (!path) return '';
  try { return new URL(path, `${currentConnection().origin}/`).toString(); }
  catch { return String(path); }
}

async function videoApi(path, options = {}) {
  const {origin, token} = currentConnection();
  const headers = {
    ...(token ? {'Authorization': `Bearer ${token}`} : {}),
    ...(!(options.body instanceof FormData) ? {'Content-Type':'application/json'} : {}),
    ...(options.headers || {}),
  };
  const response = await fetch(`${origin}/api/video${path}`, {
    ...options,
    headers,
    signal: AbortSignal.timeout(30000),
  });
  if (!response.ok) {
    let detail;
    try { detail = (await response.json()).detail; } catch {}
    throw new Error(typeof detail === 'string' ? detail : `Video request failed (${response.status})`);
  }
  return response.json();
}

function setStatus(text) {
  const target = document.getElementById('status');
  if (target) target.textContent = text;
}

function selectedCapability(capabilities) {
  const engines = capabilities?.runtime?.engines || [];
  return engines.find(engine => engine.available !== false) || engines[0] || null;
}

function optionList(values, selected) {
  return values.map(value => `<option value="${escapeHtml(value)}" ${String(value)===String(selected)?'selected':''}>${escapeHtml(value)}</option>`).join('');
}

function renderNeutralScreen(workspace, inspector, privacy) {
  workspace.innerHTML = '<div class="video-neutral-screen"><div class="video-neutral-icon">◇</div><h1>Workspace</h1><p>Private content is hidden.</p><button id="video-restore" class="primary">Return to private workspace</button></div>';
  inspector.innerHTML = '<h1>Workspace</h1><p>Private media and prompts are concealed.</p><button id="video-restore-side" class="wide">Return</button>';
  for (const id of ['video-restore','video-restore-side']) {
    const button=document.getElementById(id);
    if (button) button.onclick=()=>privacy.restore();
  }
}

function applyPrivacyPresentation(state) {
  const {privacy, sourceImageId, activeJob, jobs} = state;
  const prompt = document.getElementById('video-prompt');
  if (prompt) prompt.classList.toggle('privacy-masked-prompt', privacy.shouldMaskPrompt());
  const source = document.getElementById('video-source-preview');
  if (source) source.classList.toggle('privacy-blurred', privacy.shouldBlurMedia('source'));
  const preview = document.getElementById('video-result-preview');
  if (preview) preview.classList.toggle('privacy-blurred', privacy.shouldBlurMedia('preview'));
  const sourceButton = document.getElementById('video-reveal-source');
  if (sourceButton) sourceButton.textContent = privacy.isRevealed('source') ? 'Hide source' : 'Reveal source';
  const promptButton = document.getElementById('video-reveal-prompt');
  if (promptButton) promptButton.textContent = privacy.isRevealed('prompt') ? 'Hide prompt' : 'Reveal prompt';
  const previewButton = document.getElementById('video-reveal-preview');
  if (previewButton) previewButton.textContent = privacy.isRevealed('preview') ? 'Hide result' : 'Reveal result';
  void sourceImageId; void activeJob; void jobs;
}

function renderJobList(state) {
  const target = document.getElementById('video-jobs');
  if (!target) return;
  const prefs = state.privacy.preferences();
  target.innerHTML = state.jobs.length ? state.jobs.map((job,index) => {
    const summary = renderPrivateJobSummary(job,index,prefs);
    return `<article class="video-job-card"><div><strong>${escapeHtml(summary.label)}</strong><span>${escapeHtml(summary.status)}</span></div>${summary.error?`<p class="video-error">${escapeHtml(summary.error)}</p>`:''}${summary.asset_url?`<button data-video-job="${escapeHtml(job.id)}">Open result</button>`:''}</article>`;
  }).join('') : '<p class="hint">No video jobs yet.</p>';
  for (const button of target.querySelectorAll?.('[data-video-job]') || []) {
    button.onclick=()=>{
      state.activeJob=state.jobs.find(job=>job.id===button.dataset.videoJob) || null;
      renderWorkspace(state);
    };
  }
}

function renderWorkspace(state) {
  const workspace=document.getElementById('video-workspace');
  if (!workspace) return;
  if (state.privacy.isQuickHidden()) {
    renderNeutralScreen(workspace, document.getElementById('inspector'), state.privacy);
    return;
  }
  const current = state.activeJob?.asset_url ? state.activeJob : state.jobs.find(job=>job.asset_url);
  workspace.innerHTML = `<div class="video-stage">
    <div class="video-stage-header"><div><span class="eyebrow">PRIVATE VIDEO /</span><h1>${current?'Generated result':'Source preview'}</h1></div><button id="video-quick-hide">Quick Hide</button></div>
    <div class="video-media-shell">
      ${current?`<video id="video-result-preview" playsinline controls preload="metadata" src="${escapeHtml(videoAssetUrl(current.asset_url))}"></video>`:state.sourceImageUrl?`<img id="video-source-preview" src="${escapeHtml(state.sourceImageUrl)}" alt="Private source image">`:'<div class="video-empty-stage">Choose an image from your iPhone to begin.</div>'}
    </div>
    <div class="video-stage-actions">
      ${current?'<button id="video-peek-preview">Hold to peek</button><button id="video-reveal-preview">Reveal result</button>':''}
      ${current?`<a class="video-download" href="${escapeHtml(videoAssetUrl(current.asset_url))}" download>Download MP4</a>`:''}
      ${state.sourceImageUrl?'<button id="video-peek-source">Hold to peek</button><button id="video-reveal-source">Reveal source</button>':''}
    </div>
  </div>`;
  const quick=document.getElementById('video-quick-hide');
  if (quick) quick.onclick=()=>state.privacy.quickHide();
  const sourceReveal=document.getElementById('video-reveal-source');
  if (sourceReveal) sourceReveal.onclick=()=>state.privacy.toggleReveal('source');
  const sourcePeek=document.getElementById('video-peek-source');
  if (sourcePeek) state.cleanups.push(revealWhileHeld(sourcePeek,'source',state.privacy));
  const previewReveal=document.getElementById('video-reveal-preview');
  if (previewReveal) previewReveal.onclick=()=>state.privacy.toggleReveal('preview');
  const previewPeek=document.getElementById('video-peek-preview');
  if (previewPeek) state.cleanups.push(revealWhileHeld(previewPeek,'preview',state.privacy));
  applyPrivacyPresentation(state);
}

function renderInspector(state) {
  const inspector=document.getElementById('inspector');
  if (!inspector || state.privacy.isQuickHidden()) return;
  const engine=selectedCapability(state.capabilities);
  const controls=availableVideoControls(engine || {});
  const runtime=state.capabilities?.runtime;
  const ready=Boolean(engine?.available && state.sourceImageId);
  const profile = controls.profiles.includes(runtime?.recommended_profile) ? runtime.recommended_profile : controls.profiles[0] || 'balanced';
  inspector.innerHTML = `<h1>Video Studio</h1><p>Generate image-to-video locally on your PC. Your iPhone is the private controller.</p>
    <div class="video-privacy-row"><span>Privacy Mode</span><button id="video-privacy-toggle" aria-pressed="${state.privacy.preferences().privacy_mode}">${state.privacy.preferences().privacy_mode?'On':'Off'}</button><button id="video-quick-hide-side">Quick Hide</button></div>
    <label>Source image<input id="video-image-input" type="file" accept="image/png,image/jpeg,image/webp"></label>
    ${state.sourceImageId?'<button id="video-reveal-source-side" class="wide">Hold to peek at source</button>':''}
    <label>Motion prompt<textarea id="video-prompt" maxlength="2000" placeholder="Describe movement, expression, camera motion, and timing."></textarea></label>
    <div class="video-reveal-row"><button id="video-peek-prompt">Hold to peek</button><button id="video-reveal-prompt">Reveal prompt</button></div>
    <div class="video-grid-2">
      <label>Profile<select id="video-profile">${optionList(controls.profiles.length?controls.profiles:[profile],profile)}</select></label>
      <label>Resolution<select id="video-resolution">${optionList(controls.resolutions.length?controls.resolutions:['720p'],controls.resolutions[0]||'720p')}</select></label>
      <label>FPS<select id="video-fps">${optionList(controls.fps.length?controls.fps:[24],controls.fps[0]||24)}</select></label>
      <label>Seconds<input id="video-duration" type="number" min="${escapeHtml(engine?.min_duration_seconds || 1)}" max="${escapeHtml(engine?.max_duration_seconds || 30)}" value="${Math.min(5,engine?.max_duration_seconds || 5)}"></label>
      <label>Seed<input id="video-seed" type="number" min="0" max="4294967295" value="0"></label>
      <label>Camera<select id="video-camera" ${controls.cameraMotions.length?'':'disabled'}><option value="">Model default</option>${optionList(controls.cameraMotions,'')}</select></label>
    </div>
    <label>Motion strength<input id="video-motion" type="range" min="0" max="1" step="0.05" value="0.5" ${controls.motionStrength?'':'disabled'}></label>
    ${runtime?.blockers?.length?`<div class="notice">${runtime.blockers.map(escapeHtml).join('<br>')}</div>`:''}
    <button id="video-generate" class="wide primary" ${ready?'':'disabled'}>Generate video</button>
    <h2>Recent jobs</h2><div id="video-jobs"></div>`;

  const imageInput=document.getElementById('video-image-input');
  imageInput.onchange=async event=>{
    const file=event.target.files?.[0]; if(!file)return;
    if(file.size>12*1024*1024){setStatus('Image exceeds 12 MiB.');return;}
    const form=new FormData(); form.append('file',file);
    try{
      setStatus('Uploading private source image…');
      const result=await videoApi('/images',{method:'POST',body:form});
      state.sourceImageId=result.image_id; state.sourceImageUrl=videoAssetUrl(result.url);
      state.privacy.conceal('source');
      renderInspector(state); renderWorkspace(state);
      setStatus('Source image ready.');
    }catch(error){setStatus(error.message);}
  };
  document.getElementById('video-privacy-toggle').onclick=async()=>{
    const prefs=state.privacy.preferences();
    const next=state.privacy.setPreferences({...prefs,privacy_mode:!prefs.privacy_mode});
    try{await videoApi('/privacy',{method:'PUT',body:JSON.stringify(next)});}catch(error){setStatus(error.message);}
    renderInspector(state); renderWorkspace(state);
  };
  document.getElementById('video-quick-hide-side').onclick=()=>state.privacy.quickHide();
  const promptReveal=document.getElementById('video-reveal-prompt');
  promptReveal.onclick=()=>state.privacy.toggleReveal('prompt');
  const promptPeek=document.getElementById('video-peek-prompt');
  if(promptPeek)state.cleanups.push(revealWhileHeld(promptPeek,'prompt',state.privacy));
  const sourceRevealSide=document.getElementById('video-reveal-source-side');
  if(sourceRevealSide) state.cleanups.push(revealWhileHeld(sourceRevealSide,'source',state.privacy));

  const generate=document.getElementById('video-generate');
  generate.onclick=async()=>{
    const prompt=document.getElementById('video-prompt').value.trim();
    if(!prompt){setStatus('Enter a motion prompt.');return;}
    const payload={
      image_id:state.sourceImageId,
      prompt,
      engine_profile:document.getElementById('video-profile').value,
      seed:Number(document.getElementById('video-seed').value)||0,
      duration_seconds:Number(document.getElementById('video-duration').value)||5,
      fps:Number(document.getElementById('video-fps').value)||24,
      resolution:document.getElementById('video-resolution').value,
    };
    if(controls.motionStrength) payload.motion_strength=Number(document.getElementById('video-motion').value);
    if(controls.cameraMotions.length && document.getElementById('video-camera').value) payload.camera_motion=document.getElementById('video-camera').value;
    generate.disabled=true;
    try{
      state.privacy.concealAll();
      setStatus('Queued on your local video worker…');
      const job=await videoApi('/generate',{method:'POST',body:JSON.stringify(payload)});
      state.jobs=[job,...state.jobs.filter(item=>item.id!==job.id)];
      state.activeJob=job;
      renderJobList(state); renderWorkspace(state);
      pollVideoJob(job.id,state);
    }catch(error){setStatus(error.message); generate.disabled=false;}
  };
  renderJobList(state);
  applyPrivacyPresentation(state);
}

export async function pollVideoJob(id, state) {
  try{
    const job=await videoApi(`/jobs/${encodeURIComponent(id)}`);
    state.jobs=[job,...state.jobs.filter(item=>item.id!==id)];
    state.activeJob=job;
    renderJobList(state); renderWorkspace(state);
    if(['queued','running'].includes(job.status)) {
      state.pollTimer=setTimeout(()=>pollVideoJob(id,state),1500);
    } else {
      setStatus(job.status==='succeeded'?'Video ready on your PC.':job.error || 'Video generation stopped.');
      renderInspector(state);
    }
  }catch(error){setStatus(error.message);}
}

export async function renderVideoStudio() {
  const inspector=document.getElementById('inspector');
  const workspace=document.getElementById('video-workspace');
  const viewport=document.getElementById('viewport');
  if(!inspector || !workspace || !viewport) return;
  document.querySelectorAll('[data-tab]').forEach(button=>button.classList.toggle('selected',button.dataset.tab==='video'));
  viewport.classList.add('video-mode');
  workspace.hidden=false;
  const viewLabel=document.getElementById('view-label'); if(viewLabel)viewLabel.textContent='Private video studio';
  const badge=document.getElementById('mode-badge'); if(badge)badge.textContent='Local image-to-video';

  const state={
    capabilities:null,
    jobs:[],
    sourceImageId:null,
    sourceImageUrl:null,
    activeJob:null,
    pollTimer:null,
    cleanups:[],
    privacy:null,
  };
  state.privacy=createPrivacyController({onChange:()=>{
    if(state.privacy.isQuickHidden()) renderNeutralScreen(workspace,inspector,state.privacy);
    else { renderInspector(state); renderWorkspace(state); }
  }});
  state.cleanups.push(state.privacy.attachVisibilityGuard());
  state.cleanups.push(state.privacy.attachIdleGuard());
  workspace.__videoState=state;
  try{
    const [capabilities,preferences,jobs]=await Promise.all([
      videoApi('/capabilities'), videoApi('/privacy'), videoApi('/jobs')
    ]);
    state.capabilities=capabilities;
    state.jobs=Array.isArray(jobs)?jobs:[];
    state.activeJob=state.jobs.find(job=>job.asset_url) || state.jobs[0] || null;
    state.privacy.setPreferences(preferences);
    renderInspector(state); renderWorkspace(state);
    setStatus(capabilities?.runtime?.available?'Local video runtime ready.':'Video studio connected; local model runtime still needs setup.');
  }catch(error){
    inspector.innerHTML=`<h1>Video Studio</h1><div class="notice">${escapeHtml(error.message)}</div><button id="video-connect" class="wide">Open connection settings</button>`;
    workspace.innerHTML='<div class="video-empty-stage">Connect the private worker to use Video Studio.</div>';
    const connect=document.getElementById('video-connect');
    if(connect)connect.onclick=()=>document.getElementById('connection-dialog')?.showModal();
    setStatus(error.message);
  }
}

export function exitVideoStudio() {
  const workspace=document.getElementById('video-workspace');
  const viewport=document.getElementById('viewport');
  if(!workspace || !viewport) return;
  const state=workspace.__videoState;
  if(state?.pollTimer)clearTimeout(state.pollTimer);
  for(const cleanup of state?.cleanups || []) { try{cleanup();}catch{} }
  if(state?.privacy)state.privacy.concealAll();
  workspace.__videoState=null;
  workspace.innerHTML=''; workspace.hidden=true;
  viewport.classList.remove('video-mode');
}

function installVideoTab() {
  const nav=document.querySelector('nav[aria-label="Studio panels"]');
  if(!nav || nav.dataset.videoInstalled==='true')return;
  nav.dataset.videoInstalled='true';
  nav.addEventListener('click',event=>{
    const button=event.target.closest?.('[data-tab]');
    if(!button)return;
    if(button.dataset.tab==='video'){
      event.preventDefault(); event.stopImmediatePropagation();
      exitVideoStudio();
      renderVideoStudio();
    } else {
      exitVideoStudio();
    }
  },true);
}

if(typeof document!=='undefined')installVideoTab();
