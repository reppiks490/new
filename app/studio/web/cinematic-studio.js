const escapeHtml=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

function formatDuration(seconds){
  const total=Math.max(0,Math.round(Number(seconds)||0));
  const hours=Math.floor(total/3600);
  const minutes=Math.floor((total%3600)/60);
  const secs=total%60;
  return hours?`${hours}:${String(minutes).padStart(2,'0')}:${String(secs).padStart(2,'0')}`:`${minutes}:${String(secs).padStart(2,'0')}`;
}

export function neutralProjectLabel(index){ return `Film Project ${Number(index)+1}`; }

export function summarizeProject(project,index=0,preferences={}){
  const scenes=Array.isArray(project?.scenes)?project.scenes:[];
  const shots=scenes.reduce((sum,scene)=>sum+(scene?.shots?.length||0),0);
  const privateLabel=preferences?.privacy_mode&&preferences?.neutral_project_names;
  return {
    label:privateLabel?neutralProjectLabel(index):(project?.title||`Film ${String(project?.id||'').slice(0,8)}`),
    duration:formatDuration(project?.target_duration_seconds||0),
    seconds:Number(project?.target_duration_seconds)||0,
    scenes:scenes.length,
    shots,
    revision:Number(project?.revision)||0,
    delivery:`${project?.delivery_resolution||'—'} · ${project?.delivery_fps||'—'} FPS target`,
  };
}

export function reconcileCinematicSelection(selection={},projects=[]){
  const project=projects.find(item=>item.id===selection.projectId)||projects[0]||null;
  if(!project)return {projectId:null,sceneId:null,shotId:null};
  const scenes=Array.isArray(project.scenes)?project.scenes:[];
  const scene=scenes.find(item=>item.scene_id===selection.sceneId)||scenes[0]||null;
  const shots=scene?.shots||[];
  const shot=shots.find(item=>item.shot_id===selection.shotId)||shots[0]||null;
  return {projectId:project.id,sceneId:scene?.scene_id||null,shotId:shot?.shot_id||null};
}

export function summarizeScene(scene){
  const shots=Array.isArray(scene?.shots)?scene.shots:[];
  const seconds=shots.reduce((sum,shot)=>sum+(Number(shot?.duration_seconds)||0),0);
  return {shots:shots.length,seconds,duration:formatDuration(seconds)};
}

export function visibleShotsForScene(scene,{offset=0,limit=12}={}){
  const shots=Array.isArray(scene?.shots)?scene.shots:[];
  const safeLimit=Math.max(1,Math.min(24,Number(limit)||12));
  const safeOffset=Math.max(0,Math.min(Number(offset)||0,Math.max(0,shots.length-1)));
  const items=shots.slice(safeOffset,safeOffset+safeLimit);
  return {items,total:shots.length,offset:safeOffset,limit:safeLimit,hasMore:safeOffset+safeLimit<shots.length,hasPrevious:safeOffset>0};
}

export function buildShotInspectorView(project,scene,shot){
  void project;
  return {
    title:shot?.title||'',
    prompt:shot?.prompt||'',
    negative_prompt:shot?.negative_prompt||'',
    duration_seconds:Number(shot?.duration_seconds)||0,
    seed:Number(shot?.seed)||0,
    camera_motion:shot?.camera_motion||'',
    motion_strength:shot?.motion_strength??null,
    reference_count:shot?.reference_image_ids?.length||0,
    scene_title:scene?.title||'',
    latest_job_id:shot?.latest_job_id||null,
  };
}

export function buildPlanQualityView(plan){
  const native=`${plan?.generation_resolution||'—'} · ${plan?.generation_fps||'—'} FPS`;
  const delivery=`${plan?.delivery_resolution||'—'} · ${plan?.delivery_fps||'—'} FPS target`;
  return {native,delivery,finishingRequired:native.replace(' FPS','')!==delivery.replace(' FPS target','')};
}

export function buildNeutralCinematicView(_project){
  return {title:'Workspace',message:'Private cinematic project is hidden.'};
}

function makeId(){
  if(globalThis.crypto?.randomUUID)return globalThis.crypto.randomUUID().replaceAll('-','');
  let result='';
  for(let i=0;i<32;i++)result+=Math.floor(Math.random()*16).toString(16);
  return result;
}

function clone(value){ return JSON.parse(JSON.stringify(value)); }
function renumberScenes(scenes){
  return scenes.map((scene,index)=>({...scene,ordinal:index+1,shots:(scene.shots||[]).map((shot,shotIndex)=>({...shot,ordinal:shotIndex+1}))}));
}
function selectedObjects(state){
  const mode=state.cinematic;
  const project=mode?.projects?.find(item=>item.id===mode.selection.projectId)||null;
  const scene=project?.scenes?.find(item=>item.scene_id===mode.selection.sceneId)||null;
  const shot=scene?.shots?.find(item=>item.shot_id===mode.selection.shotId)||null;
  return {project,scene,shot};
}
function replaceProject(state,project){
  const mode=state.cinematic;
  mode.projects=[project,...mode.projects.filter(item=>item.id!==project.id)];
  mode.selection=reconcileCinematicSelection(mode.selection,mode.projects);
}
async function persistProjectPatch(state,deps,patch){
  const {project}=selectedObjects(state);
  if(!project)throw new Error('Select a cinematic project first.');
  const updated=await deps.api(`/projects/${encodeURIComponent(project.id)}`,{method:'PUT',body:JSON.stringify({expected_revision:project.revision,...patch})});
  replaceProject(state,updated);
  return updated;
}
async function uploadReferences(files,deps){
  const ids=[];
  for(const file of Array.from(files||[])){
    if(file.size>12*1024*1024)throw new Error(`${file.name||'Image'} exceeds 12 MiB.`);
    const form=new FormData(); form.append('file',file);
    const uploaded=await deps.api('/images',{method:'POST',body:form});
    ids.push(uploaded.image_id);
  }
  return ids;
}
function modeRerender(state,deps){
  renderCinematicInspector(state,deps);
  renderCinematicWorkspace(state,deps);
}
async function refreshProjects(state,deps){
  const projects=await deps.api('/projects');
  state.cinematic.projects=Array.isArray(projects)?projects:[];
  state.cinematic.selection=reconcileCinematicSelection(state.cinematic.selection,state.cinematic.projects);
  modeRerender(state,deps);
}

export async function enterCinematicProjectMode(state,deps){
  state.cinematic={
    active:true,projects:[],selection:{projectId:null,sceneId:null,shotId:null},
    creating:false,plan:null,shotOffsets:{},busy:false,
  };
  deps.setStatus('Opening cinematic project workspace…');
  await refreshProjects(state,deps);
  deps.setStatus(state.cinematic.projects.length?'Cinematic projects ready.':'Create your first long-form film project.');
}

export function exitCinematicProjectMode(state){ if(state)state.cinematic=null; }

function renderProjectList(state,deps,inspector){
  const mode=state.cinematic;
  const prefs=state.privacy?.preferences?.()||{};
  inspector.innerHTML=`<div class="cinematic-head"><div><span class="eyebrow">LONG FILM /</span><h1>Cinematic Projects</h1></div><button id="cinematic-back-quick">Quick Generate</button></div>
    <button id="cinematic-new" class="wide primary">New Film Project</button>
    ${mode.creating?`<div class="cinematic-form">
      <label>Title<input id="cinematic-new-title" maxlength="160" value="Untitled film"></label>
      <label>Target minutes<input id="cinematic-new-minutes" type="number" min="0.17" max="480" step="0.5" value="10"></label>
      <label>Aspect ratio<select id="cinematic-new-aspect"><option>16:9</option><option>9:16</option><option>2.39:1</option><option>1:1</option></select></label>
      <div class="video-grid-2"><label>Delivery<select id="cinematic-new-resolution"><option>1080p</option><option>1440p</option><option selected>2160p</option></select></label><label>FPS target<input id="cinematic-new-fps" type="number" min="1" max="120" value="120"></label></div>
      <label>Master prompt<textarea id="cinematic-new-prompt" maxlength="100000" rows="12" placeholder="Write the entire story, or use SCENE 1: ... markers to control scene boundaries."></textarea></label>
      <button id="cinematic-create" class="wide primary">Create Project</button>
    </div>`:''}
    <h2>Projects</h2><div class="cinematic-project-list">${mode.projects.length?mode.projects.map((project,index)=>{const summary=summarizeProject(project,index,prefs);return `<button class="cinematic-project-card" data-cinematic-project="${escapeHtml(project.id)}"><strong>${escapeHtml(summary.label)}</strong><span>${escapeHtml(summary.duration)} · ${summary.scenes} scenes · ${summary.shots} shots</span><small>${escapeHtml(summary.delivery)}</small></button>`;}).join(''):'<p class="hint">No cinematic projects yet.</p>'}</div>`;
  inspector.querySelector('#cinematic-back-quick').onclick=()=>{ exitCinematicProjectMode(state); deps.onExit?.(); };
  inspector.querySelector('#cinematic-new').onclick=()=>{mode.creating=!mode.creating;renderProjectList(state,deps,inspector);};
  inspector.querySelector('#cinematic-create')?.addEventListener('click',async()=>{
    const prompt=inspector.querySelector('#cinematic-new-prompt').value.trim();
    if(!prompt){deps.setStatus('Enter a master prompt.');return;}
    try{
      deps.setStatus('Creating cinematic project…');
      const minutes=Number(inspector.querySelector('#cinematic-new-minutes').value)||10;
      const created=await deps.api('/projects',{method:'POST',body:JSON.stringify({
        title:inspector.querySelector('#cinematic-new-title').value.trim()||'Untitled film',
        master_prompt:prompt,target_duration_seconds:Math.max(10,Math.round(minutes*60)),
        delivery_fps:Number(inspector.querySelector('#cinematic-new-fps').value)||24,
        delivery_resolution:inspector.querySelector('#cinematic-new-resolution').value,
        aspect_ratio:inspector.querySelector('#cinematic-new-aspect').value,
        continuity_bible:{},reference_image_ids:[],
      })});
      mode.projects=[created,...mode.projects];mode.selection={projectId:created.id,sceneId:null,shotId:null};mode.creating=false;
      modeRerender(state,deps);deps.setStatus('Project created. Add references or compile your master prompt.');
    }catch(error){deps.setStatus(error.message);}
  });
  for(const button of inspector.querySelectorAll('[data-cinematic-project]'))button.onclick=()=>{mode.selection={projectId:button.dataset.cinematicProject,sceneId:null,shotId:null};mode.selection=reconcileCinematicSelection(mode.selection,mode.projects);mode.plan=null;modeRerender(state,deps);};
}

export function renderCinematicInspector(state,deps){
  const inspector=document.getElementById('inspector');
  if(!inspector||!state.cinematic?.active)return;
  const {project}=selectedObjects(state);
  if(!project){renderProjectList(state,deps,inspector);return;}
  const mode=state.cinematic;
  inspector.innerHTML=`<div class="cinematic-head"><div><span class="eyebrow">PROJECT /</span><h1>${escapeHtml(project.title)}</h1></div><button id="cinematic-all-projects">All Projects</button></div>
    <div class="cinematic-revision">Revision ${project.revision} · ${formatDuration(project.target_duration_seconds)} target</div>
    <label>Title<input id="cinematic-title" maxlength="160" value="${escapeHtml(project.title)}"></label>
    <div class="video-grid-2"><label>Seconds<input id="cinematic-target-seconds" type="number" min="10" max="28800" value="${Number(project.target_duration_seconds)||600}"></label><label>Aspect<input id="cinematic-aspect" maxlength="16" value="${escapeHtml(project.aspect_ratio||'16:9')}"></label><label>Delivery<select id="cinematic-delivery-resolution">${['480p','720p','1080p','1440p','2160p'].map(value=>`<option ${value===project.delivery_resolution?'selected':''}>${value}</option>`).join('')}</select></label><label>FPS target<input id="cinematic-delivery-fps" type="number" min="1" max="120" value="${Number(project.delivery_fps)||24}"></label></div>
    <label>Master prompt<textarea id="cinematic-master-prompt" maxlength="100000" rows="14">${escapeHtml(project.master_prompt)}</textarea></label>
    <div class="cinematic-counter">${String(project.master_prompt||'').length.toLocaleString()} / 100,000 chars</div>
    <button id="cinematic-save-project" class="wide">Save project settings</button>
    <label>Project reference images<input id="cinematic-project-refs" type="file" multiple accept="image/png,image/jpeg,image/webp"></label>
    <div class="cinematic-ref-count">${project.reference_image_ids?.length||0} project references</div>
    <label>Preferred shot seconds<input id="cinematic-preferred-shot" type="number" min="1" max="30" step="0.5" value="10"></label>
    <button id="cinematic-compile" class="wide primary">Compile Master Prompt into Scenes + Shots</button>
    <button id="cinematic-quick-hide" class="wide">Quick Hide</button>`;
  inspector.querySelector('#cinematic-all-projects').onclick=()=>{mode.selection={projectId:null,sceneId:null,shotId:null};mode.plan=null;renderProjectList(state,deps,inspector);renderCinematicWorkspace(state,deps);};
  inspector.querySelector('#cinematic-quick-hide').onclick=()=>state.privacy.quickHide();
  inspector.querySelector('#cinematic-save-project').onclick=async()=>{
    try{
      deps.setStatus('Saving project settings…');
      await persistProjectPatch(state,deps,{
        title:inspector.querySelector('#cinematic-title').value.trim()||project.title,
        master_prompt:inspector.querySelector('#cinematic-master-prompt').value,
        target_duration_seconds:Number(inspector.querySelector('#cinematic-target-seconds').value)||project.target_duration_seconds,
        aspect_ratio:inspector.querySelector('#cinematic-aspect').value.trim()||'16:9',
        delivery_resolution:inspector.querySelector('#cinematic-delivery-resolution').value,
        delivery_fps:Number(inspector.querySelector('#cinematic-delivery-fps').value)||24,
      });
      modeRerender(state,deps);deps.setStatus('Project saved.');
    }catch(error){deps.setStatus(error.message);}
  };
  inspector.querySelector('#cinematic-project-refs').onchange=async event=>{
    try{
      deps.setStatus('Uploading project references…');
      const ids=await uploadReferences(event.target.files,deps);
      const latest=selectedObjects(state).project;
      await persistProjectPatch(state,deps,{reference_image_ids:[...(latest.reference_image_ids||[]),...ids]});
      modeRerender(state,deps);deps.setStatus(`${ids.length} reference image${ids.length===1?'':'s'} attached.`);
    }catch(error){deps.setStatus(error.message);}
  };
  inspector.querySelector('#cinematic-compile').onclick=async()=>{
    try{
      const latest=selectedObjects(state).project;
      const engines=state.capabilities?.runtime?.engines||[];
      const available=engines.find(engine=>engine.available)||engines[0];
      const engineMax=Number(available?.max_duration_seconds)||10;
      deps.setStatus('Compiling master prompt into deterministic scene/shot graph…');
      const result=await deps.api(`/projects/${encodeURIComponent(latest.id)}/compile`,{method:'POST',body:JSON.stringify({expected_revision:latest.revision,preferred_shot_seconds:Number(inspector.querySelector('#cinematic-preferred-shot').value)||10,engine_max_duration_seconds:engineMax})});
      replaceProject(state,result.project);mode.plan=null;mode.selection=reconcileCinematicSelection(mode.selection,mode.projects);modeRerender(state,deps);
      deps.setStatus(`Compiled ${result.diagnostics.scene_count} scenes / ${result.diagnostics.shot_count} shots.`);
    }catch(error){deps.setStatus(error.message);}
  };
}

function buildSceneButtons(project,selection){
  return (project.scenes||[]).map(scene=>{const summary=summarizeScene(scene);return `<button class="cinematic-scene-card ${scene.scene_id===selection.sceneId?'selected':''}" data-scene-id="${escapeHtml(scene.scene_id)}"><span>SCENE ${scene.ordinal}</span><strong>${escapeHtml(scene.title)}</strong><small>${summary.shots} shots · ${escapeHtml(summary.duration)}</small></button>`;}).join('');
}

function selectedSceneIndex(project,scene){ return Math.max(0,(project.scenes||[]).findIndex(item=>item.scene_id===scene?.scene_id)); }
function selectedShotIndex(scene,shot){ return Math.max(0,(scene?.shots||[]).findIndex(item=>item.shot_id===shot?.shot_id)); }

async function persistScenes(state,deps,scenes,selectionPatch={}){
  const normalized=renumberScenes(scenes);
  const updated=await persistProjectPatch(state,deps,{scenes:normalized});
  state.cinematic.selection=reconcileCinematicSelection({...state.cinematic.selection,...selectionPatch},state.cinematic.projects);
  state.cinematic.plan=null;
  modeRerender(state,deps);
  return updated;
}

export function renderCinematicWorkspace(state,deps){
  const workspace=document.getElementById('video-workspace');
  if(!workspace||!state.cinematic?.active)return;
  const mode=state.cinematic;
  const {project,scene,shot}=selectedObjects(state);
  if(!project){workspace.innerHTML='<div class="video-empty-stage cinematic-empty"><h2>Long Film Workspace</h2><p>Create or select a cinematic project from the left panel.</p></div>';return;}
  const totalShots=(project.scenes||[]).reduce((sum,item)=>sum+(item.shots?.length||0),0);
  const offset=mode.shotOffsets[scene?.scene_id]||0;
  const window=scene?visibleShotsForScene(scene,{offset,limit:12}):{items:[],total:0,hasMore:false,hasPrevious:false,offset:0};
  const inspector=shot?buildShotInspectorView(project,scene,shot):null;
  const quality=mode.plan?buildPlanQualityView(mode.plan):null;
  workspace.innerHTML=`<div class="cinematic-workspace">
    <div class="cinematic-workspace-head"><div><span class="eyebrow">CINEMATIC TIMELINE /</span><h1>${escapeHtml(project.title)}</h1><p>${formatDuration(project.target_duration_seconds)} target · ${project.scenes?.length||0} scenes · ${totalShots} shots</p></div><div class="cinematic-delivery-badge">${escapeHtml(project.delivery_resolution)} · ${project.delivery_fps} FPS TARGET</div></div>
    <div class="cinematic-scene-strip">${buildSceneButtons(project,mode.selection)||'<div class="hint">Compile your master prompt or add a scene manually.</div>'}</div>
    <div class="cinematic-scene-toolbar"><button id="cinematic-add-scene">+ Scene</button>${scene?'<button id="cinematic-scene-up">↑ Scene</button><button id="cinematic-scene-down">↓ Scene</button><button id="cinematic-delete-scene">Delete Scene</button><label class="cinematic-upload-button">Scene refs<input id="cinematic-scene-refs" type="file" multiple accept="image/png,image/jpeg,image/webp"></label>':''}</div>
    ${scene?`<section class="cinematic-shot-panel"><div class="cinematic-section-head"><div><span class="eyebrow">SCENE ${scene.ordinal}</span><h2>${escapeHtml(scene.title)}</h2></div><span>${window.total} shots · ${formatDuration(summarizeScene(scene).seconds)}</span></div>
      <div class="cinematic-shot-grid">${window.items.map(item=>`<button class="cinematic-shot-card ${item.shot_id===mode.selection.shotId?'selected':''}" data-shot-id="${escapeHtml(item.shot_id)}"><span>#${item.ordinal}</span><strong>${escapeHtml(item.title)}</strong><small>${Number(item.duration_seconds).toFixed(1)}s</small></button>`).join('')}</div>
      <div class="cinematic-page-row"><button id="cinematic-shots-prev" ${window.hasPrevious?'':'disabled'}>Previous shots</button><span>${window.total?window.offset+1:0}–${Math.min(window.offset+window.limit,window.total)} / ${window.total}</span><button id="cinematic-shots-next" ${window.hasMore?'':'disabled'}>Next shots</button></div>
    </section>`:''}
    ${shot?`<section class="cinematic-shot-inspector"><div class="cinematic-section-head"><div><span class="eyebrow">SHOT ${shot.ordinal}</span><h2>Edit Shot</h2></div>${shot.latest_job_id?`<small>Job ${escapeHtml(shot.latest_job_id.slice(0,8))}</small>`:''}</div>
      <div class="cinematic-shot-editor-grid"><label>Title<input id="cinematic-shot-title" maxlength="160" value="${escapeHtml(inspector.title)}"></label><label>Seconds<input id="cinematic-shot-duration" type="number" min="0.1" max="30" step="0.1" value="${inspector.duration_seconds}"></label></div>
      <label>Shot prompt<textarea id="cinematic-shot-prompt" maxlength="20000" rows="6">${escapeHtml(inspector.prompt)}</textarea></label>
      <label>Negative constraints<textarea id="cinematic-shot-negative" maxlength="10000" rows="3">${escapeHtml(inspector.negative_prompt)}</textarea></label>
      <div class="cinematic-shot-editor-grid"><label>Camera<input id="cinematic-shot-camera" maxlength="80" value="${escapeHtml(inspector.camera_motion)}" placeholder="orbit / static / model default"></label><label>Seed<input id="cinematic-shot-seed" type="number" min="0" max="4294967295" value="${inspector.seed}"></label></div>
      <label>Shot reference images<input id="cinematic-shot-refs" type="file" multiple accept="image/png,image/jpeg,image/webp"></label><small>${inspector.reference_count} shot references + inherited project/scene refs</small>
      <div class="cinematic-shot-actions"><button id="cinematic-save-shot">Save Shot</button><button id="cinematic-duplicate-shot">Duplicate</button><button id="cinematic-split-shot">Split</button><button id="cinematic-shot-up">↑</button><button id="cinematic-shot-down">↓</button><button id="cinematic-delete-shot">Delete</button><button id="cinematic-add-shot">+ Shot</button></div>
      <div class="cinematic-render-actions"><button id="cinematic-inspect-plan">Inspect Render Plan</button><button id="cinematic-render-shot" class="primary">Render Selected Shot</button></div>
      ${quality?`<div class="cinematic-quality"><div><span>Native generation</span><strong>${escapeHtml(quality.native)}</strong></div><div><span>Delivery target</span><strong>${escapeHtml(quality.delivery)}</strong></div>${quality.finishingRequired?'<p>Finishing/upscale/interpolation is still required to reach the delivery target.</p>':'<p>Native generation already matches the delivery target.</p>'}</div>`:''}
    </section>`:''}
  </div>`;

  for(const button of workspace.querySelectorAll('[data-scene-id]'))button.onclick=()=>{mode.selection={projectId:project.id,sceneId:button.dataset.sceneId,shotId:null};mode.selection=reconcileCinematicSelection(mode.selection,mode.projects);mode.plan=null;renderCinematicWorkspace(state,deps);};
  for(const button of workspace.querySelectorAll('[data-shot-id]'))button.onclick=()=>{mode.selection.shotId=button.dataset.shotId;mode.plan=null;renderCinematicWorkspace(state,deps);};
  workspace.querySelector('#cinematic-shots-prev')?.addEventListener('click',()=>{mode.shotOffsets[scene.scene_id]=Math.max(0,window.offset-window.limit);renderCinematicWorkspace(state,deps);});
  workspace.querySelector('#cinematic-shots-next')?.addEventListener('click',()=>{mode.shotOffsets[scene.scene_id]=window.offset+window.limit;renderCinematicWorkspace(state,deps);});
  workspace.querySelector('#cinematic-add-scene').onclick=async()=>{
    try{const scenes=clone(project.scenes||[]);const id=makeId();scenes.push({scene_id:id,ordinal:scenes.length+1,title:`Scene ${scenes.length+1}`,synopsis:'',source_text:'',target_duration_seconds:5,reference_image_ids:[],continuity_patch:{},shots:[{shot_id:makeId(),ordinal:1,title:'New shot',prompt:'Describe the shot action.',negative_prompt:'',duration_seconds:5,seed:0,reference_image_ids:[],continuity_patch:{},engine_profile:'balanced'}]});await persistScenes(state,deps,scenes,{sceneId:id,shotId:null});deps.setStatus('Scene added.');}catch(error){deps.setStatus(error.message);}
  };
  if(!scene||!shot)return;
  const sceneIndex=selectedSceneIndex(project,scene);const shotIndex=selectedShotIndex(scene,shot);
  workspace.querySelector('#cinematic-scene-up').onclick=async()=>{if(sceneIndex<=0)return;try{const scenes=clone(project.scenes);[scenes[sceneIndex-1],scenes[sceneIndex]]=[scenes[sceneIndex],scenes[sceneIndex-1]];await persistScenes(state,deps,scenes);}catch(error){deps.setStatus(error.message);}};
  workspace.querySelector('#cinematic-scene-down').onclick=async()=>{if(sceneIndex>=project.scenes.length-1)return;try{const scenes=clone(project.scenes);[scenes[sceneIndex+1],scenes[sceneIndex]]=[scenes[sceneIndex],scenes[sceneIndex+1]];await persistScenes(state,deps,scenes);}catch(error){deps.setStatus(error.message);}};
  workspace.querySelector('#cinematic-delete-scene').onclick=async()=>{try{const scenes=clone(project.scenes).filter(item=>item.scene_id!==scene.scene_id);await persistScenes(state,deps,scenes,{sceneId:null,shotId:null});deps.setStatus('Scene deleted.');}catch(error){deps.setStatus(error.message);}};
  workspace.querySelector('#cinematic-scene-refs').onchange=async event=>{try{const ids=await uploadReferences(event.target.files,deps);const scenes=clone(project.scenes);scenes[sceneIndex].reference_image_ids=[...(scenes[sceneIndex].reference_image_ids||[]),...ids];await persistScenes(state,deps,scenes);deps.setStatus(`${ids.length} scene references attached.`);}catch(error){deps.setStatus(error.message);}};
  workspace.querySelector('#cinematic-save-shot').onclick=async()=>{try{const scenes=clone(project.scenes);const target=scenes[sceneIndex].shots[shotIndex];target.title=workspace.querySelector('#cinematic-shot-title').value.trim()||target.title;target.prompt=workspace.querySelector('#cinematic-shot-prompt').value.trim()||target.prompt;target.negative_prompt=workspace.querySelector('#cinematic-shot-negative').value;target.duration_seconds=Number(workspace.querySelector('#cinematic-shot-duration').value)||target.duration_seconds;target.seed=Number(workspace.querySelector('#cinematic-shot-seed').value)||0;target.camera_motion=workspace.querySelector('#cinematic-shot-camera').value.trim()||null;await persistScenes(state,deps,scenes);deps.setStatus('Shot saved.');}catch(error){deps.setStatus(error.message);}};
  workspace.querySelector('#cinematic-shot-refs').onchange=async event=>{try{const ids=await uploadReferences(event.target.files,deps);const scenes=clone(project.scenes);scenes[sceneIndex].shots[shotIndex].reference_image_ids=[...(scenes[sceneIndex].shots[shotIndex].reference_image_ids||[]),...ids];await persistScenes(state,deps,scenes);deps.setStatus(`${ids.length} shot references attached.`);}catch(error){deps.setStatus(error.message);}};
  workspace.querySelector('#cinematic-duplicate-shot').onclick=async()=>{try{const scenes=clone(project.scenes);const duplicate={...clone(scenes[sceneIndex].shots[shotIndex]),shot_id:makeId(),title:`${shot.title} copy`,latest_job_id:null,latest_asset_url:null,latest_rendered_project_revision:null};scenes[sceneIndex].shots.splice(shotIndex+1,0,duplicate);await persistScenes(state,deps,scenes,{shotId:duplicate.shot_id});deps.setStatus('Shot duplicated.');}catch(error){deps.setStatus(error.message);}};
  workspace.querySelector('#cinematic-split-shot').onclick=async()=>{if(Number(shot.duration_seconds)<=0.2){deps.setStatus('Shot is too short to split.');return;}try{const scenes=clone(project.scenes);const original=scenes[sceneIndex].shots[shotIndex];const first={...clone(original),shot_id:makeId(),title:`${original.title} A`,duration_seconds:Number(original.duration_seconds)/2,latest_job_id:null,latest_asset_url:null,latest_rendered_project_revision:null};const second={...clone(original),shot_id:makeId(),title:`${original.title} B`,duration_seconds:Number(original.duration_seconds)-first.duration_seconds,latest_job_id:null,latest_asset_url:null,latest_rendered_project_revision:null};scenes[sceneIndex].shots.splice(shotIndex,1,first,second);await persistScenes(state,deps,scenes,{shotId:first.shot_id});deps.setStatus('Shot split into two continuous beats.');}catch(error){deps.setStatus(error.message);}};
  workspace.querySelector('#cinematic-add-shot').onclick=async()=>{try{const scenes=clone(project.scenes);const created={shot_id:makeId(),ordinal:1,title:'New shot',prompt:'Describe the shot action.',negative_prompt:'',duration_seconds:5,seed:0,reference_image_ids:[],continuity_patch:{},engine_profile:'balanced'};scenes[sceneIndex].shots.splice(shotIndex+1,0,created);await persistScenes(state,deps,scenes,{shotId:created.shot_id});deps.setStatus('Shot added.');}catch(error){deps.setStatus(error.message);}};
  workspace.querySelector('#cinematic-delete-shot').onclick=async()=>{try{const scenes=clone(project.scenes);scenes[sceneIndex].shots.splice(shotIndex,1);await persistScenes(state,deps,scenes,{shotId:null});deps.setStatus('Shot deleted.');}catch(error){deps.setStatus(error.message);}};
  workspace.querySelector('#cinematic-shot-up').onclick=async()=>{if(shotIndex<=0)return;try{const scenes=clone(project.scenes);const shots=scenes[sceneIndex].shots;[shots[shotIndex-1],shots[shotIndex]]=[shots[shotIndex],shots[shotIndex-1]];await persistScenes(state,deps,scenes);}catch(error){deps.setStatus(error.message);}};
  workspace.querySelector('#cinematic-shot-down').onclick=async()=>{if(shotIndex>=scene.shots.length-1)return;try{const scenes=clone(project.scenes);const shots=scenes[sceneIndex].shots;[shots[shotIndex+1],shots[shotIndex]]=[shots[shotIndex],shots[shotIndex+1]];await persistScenes(state,deps,scenes);}catch(error){deps.setStatus(error.message);}};
  workspace.querySelector('#cinematic-inspect-plan').onclick=async()=>{try{deps.setStatus('Inspecting native generation plan…');mode.plan=await deps.api(`/projects/${encodeURIComponent(project.id)}/scenes/${encodeURIComponent(scene.scene_id)}/shots/${encodeURIComponent(shot.shot_id)}/plan`);renderCinematicWorkspace(state,deps);deps.setStatus('Render plan ready.');}catch(error){deps.setStatus(error.message);}};
  workspace.querySelector('#cinematic-render-shot').onclick=async()=>{try{deps.setStatus('Submitting selected shot to the local render queue…');const result=await deps.api(`/projects/${encodeURIComponent(project.id)}/scenes/${encodeURIComponent(scene.scene_id)}/shots/${encodeURIComponent(shot.shot_id)}/render`,{method:'POST',body:JSON.stringify({expected_revision:project.revision})});replaceProject(state,result.project);mode.plan=result.plan;state.jobs=[result.job,...(state.jobs||[]).filter(item=>item.id!==result.job.id)];state.activeJob=result.job;modeRerender(state,deps);deps.pollJob?.(result.job.id,state);deps.setStatus('Shot queued.');}catch(error){deps.setStatus(error.message);}};
}
