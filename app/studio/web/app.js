import {StudioView,characterGeometry,terrainGeometry} from './engine.js';
import {loadAvatarAssets,avatarOptions,avatarAsset} from './avatar-assets.js';

const $=id=>document.getElementById(id), esc=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const defaults=()=>({base:'female',controls:{},extreme:false,skin:'#b77f60',cloth:'#253d65',iris:'#527c83',outfit:'female_casualsuit01',hair:'long01',shoes:'shoes01',skinTexture:true,attachments:[]});
let state=defaults(), data,catalog,tab='body',kind='character',group='curves',search='',category='fashion',wardrobePage=0,mature=false,linked=true;
let backend='',token='',capabilities=null,reference=null,uploadedImage=null,updateTimer,history=[],future=[],jobs=[],terrain={seed:7,size:200,height:35,resolution:6};
const groups={curves:'Breasts & glutes',breast:'Breasts',armslegs:'Arms, legs, hands & feet',head:'Head',eyes:'Eyes',nose:'Nose',mouth:'Mouth',ears:'Ears',cheek:'Cheeks',chin:'Chin & jaw',forehead:'Forehead',eyebrows:'Brows',neck:'Neck',torso:'Torso',hip:'Hips',pelvis:'Pelvis',stomach:'Abdomen',buttocks:'Glutes'};
const view=new StudioView($('canvas'),text=>$('mesh-stats').textContent=text);
function status(text){$('status').textContent=text;}
function remember(){history.push(structuredClone(state));if(history.length>80)history.shift();future=[];if($('undo'))$('undo').disabled=false;}
function renderCharacter(reframe=false){view.replace(characterGeometry(data,state,catalog),reframe);kind='character';$('view-label').textContent='Character';$('mode-badge').textContent=state.extreme?'Extended morph range':avatarAsset(state.outfit)?'Textured character':'Surface garment';}
function scheduleUpdate(){clearTimeout(updateTimer);updateTimer=setTimeout(()=>{try{renderCharacter();}catch(e){status(e.message);}},60);}
function setValue(id,value){state.controls[id]=Math.max(state.extreme?-150:-100,Math.min(state.extreme?150:100,Number(value)||0));if(linked){const opposite=id.startsWith('l-')?'r-'+id.slice(2):id.startsWith('r-')?'l-'+id.slice(2):null;if(opposite&&data.controls.some(c=>c.id===opposite)){state.controls[opposite]=state.controls[id];for(const prefix of ['slider-','number-']){const input=$(prefix+opposite);if(input)input.value=state.controls[opposite];}}}scheduleUpdate();}
function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);}
function downloadDataURL(url,name){const a=document.createElement('a');a.href=url;a.download=name;a.click();}
function heading(title,subtitle){return `<h1>${title}</h1><p>${subtitle}</p>`;}
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
  if(kind!=='character'){ $('inspector').innerHTML=heading('Body studio','Fine controls require the supported MakeHuman base.')+'<div class="notice">This asset has no verified authored target mapping. Its appearance is preserved; body sliders are unavailable.</div><button class="wide primary" id="return-base">Load supported base</button>'; $('return-base').onclick=()=>{renderCharacter(true);showBody();};return;}
  $('inspector').innerHTML=heading('Body studio',`Dedicated breast and glute sculpting, plus ${data.controls.length} shape controls across the body.`)+
    `<div class="focus-regions"><button id="focus-breasts">Breasts</button><button id="focus-glutes">Glutes</button><button id="focus-both">Both</button></div><label>Adult base<select id="base"><option value="female">Feminine adult base</option><option value="male">Masculine adult base</option></select></label><div class="inline-tools"><button id="undo" ${history.length?'':'disabled'}>Undo</button><button id="redo" ${future.length?'':'disabled'}>Redo</button><button id="reset-group">Reset region</button><button id="reset-all">Reset all</button></div><label class="check"><input type="checkbox" id="link" ${linked?'checked':''}>Link left and right</label><label class="check"><input type="checkbox" id="extreme" ${state.extreme?'checked':''}>Extended range · experimental</label><p class="hint">Standard targets: −100 to +100%. Extended targets: ±150%. Extreme combinations need mesh and garment inspection.</p><input class="search" id="control-search" type="search" placeholder="Search all body controls" aria-label="Search body controls" value="${esc(search)}"><label>Region<select id="region">${Object.entries(groups).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label><div class="section-line"><h2>Shape controls</h2><span id="control-count"></span></div><div id="control-list"></div><p class="hint">CC0 authored targets + localized sculpt deltas · static character. Bone retargeting and animation correctives are not included.</p>`;
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
  $('inspector').innerHTML=heading('Surface & details','Adjust appearance and add static fantasy accessories.')+
   `<label>Hair<select id="hair"><option value="none">No hair</option>${avatarOptions('hair').map(a=>`<option value="${a.id}">${esc(a.label)}</option>`).join('')}</select></label><label class="check"><input id="skin-texture" type="checkbox" ${state.skinTexture!==false?'checked':''}>Detailed skin texture</label><label>Skin tint<input id="skin-color" type="color" value="${state.skin}"></label><label>Iris color<input id="iris-color" type="color" value="${state.iris}"></label><h2>Attachments</h2>${[['horns','Horns'],['ears','Fantasy ears'],['earrings','Ear rings'],['tail','Tail'],['wings','Wings']].map(([id,label])=>`<label class="attachment" for="attachment-${id}">${label}<input id="attachment-${id}" type="checkbox" data-attachment="${id}" ${state.attachments.includes(id)?'checked':''}></label>`).join('')}<p class="hint">Hair, lashes, and authored outfits follow the character's source vertex bindings. Fantasy attachments use approximate placement. Both are static, without animation or simulation.</p><details><summary>Additional customization roadmap</summary><p class="feature-note">UV-aware tattoos, wrinkle maps, hair grooming, prosthetics, local sculpting, and skeletal correctives need additional assets or workers.</p></details>`;
  $('hair').value=state.hair||'none';$('hair').onchange=e=>{remember();state.hair=e.target.value;scheduleUpdate();};
  $('skin-texture').onchange=e=>{remember();state.skinTexture=e.target.checked;scheduleUpdate();};
  $('skin-color').onchange=e=>{remember();state.skin=e.target.value;scheduleUpdate();};$('iris-color').onchange=e=>{remember();state.iris=e.target.value;scheduleUpdate();};
  for(const c of document.querySelectorAll('[data-attachment]'))c.onchange=()=>{remember();state.attachments=c.checked?[...state.attachments,c.dataset.attachment]:state.attachments.filter(x=>x!==c.dataset.attachment);renderCharacter(kind!=='character');};
}
function showWorld(){
  $('inspector').innerHTML=heading('World builder','Seeded fractal landscapes generated directly in your browser.')+
  `<label>Seed<input id="terrain-seed" type="number" min="0" max="2147483647" value="${terrain.seed}"></label><label>Width · meters<input id="terrain-size" type="number" min="10" max="2000" value="${terrain.size}"></label><label>Height · meters<input id="terrain-height" type="number" min="1" max="500" value="${terrain.height}"></label><label>Detail<select id="terrain-resolution"><option value="5">Preview · 2,048 triangles</option><option value="6">Balanced · 8,192 triangles</option><option value="7">Detailed · 32,768 triangles</option><option value="8">High · 131,072 triangles</option></select></label><button id="generate-terrain" class="wide primary">Generate terrain</button><p class="hint">The same seed and settings reproduce the same landscape. Export includes real mesh geometry and biome colors.</p>`;
  $('terrain-resolution').value=terrain.resolution;$('generate-terrain').onclick=()=>{terrain={seed:Math.max(0,Math.min(2147483647,Number($('terrain-seed').value)||0)),size:Math.max(10,Math.min(2000,Number($('terrain-size').value)||200)),height:Math.max(1,Math.min(500,Number($('terrain-height').value)||35)),resolution:Number($('terrain-resolution').value)};view.replace(terrainGeometry(terrain),true);kind='terrain';$('view-label').textContent='Landscape';$('mode-badge').textContent='Local procedural mesh';status('Terrain generated. Ready to save or export.');};
}
function showCreate(){
  $('inspector').innerHTML=heading('Create in 3D','Describe a character or object, or supply a reference image.')+
  `<label>Input<select id="creation-mode"><option value="text">Text to 3D</option><option value="prompt">Guided prompt to 3D</option><option value="image">Image to 3D</option><option value="import">Import GLB</option></select></label><div id="creation-fields"></div><div class="notice">AI creation requires a connected worker and provider API key. Generated assets are checked before preview; detailed morph compatibility is evaluated separately.</div><button id="connect-worker" class="wide">Connect worker</button><div id="creation-jobs"></div>`;
  $('creation-mode').onchange=creationFields;$('connect-worker').onclick=()=>{$('backend-url').value=backend||location.origin;$('connection-dialog').showModal();};creationFields();renderJobs();
}
function creationFields(){
  const mode=$('creation-mode').value;
  if(mode==='import'){
    $('creation-fields').innerHTML='<label>GLB model<input id="glb-input" type="file" accept=".glb,model/gltf-binary"></label><p class="hint">Up to 60 MiB. Imported meshes keep their appearance; authored body controls are available only on the supported base.</p>';
    $('glb-input').onchange=async e=>{const f=e.target.files[0];if(!f)return;if(f.size>60*1024*1024)return status('Model exceeds 60 MiB');try{status('Reading model…');await view.import(await f.arrayBuffer());kind='import';$('view-label').textContent=f.name;$('mode-badge').textContent='Imported · compatibility unverified';status('Model loaded. Orbit, inspect, and export.');}catch(err){status(err.message);}};return;
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
  for(const button of document.querySelectorAll('[data-open-job]'))button.onclick=async()=>{try{const j=jobs.find(x=>x.id===button.dataset.openJob),r=await fetch(backend+j.asset_url,{headers:token?{'Authorization':'Bearer '+token}:{}});if(!r.ok)throw Error('Download failed');await view.import(await r.arrayBuffer());kind='import';$('mode-badge').textContent='Generated · compatibility unverified';$('view-label').textContent='Generated asset';status('Verified provider model opened. Detailed morph mapping is not automatic.');}catch(e){status(e.message);}};
}
async function pollJob(id){try{const job=await api('/jobs/'+id);jobs=jobs.map(j=>j.id===id?job:j);renderJobs();if(['queued','running'].includes(job.status))setTimeout(()=>pollJob(id),2500);else status(job.status==='succeeded'?'Generation completed. Open the verified asset.':job.error||'Generation stopped.');}catch(e){status(e.message);}}
async function api(path,options={}){
  const headers={...(token?{'Authorization':'Bearer '+token}:{}),...(!(options.body instanceof FormData)?{'Content-Type':'application/json'}:{}),...(options.headers||{})};
  const response=await fetch(backend+'/api/studio'+path,{...options,headers,signal:AbortSignal.timeout(30000)});
  if(!response.ok){let detail;try{detail=(await response.json()).detail;}catch{}throw Error(typeof detail==='string'?detail:`Worker request failed (${response.status})`);}return response.json();
}
async function connect(){
  try{capabilities=await api('/capabilities');$('backend-status').textContent='Worker connected';status('Worker connected. Provider readiness is shown in System.');if(tab==='status')showStatus();}
  catch{capabilities=null;$('backend-status').textContent='Browser mode · no worker';}
}
function localProjects(){try{return JSON.parse(localStorage.getItem('forma-projects')||'[]');}catch{return [];}}
function projectData(){return {id:crypto.randomUUID(),schema_version:1,name:$('project-name').value.trim()||'Untitled',character:structuredClone(state),kind,terrain,created:new Date().toISOString()};}
function validateProject(p){
  if(p.schema_version!==1||!p.character||!['female','male'].includes(p.character.base))throw Error('Unsupported project schema');
  const c=p.character,ids=new Set(data.controls.map(x=>x.id));if(!c.controls||Object.entries(c.controls).some(([k,v])=>!ids.has(k)||!Number.isFinite(v)||Math.abs(v)>(c.extreme?150:100)))throw Error('Invalid morph settings');
  for(const value of [c.skin,c.cloth,c.iris])if(!/^#[0-9a-fA-F]{6}$/.test(value))throw Error('Invalid material color');
  if((!catalog.some(x=>x.id===c.outfit)&&avatarAsset(c.outfit)?.kind!=='garment')||!Array.isArray(c.attachments)||c.attachments.some(x=>!['horns','ears','earrings','tail','wings'].includes(x)))throw Error('Unsupported wardrobe or attachment');
  if(c.hair&&c.hair!=='none'&&avatarAsset(c.hair)?.kind!=='hair')throw Error('Unsupported hair asset');
  if(c.shoes&&c.shoes!=='none'&&avatarAsset(c.shoes)?.kind!=='shoes')throw Error('Unsupported footwear');
  if(c.skinTexture!==undefined&&typeof c.skinTexture!=='boolean')throw Error('Invalid skin texture setting');
  if(!['character','terrain'].includes(p.kind))throw Error('Imported assets are exported as GLB rather than saved as procedural projects');
  if(p.kind==='terrain'&&(!p.terrain||!Number.isInteger(p.terrain.seed)||!Number.isFinite(p.terrain.size)||p.terrain.size<10||p.terrain.size>2000||!Number.isFinite(p.terrain.height)||p.terrain.height<1||p.terrain.height>500||![5,6,7,8].includes(p.terrain.resolution)))throw Error('Invalid terrain settings');
  return p;
}
function openProject(p){validateProject(p);remember();state=structuredClone(p.character);terrain=p.terrain||terrain;$('project-name').value=p.name||'Untitled';if(p.kind==='terrain'){view.replace(terrainGeometry(terrain),true);kind='terrain';$('view-label').textContent='Landscape';$('mode-badge').textContent='Local procedural mesh';}else renderCharacter(true);renderPanel();status('Project restored.');}
function showProjects(){
  const projects=localProjects();$('inspector').innerHTML=heading('Projects','Saved in this browser. Download a project file to keep a portable backup.')+
  '<button id="download-project" class="wide">Download project JSON</button><label>Open project file<input id="project-file" type="file" accept=".json,application/json"></label><div id="project-list"></div><p class="hint">Imported models are saved using GLB export. Procedural project files store editable settings, not a screenshot.</p>';
  $('project-list').innerHTML=projects.length?projects.map(p=>`<div class="project-card"><strong>${esc(p.name)}</strong><p>${esc(p.kind)} · ${esc(p.created.slice(0,10))}</p><button data-project="${esc(p.id)}">Open project</button></div>`).join(''):'<div class="empty">No saved projects. Use Save project above.</div>';
  for(const b of document.querySelectorAll('[data-project]'))b.onclick=()=>{try{openProject(projects.find(p=>p.id===b.dataset.project));}catch(e){status(e.message);}};
  $('download-project').onclick=()=>{try{const p=validateProject(projectData());download(new Blob([JSON.stringify(p,null,2)],{type:'application/json'}),'forma-project.json');status('Editable project downloaded.');}catch(e){status(e.message);}};
  $('project-file').onchange=async e=>{try{const f=e.target.files[0];if(!f)return;if(f.size>1024*1024)throw Error('Project exceeds 1 MiB');openProject(JSON.parse(await f.text()));}catch(e){status('Unable to open project: '+e.message);}};
}
function showStatus(){
  const runtime=capabilities?.runtime;
  $('inspector').innerHTML=heading('System & capabilities','Implemented features and available worker services.')+
  `<div class="capability">Body controls<span>${data.controls.filter(c=>c.source_kind==='authored').length} authored targets + ${data.controls.filter(c=>c.source_kind==='derived').length} localized controls</span></div><div class="capability">Wardrobe<span>${catalog.length} executable surface recipes · no cloth simulation</span></div><div class="capability">Browser editing & GLB export<span>Runs locally in your browser</span></div><div class="capability">Provider generation<span>${capabilities?'Worker connected':'Connect a Python worker'}</span></div>${runtime?.providers.map(p=>`<div class="capability">${esc(p.name.replace('provider:',''))}<span>${p.available?'Credentials configured; live request not yet verified':'API key not configured'}</span></div>`).join('')||''}<div class="capability">Blender rendering<span>${runtime?.blender.available?'Worker installed; browser render job controls pending':'Requires a Blender worker; browser snapshots remain available'}</span></div><div class="notice">This build uses a static human mesh with authored shape targets. Rigged animation, sculpt brushes, texture baking, production garment fitting, and prosthetics remain incomplete.</div><button class="wide" id="system-connect">Connect worker</button><h2>Asset credits</h2><p class="hint">MakeHuman hm08 body and targets: CC0. Authored hair, clothing, lashes, skin textures and shoes from the older MakeHuman asset collection: AGPL-3.0-or-later, with source and license bundled. Three.js: MIT.</p><a href="/studio/data/provenance.json" target="_blank" rel="noopener">Body provenance</a><p><a href="/studio/data/quality-assets/CREDITS.md">Finish asset credits</a> · <a href="/studio/data/quality-assets/source-assets.zip">Original asset source</a></p>`;
  $('system-connect').onclick=()=>{$('backend-url').value=backend||location.origin;$('connection-dialog').showModal();};
}
function renderPanel(){({body:showBody,wardrobe:showWardrobe,details:showDetails,world:showWorld,create:showCreate,projects:showProjects,status:showStatus}[tab])();}
for(const button of document.querySelectorAll('[data-tab]'))button.onclick=()=>{if(!data)return;tab=button.dataset.tab;document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('selected',b===button));renderPanel();};
$('frame').onclick=()=>view.frame();$('portrait').onclick=()=>view.portrait();$('front').onclick=()=>view.angle([0,0,1]);$('side').onclick=()=>view.angle([1,0,0]);$('back').onclick=()=>view.angle([0,0,-1]);
$('wire').onclick=e=>{const v=e.target.getAttribute('aria-pressed')!=='true';e.target.setAttribute('aria-pressed',v);view.setWire(v);};
$('snapshot').onclick=()=>{downloadDataURL(view.snapshot(),'forma-preview.png');status('Browser preview image downloaded. This is not a Cycles render.');};
$('export').onclick=async()=>{const b=$('export');b.disabled=true;try{status('Building GLB export…');const result=await view.export();download(new Blob([result],{type:'model/gltf-binary'}),'forma-'+kind+'.glb');status('GLB exported with the visible model, garments, and attachments.');}catch(e){status('Export failed: '+e.message);}finally{b.disabled=false;}};
$('save').onclick=async()=>{try{const p=validateProject(projectData()),list=localProjects();localStorage.setItem('forma-projects',JSON.stringify([p,...list].slice(0,50)));if(capabilities?.backend&&kind==='character'){const character=state;await api('/projects',{method:'POST',body:JSON.stringify({name:p.name,character})});}if(tab==='projects')showProjects();status('Editable project saved in this browser.');}catch(e){status(e.message);}};
$('connection-dialog').addEventListener('close',async()=>{if($('connection-dialog').returnValue!=='connect')return;const value=$('backend-url').value.trim();try{const url=new URL(value);if(url.protocol!=='https:'&&!['localhost','127.0.0.1'].includes(url.hostname))throw Error('Use HTTPS for remote workers');backend=url.origin;token=$('backend-token').value;await connect();if(!capabilities)throw Error('Worker unavailable or unauthorized. Check URL, token, and allowed origin.');renderPanel();}catch(e){status(e.message);}});

try{
  [data,catalog]=await Promise.all([fetch('/studio/data/human.json').then(r=>{if(!r.ok)throw Error('Character data could not be loaded');return r.json();}),fetch('/studio/data/wardrobe.json').then(r=>r.json()),loadAvatarAssets()]);
  renderCharacter(true);renderPanel();status(`${data.controls.length} body controls ready, including focused breast and glute sculpting.`);await connect();
}catch(e){status(e.message);$('inspector').innerHTML=heading('Unable to start',esc(e.message))+'<button class="wide" onclick="location.reload()">Retry loading</button>';}
