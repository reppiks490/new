import {StudioView,characterGeometry,terrainGeometry,MAX_GLB_BYTES} from './engine.js';
import {loadAvatarAssets,avatarOptions,avatarAsset} from './avatar-assets.js';
import {loadBundledLibrary,downloadBundledModel} from './bundled-library.js';

const $=id=>document.getElementById(id), esc=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const defaults=()=>({base:'female',controls:{},extreme:false,skin:'#b77f60',cloth:'#253d65',iris:'#527c83',outfit:'female_casualsuit01',hair:'long01',shoes:'shoes01',skinTexture:true,attachments:[]});
let state=defaults(), data,catalog,tab='models',kind='empty',group='curves',search='',category='fashion',wardrobePage=0,mature=false,linked=true;
let backend='',token='',capabilities=null,reference=null,uploadedImage=null,updateTimer,history=[],future=[],jobs=[],terrain={seed:7,size:200,height:35,resolution:6};
let baseAssetsPromise,modelLibrary=null,librarySource=null,libraryError='',libraryLoading=false,modelLoading=false,activeModel=null,morphSearch='',sculptPicking=false;
const groups={curves:'Breasts & glutes',breast:'Breasts',armslegs:'Arms, legs, hands & feet',head:'Head',eyes:'Eyes',nose:'Nose',mouth:'Mouth',ears:'Ears',cheek:'Cheeks',chin:'Chin & jaw',forehead:'Forehead',eyebrows:'Brows',neck:'Neck',torso:'Torso',hip:'Hips',pelvis:'Pelvis',stomach:'Abdomen',buttocks:'Glutes'};
const view=new StudioView($('canvas'),text=>$('mesh-stats').textContent=text);
function stopSculptPicking(){sculptPicking=false;$('canvas').classList.remove('sculpt-picking');}
$('canvas').addEventListener('click',event=>{
  if(!sculptPicking)return;
  try{const target=view.pickSurface(event.clientX,event.clientY);stopSculptPicking();if(tab==='body')showImportedControls();status(`Picked ${target.mesh}. Use a sculpt prompt to inflate or shrink this surface area.`);}
  catch(error){status(error.message);}
});
function status(text){$('status').textContent=text;}
function remember(){history.push(structuredClone(state));if(history.length>80)history.shift();future=[];if($('undo'))$('undo').disabled=false;}
function hasModel(){return Boolean(view.object);}
function enableModelActions(){$('export').disabled=!hasModel();$('save').disabled=!hasModel();}
function renderCharacter(reframe=false){view.replace(characterGeometry(data,state,catalog),reframe);kind='character';activeModel=null;enableModelActions();$('view-label').textContent='Character';$('mode-badge').textContent=state.extreme?'Extended morph range':avatarAsset(state.outfit)?'Textured character':'Surface garment';}
async function ensureBaseAssets(){
  if(data)return;
  if(!baseAssetsPromise)baseAssetsPromise=Promise.all([fetch('/studio/data/human.json').then(r=>{if(!r.ok)throw Error('Character data could not be loaded');return r.json();}),fetch('/studio/data/wardrobe.json').then(r=>{if(!r.ok)throw Error('Wardrobe data could not be loaded');return r.json();}),loadAvatarAssets()]).then(([human,wardrobe])=>{data=human;catalog=wardrobe;}).catch(error=>{baseAssetsPromise=null;throw error;});
  await baseAssetsPromise;
}
async function loadSupportedBase(){try{status('Loading supported character assets…');await ensureBaseAssets();renderCharacter(true);await renderPanel();status('Supported character base loaded.');}catch(error){status(error.message);}}
function scheduleUpdate(){clearTimeout(updateTimer);updateTimer=setTimeout(()=>{try{renderCharacter();}catch(e){status(e.message);}},60);}
function setValue(id,value){state.controls[id]=Math.max(state.extreme?-150:-100,Math.min(state.extreme?150:100,Number(value)||0));if(linked){const opposite=id.startsWith('l-')?'r-'+id.slice(2):id.startsWith('r-')?'l-'+id.slice(2):null;if(opposite&&data.controls.some(c=>c.id===opposite)){state.controls[opposite]=state.controls[id];for(const prefix of ['slider-','number-']){const input=$(prefix+opposite);if(input)input.value=state.controls[opposite];}}}scheduleUpdate();}
function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);}
function downloadDataURL(url,name){const a=document.createElement('a');a.href=url;a.download=name;a.click();}
function heading(title,subtitle){return `<h1>${title}</h1><p>${subtitle}</p>`;}
function connectDialog(){$('backend-url').value=backend||location.origin;$('connection-dialog').showModal();}
function formatBytes(bytes){return Number.isFinite(bytes)?`${(bytes/1024/1024).toFixed(1)} MiB`:'Size unavailable';}
function validModelId(id){return typeof id==='string'&&/^[a-zA-Z0-9_-]{1,128}$/.test(id);}
function sourceCredit(value){return typeof value==='string'?value:value?JSON.stringify(value):'No creator credit supplied';}
function updateConnectionStatus(){$('backend-status').textContent=capabilities?.backend?'Worker connected':librarySource==='bundled'?'Browser mode · bundled library':'Browser mode · no worker';}
const editTargets=[
  {keys:['breast','bust'],test:s=>/\b(projection|project)\b/.test(s)?'breast-projection':/\b(width|wider|narrower)\b/.test(s)?'breast-width':/\b(upper|top)\b/.test(s)?'breast-upper-fullness':/\b(lower|bottom)\b/.test(s)?'breast-lower-fullness':'breast-size'},
  {keys:['butt','glute','rear'],test:s=>/\b(projection|project)\b/.test(s)?'glute-projection':/\b(width|wider|narrower)\b/.test(s)?'glute-width':/\b(lift|higher)\b/.test(s)?'glute-lift':/\b(round|rounder)\b/.test(s)?'glute-roundness':'buttocks-volume'},
  {keys:['hip'],test:s=>/\b(depth|deeper)\b/.test(s)?'hip-scale-depth':'hip-scale-horiz'},
  {keys:['chest','pectoral'],test:()=> 'torso-muscle-pectoral'},
  {keys:['stomach','abdomen','belly'],test:()=> 'stomach-tone'},
];
function parsePromptParts(prompt,available){
  if(typeof prompt!=='string'||prompt.length>2000)throw Error('Keep the edit prompt under 2,000 characters.');
  const parts=prompt.toLowerCase().split(/\s+(?:and|then)\s+|[,;\n]+/).map(s=>s.trim()).filter(Boolean),edits=[];
  for(const part of parts){
    const target=editTargets.find(item=>item.keys.some(key=>new RegExp(`\\b${key}s?\\b`).test(part)));
    let entry;
    if(target){const id=target.test(part);entry=available.find(c=>c.id===id)||available.find(c=>`${c.label} ${c.mesh||''}`.toLowerCase().includes(target.keys[0]));}
    else entry=available.map(c=>({c,words:String(c.label||'').toLowerCase().split(/[\s_.:/-]+/).filter(w=>w.length>2)}).filter(x=>x.words.some(w=>new RegExp(`\\b${w}\\b`).test(part))).sort((a,b)=>Math.max(...b.words.map(w=>w.length))-Math.max(...a.words.map(w=>w.length)))[0]?.c;
    if(!entry)continue;
    const amountMatch=part.match(/([+-]?\d+(?:\.\d+)?)\s*%?/),worded=/\b(slightly|subtly|a little)\b/.test(part)?15:/\b(much|drastically|a lot|significantly)\b/.test(part)?75:40;
    let amount=amountMatch?Number(amountMatch[1]):worded;
    if(/\b(smaller|reduce|reduc|decrease|less|shrink|narrower)\b/.test(part)&&amount>0)amount=-amount;
    const isSet=/\b(set|make|to)\b/.test(part)&&/\bto\b/.test(part);
    edits.push({entry,value:isSet?amount:entry.value+amount,delta:amount,isSet,label:entry.label});
  }
  return edits;
}
function applyBodyPrompt(){
  try{
    const edits=parsePromptParts($('body-edit-prompt').value,data.controls.map(c=>({...c,value:Number(state.controls[c.id]||0)})));
    if(!edits.length)throw Error('I could not match that prompt to a supported body control. Try “increase breast size by 40% and glute size by 30%.”');
    remember();
    for(const edit of edits)state.controls[edit.entry.id]=Math.max(state.extreme?-150:-100,Math.min(state.extreme?150:100,edit.value));
    renderCharacter();showBody();status(`Applied prompt to ${edits.map(e=>e.label).join(', ')}.`);
  }catch(error){status(error.message);}
}
function applySourcePrompt(){
  try{
    const edits=parsePromptParts($('body-edit-prompt').value,view.getMorphControls());
    if(!edits.length)throw Error('This model has no matching authored shape target. Open Body → Edit an adult base to use the full proportion controls.');
    for(const edit of edits){const range=edit.entry.max-edit.entry.min,value=edit.isSet?edit.entry.min+edit.value/100*range:edit.entry.value+edit.delta/100*range;view.setMorph(edit.entry.id,Math.max(edit.entry.min,Math.min(edit.entry.max,value)));}
    showImportedControls();status(`Applied source prompt to ${edits.map(e=>e.label).join(', ')}.`);
  }catch(error){status(error.message);}
}
function applySculptPrompt(){
  try{const result=view.sculptFromPrompt($('sculpt-prompt').value,Number($('sculpt-radius').value)/100);showImportedControls();status(`Applied localized sculpt: ${result.affected_vertices.toLocaleString()} vertices changed. Export GLB to keep the edit.`);}
  catch(error){status(error.message);}
}
function showModels(){
  const sorted=[...(modelLibrary||[])].sort((a,b)=>Number(/street[ _-]*fighter/i.test(b.name+' '+b.source_filename))-Number(/street[ _-]*fighter/i.test(a.name+' '+a.source_filename))||String(a.name).localeCompare(String(b.name)));
  $('inspector').innerHTML=heading('Your model library','Source models with their original materials, textures, rigs, and authored shape targets.')+
    '<div class="row"><button id="refresh-models">Refresh library</button><button id="models-connect">Connect worker</button></div>'+
    '<p class="hint">Files download only when you open them. Street Fighter models appear first. Source animation clips are preserved in exports; playback is off.</p>'+
    (libraryError?`<div class="notice" role="alert">${esc(libraryError)}</div>`:'')+
    (libraryLoading?'<p class="loading" role="status">Reading model inventory…</p>':sorted.length?`<div class="model-library">${sorted.map(model=>`<article class="model-card ${activeModel?.id===model.id?'active-model':''}"><div class="model-card-heading"><span class="eyebrow">${/street[ _-]*fighter/i.test(model.name+' '+model.source_filename)?'PRIORITY MODEL':'SOURCE MODEL'}</span>${activeModel?.id===model.id?'<span class="badge">Open</span>':''}</div><h2>${esc(model.name)}</h2><p class="model-file">${esc(model.source_filename||'GLB asset')}</p><dl class="model-stats"><div><dt>File</dt><dd>${formatBytes(model.bytes)}</dd></div><div><dt>Triangles</dt><dd>${Number(model.triangle_count||0).toLocaleString()}</dd></div><div><dt>Materials</dt><dd>${Number(model.material_count||0)}</dd></div><div><dt>Skins / clips</dt><dd>${Number(model.skin_count||0)} / ${Number(model.animation_count||0)}</dd></div></dl><p class="hint">${Number(model.morph_target_count||0)} source morph targets · ${esc(typeof model.readiness==='string'?model.readiness:'Source inspected')}</p><details><summary>Source information</summary><p class="hint">${esc(sourceCredit(model.source_credit))}</p><p class="hint">License: ${esc(sourceCredit(model.license_status||'Not supplied'))}</p></details>${model.preview_allowed===false?'<p class="notice">Source review required before preview.</p>':''}<button class="wide primary" data-load-model="${esc(model.id)}" ${modelLoading||model.preview_allowed===false?'disabled':''}>${modelLoading?'Loading model…':'Open model'}</button></article>`).join('')}</div>`:'<div class="empty">No model inventory loaded. Refresh to load bundled files, or connect your worker.</div>')+
    '<button class="wide" id="models-import-local">Import a local GLB</button>';
  $('models-connect').onclick=connectDialog;$('refresh-models').onclick=refreshModels;$('refresh-models').disabled=libraryLoading;
  $('models-import-local').onclick=()=>{tab='create';renderPanel();$('creation-mode').value='import';creationFields();};
  for(const button of document.querySelectorAll('[data-load-model]'))button.onclick=()=>loadLibraryModel(button.dataset.loadModel).catch(error=>status(error.message));
}
async function refreshModels(){
  if(libraryLoading)return;
  libraryLoading=true;libraryError='';if(tab==='models')showModels();
  try{
    try{const result=await api('/models');if(!Array.isArray(result))throw Error('Worker returned an invalid model inventory');modelLibrary=result.filter(m=>m&&validModelId(m.id));librarySource='worker';}
    catch(error){if(backend)throw error;modelLibrary=await loadBundledLibrary({origin:location.origin,maxBytes:MAX_GLB_BYTES});librarySource='bundled';}
  }catch(error){modelLibrary=null;librarySource=null;libraryError=`Model library unavailable: ${error.message}. Connect your worker and try again.`;}
  finally{libraryLoading=false;updateConnectionStatus();if(tab==='models')showModels();}
}
async function downloadModel(url){
  const target=new URL(url,backend||location.origin),origin=new URL(backend||location.origin).origin;
  if(target.origin!==origin||!target.pathname.startsWith('/api/studio/')||target.username||target.password)throw Error('Worker supplied an unsupported model URL');
  const response=await fetch(target,{headers:token?{'Authorization':'Bearer '+token}:{},signal:AbortSignal.timeout(120000)});
  if(!response.ok)throw Error(`Model download failed (${response.status})`);
  if(Number(response.headers.get('content-length'))>MAX_GLB_BYTES)throw Error('Model exceeds 150 MiB');
  if(!response.body){const buffer=await response.arrayBuffer();if(buffer.byteLength>MAX_GLB_BYTES)throw Error('Model exceeds 150 MiB');return buffer;}
  const reader=response.body.getReader(),chunks=[];let bytes=0;
  try{while(true){const {done,value}=await reader.read();if(done)break;bytes+=value.byteLength;if(bytes>MAX_GLB_BYTES)throw Error('Model exceeds 150 MiB');chunks.push(value);status(`Downloading model · ${formatBytes(bytes)}`);}}
  catch(error){await reader.cancel().catch(()=>{});throw error;}finally{reader.releaseLock();}
  const result=new Uint8Array(bytes);let offset=0;for(const chunk of chunks){result.set(chunk,offset);offset+=chunk.byteLength;}return result.buffer;
}
async function loadLibraryModel(id,project=null){
  if(modelLoading)throw Error('Wait for the current model to finish loading.');
  if(!validModelId(id))throw Error('Invalid model identifier');
  modelLoading=true;clearTimeout(updateTimer);if(tab==='models')showModels();
  try{
    status('Reading model source…');
    if(!modelLibrary)await refreshModels();
    const bundled=!backend&&librarySource==='bundled';
    const model=bundled?modelLibrary.find(item=>item.id===id):await api('/models/'+encodeURIComponent(id));
    if(!model)throw Error('This source model is not available in the current library.');
    if(model.preview_allowed===false)throw Error('This source is awaiting review before preview.');
    if(!/^[0-9a-f]{64}$/i.test(model.sha256||''))throw Error('Model source has no valid integrity hash');
    if(project&&project.source_sha256!==model.sha256)throw Error('The source model has changed since this project was saved. Reopen the current model separately.');
    const buffer=bundled?await downloadBundledModel(model,{origin:location.origin,maxBytes:MAX_GLB_BYTES,onProgress:bytes=>status(`Downloading bundled model · ${formatBytes(bytes)}`)}):await downloadModel(model.asset_url);
    const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',buffer)),n=>n.toString(16).padStart(2,'0')).join('');
    if(digest!==model.sha256.toLowerCase())throw Error('Downloaded model does not match its registered source hash');
    status('Preparing original materials and geometry…');await view.import(buffer);kind='model';activeModel=model;morphSearch='';enableModelActions();
    $('view-label').textContent=model.name;$('mode-badge').textContent='Original source model';$('project-name').value=project?.name||model.name;
    if(project){for(const operation of project.sculpt_ops||[])view.applySculptOperation(operation);view.applyMorphValues(project.morphs);}
    tab='body';await renderPanel();
    status(`${model.name} opened. Body editing options are shown; source materials and ${view.animations.length} animation clips retained.`);
  }finally{modelLoading=false;if(tab==='models')showModels();else if(tab==='body')showImportedControls();}
}
function showImportedControls(){
  const controls=view.getMorphControls(),filtered=controls.filter(c=>(c.label+' '+c.mesh).toLowerCase().includes(morphSearch.toLowerCase()));
  $('inspector').innerHTML=heading('Edit this model','Prompt edits use shape targets already inside this file; the source mesh is preserved.')+
    `<h2>Direct surface sculpt</h2><p class="hint">Pick a point on the model, then inflate or shrink that mesh area. Separate clothing meshes need their own pass.</p><button id="pick-sculpt-area" class="wide" aria-pressed="${sculptPicking}">${sculptPicking?'Click a model area…':'Pick an area in the 3D view'}</button><p class="hint">${view.sculptSelection?`Selected mesh: ${esc(view.sculptSelection.mesh.name||`Mesh ${view.sculptSelection.meshIndex+1}`)}`:'No surface area selected.'}</p><label for="sculpt-radius">Sculpt radius · <span id="sculpt-radius-label">12%</span> of mesh</label><input id="sculpt-radius" type="range" min="4" max="35" step="1" value="12"><label for="sculpt-prompt">Prompt for selected area</label><textarea id="sculpt-prompt" maxlength="500" placeholder="Make this area fuller by 30%"></textarea><button id="apply-sculpt-prompt" class="wide primary" ${view.sculptSelection?'':'disabled'}>Apply localized sculpt</button><p class="hint">Each edit becomes a shape key, so it can be adjusted below and is saved in model projects.</p>`+
    (controls.length?`<label for="body-edit-prompt">Prompt to edit</label><textarea id="body-edit-prompt" maxlength="2000" placeholder="Change a feature that has a matching source shape key"></textarea><button class="wide primary" id="apply-edit-prompt">Apply prompt to source</button>`:'')+
    (controls.length?`<input id="source-morph-search" class="search" type="search" aria-label="Search source shape targets" placeholder="Search source shape targets" value="${esc(morphSearch)}"><button id="reset-source-morphs" class="wide">Restore source values</button><p class="hint">${filtered.length} of ${controls.length} targets. Clothing follows only when the source includes matching deformation.</p><div id="source-morph-list">${filtered.map(c=>`<div class="slider-row"><div class="slider-title"><label for="source-${c.id}">${esc(c.label)}</label><input type="number" data-source-number="${c.id}" min="${c.min}" max="${c.max}" step="0.01" value="${c.value}" aria-label="${esc(c.label)} numeric value"></div><input id="source-${c.id}" data-source-morph="${c.id}" type="range" min="${c.min}" max="${c.max}" step="0.01" value="${c.value}"><p class="control-description">${esc(c.mesh)}</p></div>`).join('')}</div>`:'<div class="notice">This model contains no editable source shape targets. Its original geometry, materials, and rig are preserved.</div>')+
    (!controls.length?'<div class="notice">This file has no authored body shape keys, so its imported geometry cannot be reshaped here. The editable adult character base below has dedicated body controls and prompt edits.</div><button class="wide primary" id="edit-adult-base">Open the editable adult character base</button>':'')+
    `<p class="hint">${view.animations?.length||0} embedded animation clips retained. No animation plays automatically.</p>${controls.length?'<button class="wide" id="return-base">Load supported character base</button>':''}`;
  if(controls.length)$('apply-edit-prompt').onclick=applySourcePrompt;
  $('pick-sculpt-area').onclick=()=>{sculptPicking=!sculptPicking;$('canvas').classList.toggle('sculpt-picking',sculptPicking);$('pick-sculpt-area').setAttribute('aria-pressed',String(sculptPicking));$('pick-sculpt-area').textContent=sculptPicking?'Click a model area…':'Pick an area in the 3D view';status(sculptPicking?'Click a visible mesh area in the preview.':'Surface picking canceled.');};
  $('sculpt-radius').oninput=e=>{$('sculpt-radius-label').textContent=`${e.target.value}%`;};
  $('apply-sculpt-prompt').onclick=applySculptPrompt;
  if($('edit-adult-base'))$('edit-adult-base').onclick=loadSupportedBase;
  if($('return-base'))$('return-base').onclick=loadSupportedBase;
  if(!controls.length)return;
  $('source-morph-search').oninput=e=>{const start=e.target.selectionStart;morphSearch=e.target.value;showImportedControls();$('source-morph-search').focus();$('source-morph-search').setSelectionRange(start,start);};
  $('reset-source-morphs').onclick=()=>{view.resetMorphs();showImportedControls();status('Original source morph values restored.');};
  for(const input of document.querySelectorAll('[data-source-morph]'))input.oninput=()=>{try{view.setMorph(input.dataset.sourceMorph,Number(input.value));document.querySelector(`[data-source-number="${input.dataset.sourceMorph}"]`).value=input.value;}catch(error){status(error.message);}};
  for(const input of document.querySelectorAll('[data-source-number]'))input.onchange=()=>{try{view.setMorph(input.dataset.sourceNumber,Number(input.value));$('source-'+input.dataset.sourceNumber).value=input.value;}catch(error){input.value=view.getMorphControls().find(c=>c.id===input.dataset.sourceNumber).value;status(error.message);}};
}
function controlList(){
  const selected=data.controls.filter(c=>(search?`${c.label} ${groups[c.group]}`.toLowerCase().includes(search.toLowerCase()):group==='curves'?['breast','buttocks'].includes(c.group):c.group===group));
  const priority=['breast-size','buttocks-volume','breast-projection','glute-projection','breast-width','glute-width'];
  if(group==='curves'&&!search)selected.sort((a,b)=>(priority.includes(a.id)?priority.indexOf(a.id):100)-(priority.includes(b.id)?priority.indexOf(b.id):100));
  $('control-list').innerHTML=selected.map(c=>`<div class="slider-row ${['breast-size','buttocks-volume'].includes(c.id)?'featured-control':''}"><div class="slider-title"><label for="slider-${c.id}">${esc(c.label)}</label><input id="number-${c.id}" data-number="${c.id}" type="number" min="${state.extreme?-150:-100}" max="${state.extreme?150:100}" step="1" value="${state.controls[c.id]||0}" aria-label="${esc(c.label)} numeric value"></div><input id="slider-${c.id}" data-control="${c.id}" type="range" min="${state.extreme?-150:-100}" max="${state.extreme?150:100}" step="1" value="${state.controls[c.id]||0}"><div class="ends"><span>${state.extreme?-150:-100}%</span><span>Neutral · 0</span><span>${state.extreme?150:100}%</span></div>${c.description?`<p class="control-description">${esc(c.description)}</p>`:''}</div>`).join('')||'<div class="empty">No matching controls.</div>';
  $('control-count').textContent=`${selected.length} shown / ${data.controls.length}`;
  for(const input of document.querySelectorAll('[data-control]')){
    let editing=false;input.addEventListener('pointerdown',()=>{remember();editing=true;});input.addEventListener('keydown',()=>{if(!editing){remember();editing=true;}});
    input.addEventListener('input',()=>{if(!editing){remember();editing=true;}setValue(input.dataset.control,input.value);$(`number-${input.dataset.control}`).value=state.controls[input.dataset.control];});input.addEventListener('change',()=>editing=false);
  }
  for(const input of document.querySelectorAll('[data-number]'))input.addEventListener('change',()=>{remember();setValue(input.dataset.number,input.value);input.value=state.controls[input.dataset.number];$(`slider-${input.dataset.number}`).value=input.value;});
}
function showBody(){
  if(kind==='model'||kind==='import'){showImportedControls();return;}
  if(kind!=='character'){ $('inspector').innerHTML=heading('Body studio','Load the supported character base to edit its authored controls.')+'<button class="wide primary" id="return-base">Load supported base</button>'; $('return-base').onclick=loadSupportedBase;return;}
  $('inspector').innerHTML=heading('Body studio',`Prompt edits and ${data.controls.length} proportion controls for this editable adult base.`)+
    `<label for="body-edit-prompt">Prompt to edit</label><textarea id="body-edit-prompt" maxlength="2000" placeholder="Increase breast size by 40% and glute size by 30%"></textarea><button id="apply-edit-prompt" class="wide primary">Apply body prompt</button><p class="hint">Prompt percentages set or adjust the authored controls below; changes appear immediately in the preview.</p><div class="focus-regions"><button id="focus-breasts">Breasts</button><button id="focus-glutes">Glutes</button><button id="focus-both">Both</button></div><label>Adult base<select id="base"><option value="female">Feminine adult base</option><option value="male">Masculine adult base</option></select></label><div class="inline-tools"><button id="undo" ${history.length?'':'disabled'}>Undo</button><button id="redo" ${future.length?'':'disabled'}>Redo</button><button id="reset-group">Reset region</button><button id="reset-all">Reset all</button></div><label class="check"><input type="checkbox" id="link" ${linked?'checked':''}>Link left and right</label><label class="check"><input type="checkbox" id="extreme" ${state.extreme?'checked':''}>Extended range · experimental</label><p class="hint">Standard targets: −100 to +100%. Extended targets: ±150%. Extreme combinations need mesh and garment inspection.</p><input class="search" id="control-search" type="search" placeholder="Search all body controls" aria-label="Search body controls" value="${esc(search)}"><label>Region<select id="region">${Object.entries(groups).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label><div class="section-line"><h2>Shape controls</h2><span id="control-count"></span></div><div id="control-list"></div><p class="hint">CC0 authored targets + localized sculpt deltas · static character. Bone retargeting and animation correctives are not included.</p>`;
  $('apply-edit-prompt').onclick=applyBodyPrompt;
  for(const [id,value] of [['focus-breasts','breast'],['focus-glutes','buttocks'],['focus-both','curves']])$(id).onclick=()=>{group=value;search='';$('control-search').value='';$('region').value=group;controlList();};
  $('base').value=state.base;$('base').onchange=e=>{remember();state.base=e.target.value;renderCharacter();};
  $('region').value=group;$('region').onchange=e=>{group=e.target.value;controlList();};
  $('control-search').oninput=e=>{search=e.target.value;controlList();};$('link').onchange=e=>linked=e.target.checked;
  $('extreme').onchange=e=>{remember();state.extreme=e.target.checked;if(!state.extreme)for(const k in state.controls)state.controls[k]=Math.max(-100,Math.min(100,state.controls[k]));showBody();renderCharacter();};
  $('undo').onclick=()=>{future.push(structuredClone(state));state=history.pop();renderCharacter();showBody();};
  $('redo').onclick=()=>{history.push(structuredClone(state));state=future.pop();renderCharacter();showBody();};
  $('reset-all').onclick=()=>{remember();state.controls={};renderCharacter();controlList();status('All body morphs reset.');};
  $('reset-group').onclick=()=>{remember();for(const c of data.controls.filter(c=>group==='curves'?['breast','buttocks'].includes(c.group):c.group===group))delete state.controls[c.id];renderCharacter();controlList();};controlList();
}
function showWardrobe(){
  if(kind!=='character'){showSourceAppearance();return;}
  $('inspector').innerHTML=heading('Wardrobe','Authored outfits with separate geometry, fabric textures, and fitted details.')+
  `<div class="authored-outfits">${avatarOptions('garment').map(a=>`<button class="outfit ${state.outfit===a.id?'selected':''}" data-authored-outfit="${a.id}"><img src="/studio/data/quality-assets/${a.id}_thumb.png" alt="${esc(a.label)} outfit"><strong>${esc(a.label)}</strong><small>Authored mesh & textures</small></button>`).join('')}</div><label>Footwear<select id="shoes"><option value="none">Bare feet</option>${avatarOptions('shoes').map(a=>`<option value="${a.id}">${esc(a.label)}</option>`).join('')}</select></label><h2>Surface design library</h2><p class="hint">360 procedural cut variations. These are fitting templates with less detail than the authored outfits above.</p>`+
  `<label class="check"><input type="checkbox" id="mature" ${mature?'checked':''}>Show mature fashion</label><label>Collection<select id="category"><option value="fashion">Fashion · 200</option><option value="custom">Custom cuts · 80</option><option value="bikini">Bikinis · 40</option><option value="lingerie">Lingerie · 20</option><option value="bodysuit">Body suits · 20</option></select></label><label>Fabric color<input id="fabric-color" type="color" value="${state.cloth}"></label><div class="notice">These garments follow the edited surface. They are fitted shells, not simulated fabric or animation-tested couture.</div><div id="outfit-list"></div><div class="row"><button id="prev-page">Previous</button><span id="page-label" class="hint"></span><button id="next-page">Next</button></div>`;
  for(const button of document.querySelectorAll('[data-authored-outfit]'))button.onclick=()=>{remember();state.outfit=button.dataset.authoredOutfit;renderCharacter(kind!=='character');showWardrobe();status('Authored outfit fitted to the current character.');};
  $('shoes').value=state.shoes||'none';$('shoes').onchange=e=>{remember();state.shoes=e.target.value;renderCharacter(kind!=='character');};
  $('category').value=category;$('category').onchange=e=>{category=e.target.value;wardrobePage=0;wardrobeList();};$('mature').onchange=e=>{mature=e.target.checked;wardrobePage=0;wardrobeList();};
  $('fabric-color').onchange=e=>{remember();state.cloth=e.target.value;scheduleUpdate();};wardrobeList();
}
function wardrobeList(){
  const list=catalog.filter(x=>x.category===category&&(mature||x.coverage==='standard')),pages=Math.max(1,Math.ceil(list.length/12));wardrobePage=Math.min(wardrobePage,pages-1);
  $('outfit-list').innerHTML=list.length?`<div class="catalog">${list.slice(wardrobePage*12,wardrobePage*12+12).map(item=>`<button class="outfit ${state.outfit===item.id?'selected':''}" data-outfit="${item.id}" aria-pressed="${state.outfit===item.id}"><div class="swatch">${String(item.design+1).padStart(2,'0')}</div><strong>${esc(item.name)}</strong><small>Surface recipe · ${item.design+1}</small></button>`).join('')}</div>`:'<div class="empty">Enable mature fashion to browse this collection.</div>';
  for(const b of document.querySelectorAll('[data-outfit]'))b.onclick=()=>{remember();state.outfit=b.dataset.outfit;renderCharacter(kind!=='character');wardrobeList();status('Garment equipped. Inspect surface fit before export.');};
  $('page-label').textContent=`${wardrobePage+1} / ${pages}`;$('prev-page').disabled=wardrobePage===0;$('next-page').disabled=wardrobePage===pages-1;
  $('prev-page').onclick=()=>{wardrobePage--;wardrobeList();};$('next-page').onclick=()=>{wardrobePage++;wardrobeList();};
}
function showDetails(){
  if(kind!=='character'){showSourceAppearance();return;}
  $('inspector').innerHTML=heading('Surface & details','Adjust appearance and add static fantasy accessories.')+
   `<label>Hair<select id="hair"><option value="none">No hair</option>${avatarOptions('hair').map(a=>`<option value="${a.id}">${esc(a.label)}</option>`).join('')}</select></label><label class="check"><input id="skin-texture" type="checkbox" ${state.skinTexture!==false?'checked':''}>Detailed skin texture</label><label>Skin tint<input id="skin-color" type="color" value="${state.skin}"></label><label>Iris color<input id="iris-color" type="color" value="${state.iris}"></label><h2>Attachments</h2>${[['horns','Horns'],['ears','Fantasy ears'],['earrings','Ear rings'],['tail','Tail'],['wings','Wings']].map(([id,label])=>`<label class="attachment" for="attachment-${id}">${label}<input id="attachment-${id}" type="checkbox" data-attachment="${id}" ${state.attachments.includes(id)?'checked':''}></label>`).join('')}<p class="hint">Hair, lashes, and authored outfits follow the character's source vertex bindings. Fantasy attachments use approximate placement. Both are static, without animation or simulation.</p><details><summary>Additional customization roadmap</summary><p class="feature-note">UV-aware tattoos, wrinkle maps, hair grooming, prosthetics, local sculpting, and skeletal correctives need additional assets or workers.</p></details>`;
  $('hair').value=state.hair||'none';$('hair').onchange=e=>{remember();state.hair=e.target.value;scheduleUpdate();};
  $('skin-texture').onchange=e=>{remember();state.skinTexture=e.target.checked;scheduleUpdate();};
  $('skin-color').onchange=e=>{remember();state.skin=e.target.value;scheduleUpdate();};$('iris-color').onchange=e=>{remember();state.iris=e.target.value;scheduleUpdate();};
  for(const c of document.querySelectorAll('[data-attachment]'))c.onchange=()=>{remember();state.attachments=c.checked?[...state.attachments,c.dataset.attachment]:state.attachments.filter(x=>x!==c.dataset.attachment);renderCharacter(kind!=='character');};
}
function showSourceAppearance(){
  $('inspector').innerHTML=heading('Original appearance','Imported models keep their own materials, textures, hair, and clothing.')+'<div class="notice">The supported base wardrobe and surface controls do not map to this model. Use Body to inspect its existing shape targets.</div><button id="source-body" class="wide">Inspect source shape targets</button><button id="return-base" class="wide">Load supported character base</button>';
  $('source-body').onclick=()=>{tab='body';renderPanel();};$('return-base').onclick=loadSupportedBase;
}
function showWorld(){
  $('inspector').innerHTML=heading('World builder','Seeded fractal landscapes generated directly in your browser.')+
  `<label>Seed<input id="terrain-seed" type="number" min="0" max="2147483647" value="${terrain.seed}"></label><label>Width · meters<input id="terrain-size" type="number" min="10" max="2000" value="${terrain.size}"></label><label>Height · meters<input id="terrain-height" type="number" min="1" max="500" value="${terrain.height}"></label><label>Detail<select id="terrain-resolution"><option value="5">Preview · 2,048 triangles</option><option value="6">Balanced · 8,192 triangles</option><option value="7">Detailed · 32,768 triangles</option><option value="8">High · 131,072 triangles</option></select></label><button id="generate-terrain" class="wide primary">Generate terrain</button><p class="hint">The same seed and settings reproduce the same landscape. Export includes real mesh geometry and biome colors.</p>`;
  $('terrain-resolution').value=terrain.resolution;$('generate-terrain').onclick=()=>{clearTimeout(updateTimer);terrain={seed:Math.max(0,Math.min(2147483647,Number($('terrain-seed').value)||0)),size:Math.max(10,Math.min(2000,Number($('terrain-size').value)||200)),height:Math.max(1,Math.min(500,Number($('terrain-height').value)||35)),resolution:Number($('terrain-resolution').value)};view.replace(terrainGeometry(terrain),true);kind='terrain';activeModel=null;enableModelActions();$('view-label').textContent='Landscape';$('mode-badge').textContent='Local procedural mesh';status('Terrain generated. Ready to save or export.');};
}
function showCreate(){
  $('inspector').innerHTML=heading('Create in 3D','Describe a character or object, or supply a reference image.')+
  `<label>Input<select id="creation-mode"><option value="text">Text to 3D</option><option value="prompt">Guided prompt to 3D</option><option value="image">Image to 3D</option><option value="import">Import GLB</option></select></label><div id="creation-fields"></div><div class="notice">AI creation requires a connected worker and provider API key. Generated assets are checked before preview; detailed morph compatibility is evaluated separately.</div><button id="connect-worker" class="wide">Connect worker</button><div id="creation-jobs"></div>`;
  $('creation-mode').onchange=creationFields;$('connect-worker').onclick=()=>{$('backend-url').value=backend||location.origin;$('connection-dialog').showModal();};creationFields();renderJobs();
}
function creationFields(){
  const mode=$('creation-mode').value;
  if(mode==='import'){
    $('creation-fields').innerHTML='<label>GLB model<input id="glb-input" type="file" accept=".glb,model/gltf-binary"></label><p class="hint">Up to 150 MiB. Original materials, skins, shape targets, and animation clips are retained. Save local imports with Export GLB.</p>';
    $('glb-input').onchange=async e=>{const f=e.target.files[0];if(!f)return;if(f.size>MAX_GLB_BYTES)return status('Model exceeds 150 MiB');if(modelLoading)return status('Wait for the current model to finish loading.');modelLoading=true;clearTimeout(updateTimer);try{status('Reading model…');await view.import(await f.arrayBuffer());kind='import';activeModel=null;morphSearch='';enableModelActions();$('view-label').textContent=f.name;$('mode-badge').textContent='Original imported model';status('Model loaded. Source shape targets are available in Body; use GLB export to save.');}catch(err){status(err.message);}finally{modelLoading=false;}};return;
  }
  let fields='';
  if(mode==='prompt')fields=`<label>Subject<input id="prompt-subject" value="Adult fictional explorer"></label><label>Visual style<select id="prompt-style"><option>Realistic</option><option>Stylized</option><option>Low-poly</option><option>Fantasy</option></select></label><label>Clothing & materials<input id="prompt-material" value="Layered travel jacket, woven fabric, leather boots"></label><button id="compose" class="wide">Compose editable prompt</button>`;
  fields+=mode==='image'?'<label>Reference image<input id="image-input" type="file" accept="image/png,image/jpeg,image/webp"></label><div id="reference-preview"></div><p class="hint">Your reference is sent to the selected provider only when you press Generate.</p>':'<label>Prompt<textarea id="prompt-text" maxlength="12000" placeholder="Describe the subject, shape, materials, and style. Avoid lighting or backgrounds that obscure the object."></textarea></label>';
  fields+=`<label>Provider<select id="provider">${mode==='image'?'<option value="hi3d">Hi3D · image upload</option>':'<option value="tripo">Tripo · text generation</option><option value="meshy">Meshy · preview + refine</option>'}</select></label><p class="hint">Generation may consume credits on your provider account.</p><button id="generate-ai" class="wide primary">Generate 3D</button>`;
  $('creation-fields').innerHTML=fields;
  if(mode==='prompt')$('compose').onclick=()=>{$('prompt-text').value=`${$('prompt-subject').value}. ${$('prompt-style').value} 3D asset. ${$('prompt-material').value}. Clean geometry, full subject visible, neutral pose.`;};
  if(mode==='image')$('image-input').onchange=e=>{const file=e.target.files[0];if(!file)return;if(file.size>12*1024*1024)return status('Reference exceeds 12 MiB');if(reference)URL.revokeObjectURL(reference);reference=URL.createObjectURL(file);$('reference-preview').innerHTML=`<img class="image-preview" alt="Selected reference" src="${reference}">`;uploadedImage=null;};
  $('generate-ai').onclick=async()=>{
    const b=$('generate-ai');b.disabled=true;
    try{
      if(!capabilities?.backend)throw Error('Connect the Python worker before AI generation. Local editing remains available.');
      const request={kind:mode==='image'?'image':'text',provider:$('provider').value,prompt:mode==='image'?'':$('prompt-text').value};
      if(mode==='image'){const file=$('image-input').files[0];if(!file)throw Error('Choose a reference image');const form=new FormData();form.append('file',file);const result=await api('/images',{method:'POST',body:form});request.image_id=result.image_id;}
      const result=await api('/generate',{method:'POST',body:JSON.stringify(request)});jobs.unshift(result);renderJobs();status('Generation submitted to your provider.');pollJob(result.id);
    }catch(e){status(e.message);}finally{b.disabled=false;}
  };
}
function renderJobs(){
  if(!$('creation-jobs'))return;
  $('creation-jobs').innerHTML=jobs.map(j=>`<div class="job-card"><strong>${esc(j.provider)} · ${esc(j.status)}</strong><div>${esc(j.error||j.stage)}${j.provider_progress!=null?' · '+esc(j.provider_progress)+'%':''}</div>${j.asset_url?`<button class="wide" data-open-job="${esc(j.id)}">Open generated asset</button>`:''}</div>`).join('');
  for(const button of document.querySelectorAll('[data-open-job]'))button.onclick=async()=>{if(modelLoading)return status('Wait for the current model to finish loading.');modelLoading=true;clearTimeout(updateTimer);try{const j=jobs.find(x=>x.id===button.dataset.openJob);await view.import(await downloadModel(j.asset_url));kind='import';activeModel=null;morphSearch='';enableModelActions();$('mode-badge').textContent='Generated · compatibility unverified';$('view-label').textContent='Generated asset';status('Verified provider model opened. Detailed morph mapping is not automatic.');}catch(e){status(e.message);}finally{modelLoading=false;}};
}
async function pollJob(id){try{const job=await api('/jobs/'+id);jobs=jobs.map(j=>j.id===id?job:j);renderJobs();if(['queued','running'].includes(job.status))setTimeout(()=>pollJob(id),2500);else status(job.status==='succeeded'?'Generation completed. Open the verified asset.':job.error||'Generation stopped.');}catch(e){status(e.message);}}
async function api(path,options={}){
  const headers={...(token?{'Authorization':'Bearer '+token}:{}),...(!(options.body instanceof FormData)?{'Content-Type':'application/json'}:{}),...(options.headers||{})};
  const response=await fetch(backend+'/api/studio'+path,{...options,headers,signal:AbortSignal.timeout(30000)});
  if(!response.ok){let detail;try{detail=(await response.json()).detail;}catch{}throw Error(typeof detail==='string'?detail:`Worker request failed (${response.status})`);}return response.json();
}
async function connect(){
  try{capabilities=await api('/capabilities');status('Worker connected. Provider readiness is shown in System.');if(tab==='status')showStatus();}
  catch{capabilities=null;}finally{updateConnectionStatus();}
}
function localProjects(){try{const entries=JSON.parse(localStorage.getItem('forma-projects')||'[]');return Array.isArray(entries)?entries.filter(p=>p&&typeof p.id==='string'&&typeof p.created==='string'):[];}catch{return [];}}
function projectData(){
  const project={id:crypto.randomUUID(),schema_version:1,name:$('project-name').value.trim()||'Untitled',kind,created:new Date().toISOString()};
  if(kind==='model'&&activeModel)return {...project,schema_version:3,source_id:activeModel.id,source_sha256:activeModel.sha256,morphs:view.morphValues(),sculpt_ops:view.getSculptOperations()};
  return {...project,character:structuredClone(state),terrain};
}
function validateProject(p){
  if(!p||typeof p!=='object'||typeof p.name!=='string'||p.name.length>120)throw Error('Invalid project metadata');
  if(p.kind==='model'){
    if(![2,3].includes(p.schema_version)||!validModelId(p.source_id)||!/^[0-9a-f]{64}$/i.test(p.source_sha256||''))throw Error('Invalid model project source');
    if(!p.morphs||Array.isArray(p.morphs)||typeof p.morphs!=='object'||Object.keys(p.morphs).length>10000||Object.entries(p.morphs).some(([id,value])=>!/^m\d+:\d+$/.test(id)||!Number.isFinite(value)||Math.abs(value)>10))throw Error('Invalid source morph settings');
    if(p.schema_version===3&&(!Array.isArray(p.sculpt_ops)||p.sculpt_ops.length>100||p.sculpt_ops.some(op=>!op||!Number.isInteger(op.meshIndex)||op.meshIndex<0||op.meshIndex>10000||![op.center,op.normal].every(v=>Array.isArray(v)&&v.length===3&&v.every(n=>Number.isFinite(n)&&Math.abs(n)<=1e6))||Math.hypot(...op.normal)<=0||!Number.isFinite(op.radius)||op.radius<=0||op.radius>1e6||!Number.isFinite(op.amount)||Math.abs(op.amount)>1e6||typeof op.label!=='string'||op.label.length>64)))throw Error('Invalid saved sculpt operations');
    return p;
  }
  if(!['character','terrain'].includes(p.kind))throw Error('Save local or generated imports with Export GLB. Library models support editable project files.');
  if(p.schema_version!==1||!p.character||!['female','male'].includes(p.character.base))throw Error('Unsupported project schema');
  const c=p.character,ids=new Set(data.controls.map(x=>x.id));if(!c.controls||Object.entries(c.controls).some(([k,v])=>!ids.has(k)||!Number.isFinite(v)||Math.abs(v)>(c.extreme?150:100)))throw Error('Invalid morph settings');
  for(const value of [c.skin,c.cloth,c.iris])if(!/^#[0-9a-fA-F]{6}$/.test(value))throw Error('Invalid material color');
  if((!catalog.some(x=>x.id===c.outfit)&&avatarAsset(c.outfit)?.kind!=='garment')||!Array.isArray(c.attachments)||c.attachments.some(x=>!['horns','ears','earrings','tail','wings'].includes(x)))throw Error('Unsupported wardrobe or attachment');
  if(c.hair&&c.hair!=='none'&&avatarAsset(c.hair)?.kind!=='hair')throw Error('Unsupported hair asset');
  if(c.shoes&&c.shoes!=='none'&&avatarAsset(c.shoes)?.kind!=='shoes')throw Error('Unsupported footwear');
  if(c.skinTexture!==undefined&&typeof c.skinTexture!=='boolean')throw Error('Invalid skin texture setting');
  if(p.kind==='terrain'&&(!p.terrain||!Number.isInteger(p.terrain.seed)||!Number.isFinite(p.terrain.size)||p.terrain.size<10||p.terrain.size>2000||!Number.isFinite(p.terrain.height)||p.terrain.height<1||p.terrain.height>500||![5,6,7,8].includes(p.terrain.resolution)))throw Error('Invalid terrain settings');
  return p;
}
async function openProject(p){
  if(p?.kind!=='model')await ensureBaseAssets();validateProject(p);
  if(p.kind==='model'){await loadLibraryModel(p.source_id,p);await renderPanel();status('Project restored from its verified source model.');return;}
  clearTimeout(updateTimer);remember();state=structuredClone(p.character);terrain=p.terrain||terrain;$('project-name').value=p.name||'Untitled';
  if(p.kind==='terrain'){view.replace(terrainGeometry(terrain),true);kind='terrain';activeModel=null;enableModelActions();$('view-label').textContent='Landscape';$('mode-badge').textContent='Local procedural mesh';}else renderCharacter(true);
  await renderPanel();status('Project restored.');
}
function showProjects(){
  const projects=localProjects();$('inspector').innerHTML=heading('Projects','Saved in this browser. Download a project file to keep a portable backup.')+
  '<button id="download-project" class="wide">Download project JSON</button><label>Open project file<input id="project-file" type="file" accept=".json,application/json"></label><div id="project-list"></div><p class="hint">Library projects store the source ID, integrity hash, and editable morph values. Reopening needs that model in the bundled library or on the connected worker. Local imports are saved with GLB export.</p>';
  $('project-list').innerHTML=projects.length?projects.map(p=>`<div class="project-card"><strong>${esc(p.name)}</strong><p>${esc(p.kind)} · ${esc(p.created.slice(0,10))}</p><button data-project="${esc(p.id)}">Open project</button></div>`).join(''):'<div class="empty">No saved projects. Use Save project above.</div>';
  for(const b of document.querySelectorAll('[data-project]'))b.onclick=async()=>{try{await openProject(projects.find(p=>p.id===b.dataset.project));}catch(e){status(e.message);}};
  $('download-project').disabled=!hasModel();
  $('download-project').onclick=async()=>{try{if(['character','terrain'].includes(kind))await ensureBaseAssets();const p=validateProject(projectData());download(new Blob([JSON.stringify(p,null,2)],{type:'application/json'}),'forma-project.json');status('Editable project downloaded.');}catch(e){status(e.message);}};
  $('project-file').onchange=async e=>{try{const f=e.target.files[0];if(!f)return;if(f.size>1024*1024)throw Error('Project exceeds 1 MiB');await openProject(JSON.parse(await f.text()));}catch(e){status('Unable to open project: '+e.message);}};
}
function showStatus(){
  const runtime=capabilities?.runtime;
  $('inspector').innerHTML=heading('System & capabilities','Implemented features and available worker services.')+
  `<div class="capability">Body controls<span>${data?data.controls.length+' loaded authored and local targets':'Loaded when you open the supported base'}</span></div><div class="capability">Wardrobe<span>${catalog?.length||360} executable surface recipes · no cloth simulation</span></div><div class="capability">Browser editing & GLB export<span>Runs locally in your browser</span></div><div class="capability">Provider generation<span>${capabilities?.backend?'Worker connected':'Connect a Python worker'}</span></div>${runtime?.providers?.map(p=>`<div class="capability">${esc(p.name.replace('provider:',''))}<span>${p.available?'Credentials configured; live request not yet verified':'API key not configured'}</span></div>`).join('')||''}<div class="capability">Blender rendering<span>${runtime?.blender?.available?'Worker installed; browser render job controls pending':'Requires a Blender worker; browser snapshots remain available'}</span></div><div class="notice">Imported models preserve their source materials, rigs, shape targets, and animation clips. The supported base is static. New rigging, animation authoring, sculpt brushes, and production garment fitting remain incomplete.</div><button class="wide" id="system-connect">Connect worker</button><h2>Asset credits</h2><p class="hint">MakeHuman hm08 body and targets: CC0. Authored hair, clothing, lashes, skin textures and shoes from the older MakeHuman asset collection: AGPL-3.0-or-later, with source and license bundled. Three.js: MIT.</p><a href="/studio/data/provenance.json" target="_blank" rel="noopener">Body provenance</a><p><a href="/studio/data/quality-assets/CREDITS.md">Finish asset credits</a> · <a href="/studio/data/quality-assets/source-assets.zip">Original asset source</a></p>`;
  $('system-connect').onclick=()=>{$('backend-url').value=backend||location.origin;$('connection-dialog').showModal();};
}
async function renderPanel(){
  if(tab!=='body')stopSculptPicking();
  document.querySelectorAll('[data-tab]').forEach(button=>button.classList.toggle('selected',button.dataset.tab===tab));
  try{
    if(['body','wardrobe','details'].includes(tab)&&kind==='empty'){
      $('inspector').innerHTML=heading('Character tools','Open a library model or load the supported character base.')+'<button id="choose-model" class="wide primary">Browse your models</button><button id="return-base" class="wide">Load supported character base</button>';
      $('choose-model').onclick=()=>{tab='models';renderPanel();};$('return-base').onclick=loadSupportedBase;return;
    }
    ({models:showModels,body:showBody,wardrobe:showWardrobe,details:showDetails,world:showWorld,create:showCreate,projects:showProjects,status:showStatus}[tab])();
  }catch(error){status(error.message);}
}
for(const button of document.querySelectorAll('[data-tab]'))button.onclick=()=>{tab=button.dataset.tab;renderPanel();};
$('frame').onclick=()=>view.frame();$('portrait').onclick=()=>view.portrait();$('front').onclick=()=>view.angle([0,0,1]);$('side').onclick=()=>view.angle([1,0,0]);$('back').onclick=()=>view.angle([0,0,-1]);
$('wire').onclick=e=>{const v=e.target.getAttribute('aria-pressed')!=='true';e.target.setAttribute('aria-pressed',v);view.setWire(v);};
$('snapshot').onclick=()=>{downloadDataURL(view.snapshot(),'forma-preview.png');status('Browser preview image downloaded. This is not a Cycles render.');};
$('export').onclick=async()=>{const b=$('export');b.disabled=true;try{status('Building GLB export…');const result=await view.export();download(new Blob([result],{type:'model/gltf-binary'}),'forma-'+kind+'.glb');status('GLB exported with the visible model, garments, and attachments.');}catch(e){status('Export failed: '+e.message);}finally{b.disabled=false;}};
$('save').onclick=async()=>{try{if(['character','terrain'].includes(kind))await ensureBaseAssets();const p=validateProject(projectData()),list=localProjects();localStorage.setItem('forma-projects',JSON.stringify([p,...list].slice(0,50)));let workerError='';if(capabilities?.backend&&kind==='character'){try{await api('/projects',{method:'POST',body:JSON.stringify({name:p.name,character:state})});}catch(error){workerError=` Worker copy failed: ${error.message}`;}}if(tab==='projects')showProjects();status('Editable project saved in this browser.'+workerError);}catch(e){status(e.message);}};
$('connection-dialog').addEventListener('close',async()=>{if($('connection-dialog').returnValue!=='connect')return;const value=$('backend-url').value.trim();try{const url=new URL(value);if(url.protocol!=='https:'&&!['localhost','127.0.0.1'].includes(url.hostname))throw Error('Use HTTPS for remote workers');backend=url.origin;token=$('backend-token').value;modelLibrary=null;librarySource=null;await connect();if(!capabilities)throw Error('Worker unavailable or unauthorized. Check URL, token, and allowed origin.');await refreshModels();renderPanel();}catch(e){status(e.message);}});

try{
  enableModelActions();renderPanel();await connect();await refreshModels();status(librarySource==='bundled'?'Bundled library ready in your browser. Choose a model to download and open.':'Choose a source model to begin. No model downloads until selected.');
}catch(e){status(e.message);$('inspector').innerHTML=heading('Unable to start',esc(e.message))+'<button class="wide" onclick="location.reload()">Retry loading</button>';}
