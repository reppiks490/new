import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

// Exercise the actual launcher, editor and privacy controller. The DOM below
// implements only their element/event boundary; it does not simulate layout.
class Element {
  constructor(){
    this.children=[];this.handlers=new Map();this.classes=new Set();this.dataset={};this.value='';this.textContent='';this.writes=[];
    this.classList={add:(...xs)=>xs.forEach(x=>this.classes.add(x)),remove:(...xs)=>xs.forEach(x=>this.classes.delete(x)),toggle:(x,on)=>on?this.classes.add(x):this.classes.delete(x),contains:x=>this.classes.has(x)};
  }
  set innerHTML(html){
    this.html=html;this.writes.push(html);this.children=[];
    for(const match of html.matchAll(/<([\w-]+)\b([^>]*)>/g)){
      const child=new Element();child.tagName=match[1];
      child.id=/\bid="([^"]*)"/.exec(match[2])?.[1];
      child.className=/\bclass="([^"]*)"/.exec(match[2])?.[1]||'';
      child.value=/\bvalue="([^"]*)"/.exec(match[2])?.[1]||'';
      child.parent=this;this.children.push(child);
    }
  }
  get innerHTML(){return this.html||'';}
  set className(value){this.classes=new Set(value.split(/\s+/).filter(Boolean));}
  get className(){return [...this.classes].join(' ');}
  querySelectorAll(selector){
    const matches=element=>selector.startsWith('#')?element.id===selector.slice(1):selector.startsWith('.')?element.classes.has(selector.slice(1)):element.tagName===selector;
    return this.children.flatMap(child=>[...(matches(child)?[child]:[]),...child.querySelectorAll(selector)]);
  }
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  addEventListener(name,fn){this.handlers.set(name,[...(this.handlers.get(name)||[]),fn]);}
  removeEventListener(name,fn){this.handlers.set(name,(this.handlers.get(name)||[]).filter(x=>x!==fn));}
  setAttribute(){}
  prepend(child){child.parent=this;this.children.unshift(child);}
  remove(){this.parent.children=this.parent.children.filter(x=>x!==this);}
}

const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const project={id:'a'.repeat(32),title:'PRIVATE_TITLE_SENTINEL',master_prompt:'PRIVATE_PROMPT_SENTINEL',revision:1,scenes:[],target_duration_seconds:600,delivery_fps:24,delivery_resolution:'480p'};
const job={id:'b'.repeat(32),status:'succeeded',stage:'Ready',progress:100,asset_url:`/api/video/assets/${'c'.repeat(32)}.mp4`};
let sequence=0;

async function harness(t,route=()=>undefined){
  const roots=new Map(['inspector','video-workspace','viewport','status','backend-url','backend-token','view-label','mode-badge','image-workspace'].map(id=>[id,new Element()]));
  const doc=new Element();doc.hidden=false;
  doc.getElementById=id=>roots.get(id)||[...roots.values()].map(root=>root.querySelector(`#${id}`)).find(Boolean)||null;
  doc.querySelector=()=>null;doc.querySelectorAll=()=>[];doc.createElement=()=>new Element();
  const restoreGlobals=[];let launcher;
  t.after(async()=>{await launcher?.closeCinematic();for(const restore of restoreGlobals)restore();});
  for(const [name,value] of Object.entries({document:doc,location:{origin:'https://worker.example'}})){
    const previous=Object.getOwnPropertyDescriptor(globalThis,name);
    Object.defineProperty(globalThis,name,{value,writable:true,configurable:true});
    restoreGlobals.push(()=>previous?Object.defineProperty(globalThis,name,previous):delete globalThis[name]);
  }
  const timers=new Map();let timerId=0;
  t.mock.method(globalThis,'setTimeout',(fn,ms)=>{const id=++timerId;timers.set(id,{fn,ms});return id;});
  t.mock.method(globalThis,'clearTimeout',id=>timers.delete(id));
  const requests=[];
  t.mock.method(globalThis,'fetch',async(url,options)=>{
    const path=new URL(url).pathname.replace('/api/video','');requests.push({path,options});
    const custom=route(path,options);
    if(custom!==undefined)return custom;
    const data=path==='/projects'?[project]:path==='/jobs'?[]:{};
    return {ok:true,json:async()=>data};
  });
  const created=[];const revoked=[];
  t.mock.method(URL,'createObjectURL',()=>{const url=`blob:test-${created.length}`;created.push(url);return url;});
  t.mock.method(URL,'revokeObjectURL',url=>revoked.push(url));
  const web=new URL('../app/studio/web/',import.meta.url);
  const quickModule='data:text/javascript,'+encodeURIComponent('export function exitVideoStudio(){} export function renderVideoStudio(){}');
  const source=fs.readFileSync(new URL('cinematic-launcher.js',web),'utf8')
    .replaceAll("'./cinematic-studio.js'",JSON.stringify(new URL('cinematic-studio.js',web).href))
    .replaceAll("'./privacy-mode.js'",JSON.stringify(new URL('privacy-mode.js',web).href))
    .replaceAll("import('./video-studio.js')",`import(${JSON.stringify(quickModule)})`);
  launcher=await import(`data:text/javascript,${encodeURIComponent(source)}#${++sequence}`);
  return {launcher,roots,requests,timers,created,revoked,doc,state:()=>roots.get('video-workspace').__cinematicState};
}

test('leaving during startup prevents late responses from reopening the cinematic editor',async t=>{
  const pending=deferred();
  const h=await harness(t,path=>path==='/capabilities'?pending.promise:undefined);
  const opening=h.launcher.openCinematic();await tick();
  await h.launcher.closeCinematic();
  h.roots.get('inspector').innerHTML='OTHER PANEL';h.roots.get('video-workspace').innerHTML='OTHER WORKSPACE';
  h.roots.get('status').textContent='Other panel ready';
  pending.resolve({ok:true,json:async()=>({})});await opening;
  assert.equal(h.roots.get('inspector').innerHTML,'OTHER PANEL');
  assert.equal(h.roots.get('video-workspace').innerHTML,'OTHER WORKSPACE');
  assert.equal(h.roots.get('status').textContent,'Other panel ready');
  assert.equal(h.requests.some(item=>item.path==='/projects'),false);
});

test('leaving during project loading cannot display an obsolete connection error',async t=>{
  const pending=deferred();const h=await harness(t,path=>path==='/projects'?pending.promise:undefined);
  const opening=h.launcher.openCinematic();await tick();
  await h.launcher.closeCinematic();h.roots.get('inspector').innerHTML='OTHER PANEL';
  pending.resolve({ok:true,json:async()=>[project]});await opening;
  assert.equal(h.roots.get('inspector').innerHTML,'OTHER PANEL');
  assert.equal(h.timers.size,0);
});

test('quick hide survives delayed project loading and restore shows the loaded project',async t=>{
  const pending=deferred();const h=await harness(t,path=>path==='/projects'?pending.promise:undefined);
  const opening=h.launcher.openCinematic();await tick();
  h.state().privacy.quickHide();pending.resolve({ok:true,json:async()=>[project]});await opening;
  for(const id of ['inspector','video-workspace']){
    assert.doesNotMatch(h.roots.get(id).writes.join(''),/PRIVATE_.*SENTINEL/);
    assert.doesNotMatch(h.roots.get(id).innerHTML,/PRIVATE_.*SENTINEL/);
    assert.match(h.roots.get(id).innerHTML,/hidden/);
  }
  h.state().privacy.restore();assert.match(h.roots.get('inspector').innerHTML,/PRIVATE_TITLE_SENTINEL/);
});

test('a delayed startup error cannot replace the neutral screen or expose error details',async t=>{
  const pending=deferred();const h=await harness(t,path=>path==='/capabilities'?pending.promise:undefined);
  const opening=h.launcher.openCinematic();await tick();h.state().privacy.quickHide();
  pending.reject(new Error('PRIVATE_ERROR_SENTINEL'));await opening;
  assert.match(h.roots.get('inspector').innerHTML,/hidden/);
  assert.doesNotMatch(h.roots.get('status').textContent,/PRIVATE_ERROR_SENTINEL/);
});

test('quick hide aborts an in-flight private preview and discards its late blob',async t=>{
  const pending=deferred();const h=await harness(t,path=>path==='/jobs'?{ok:true,json:async()=>[job]}:path.startsWith('/assets/')?pending.promise:undefined);
  const opening=h.launcher.openCinematic();await tick();
  const media=h.requests.find(item=>item.path.startsWith('/assets/'));assert.ok(media);
  h.state().privacy.quickHide();
  assert.equal(media.options.signal.aborted,true);
  pending.resolve({ok:true,blob:async()=>new Blob(['private'])});await opening;
  assert.deepEqual(h.created,[]);assert.equal(h.state().cinematicResultUrl,null);
});

test('cinematic previews obey blur preferences and hidden previews release their blob URLs',async t=>{
  const h=await harness(t,path=>path==='/jobs'?{ok:true,json:async()=>[job]}:path.startsWith('/assets/')?{ok:true,blob:async()=>new Blob(['private'])}:undefined);
  await h.launcher.openCinematic();
  const video=h.roots.get('video-workspace').querySelector('video');assert.ok(video);
  assert.equal(video.classList.contains('privacy-blurred'),true);
  h.roots.get('video-workspace').querySelector('#cinematic-reveal-preview').onclick();
  assert.equal(h.roots.get('video-workspace').querySelector('video').classList.contains('privacy-blurred'),false);
  h.roots.get('video-workspace').querySelector('#cinematic-reveal-preview').onclick();
  assert.equal(h.roots.get('video-workspace').querySelector('video').classList.contains('privacy-blurred'),true);
  h.state().privacy.setPreferences({blur_media:false});
  assert.equal(h.roots.get('video-workspace').querySelector('video').classList.contains('privacy-blurred'),false);
  h.state().privacy.quickHide();assert.deepEqual(h.revoked,h.created);
  assert.equal(h.state().cinematicResultUrl,null);
});

test('leaving before the lazy import completes cancels the pending navigation',async t=>{
  const h=await harness(t);h.roots.get('inspector').innerHTML='OTHER PANEL';
  const opening=h.launcher.openCinematic();await h.launcher.closeCinematic();await opening;
  assert.equal(h.state(),undefined);assert.equal(h.requests.length,0);
  assert.equal(h.roots.get('inspector').innerHTML,'OTHER PANEL');
});

test('an obsolete open cannot replace the current session or display its errors',async t=>{
  const pending=deferred();let calls=0;
  const h=await harness(t,path=>path==='/capabilities'&&++calls===1?pending.promise:undefined);
  const first=h.launcher.openCinematic();await tick();
  const oldState=h.state();await h.launcher.openCinematic();const current=h.state();
  assert.notEqual(current,oldState);
  pending.reject(new Error('OBSOLETE_PRIVATE_ERROR'));await first;
  assert.equal(h.state(),current);
  assert.match(h.roots.get('inspector').innerHTML,/PRIVATE_TITLE_SENTINEL/);
  assert.doesNotMatch(h.roots.get('status').textContent,/OBSOLETE_PRIVATE_ERROR/);
  assert.equal(h.requests.filter(item=>item.path==='/projects').length,1);
});

test('a poll completing after tab exit cannot restart polling or update another panel',async t=>{
  const pending=deferred();const running={...job,status:'running',asset_url:null};
  const h=await harness(t,path=>path==='/jobs'?{ok:true,json:async()=>[running]}:path===`/jobs/${job.id}`?pending.promise:undefined);
  const opening=h.launcher.openCinematic();await tick();
  const poll=h.requests.find(item=>item.path===`/jobs/${job.id}`);assert.ok(poll);
  await h.launcher.closeCinematic();assert.equal(poll.options.signal.aborted,true);
  h.roots.get('inspector').innerHTML='OTHER PANEL';h.roots.get('status').textContent='Other panel ready';
  pending.resolve({ok:true,json:async()=>running});await opening;
  assert.equal(h.timers.size,0);assert.equal(h.roots.get('inspector').innerHTML,'OTHER PANEL');
  assert.equal(h.roots.get('status').textContent,'Other panel ready');
});

test('restore reconnects to the active shot and rejects a late pre-hide poll',async t=>{
  const pending=deferred();let polls=0;const running={...job,status:'running',asset_url:null};
  const done={...running,status:'succeeded'};
  const h=await harness(t,path=>path==='/jobs'?{ok:true,json:async()=>[running]}:path===`/jobs/${job.id}`?(++polls===1?pending.promise:{ok:true,json:async()=>done}):undefined);
  const opening=h.launcher.openCinematic();await tick();
  h.state().privacy.quickHide();h.state().privacy.restore();await tick();
  assert.equal(polls,2);assert.equal(h.state().activeJob.status,'succeeded');
  pending.resolve({ok:true,json:async()=>running});await opening;
  assert.equal(h.state().activeJob.status,'succeeded');
  assert.equal([...h.timers.values()].some(item=>item.ms===1500),false);
});

test('restore reloads a private preview without accepting the obsolete pre-hide blob',async t=>{
  const pending=deferred();let downloads=0;
  const h=await harness(t,path=>path==='/jobs'?{ok:true,json:async()=>[job]}:path.startsWith('/assets/')?(++downloads===1?pending.promise:{ok:true,blob:async()=>new Blob(['current'])}):undefined);
  const opening=h.launcher.openCinematic();await tick();
  h.state().privacy.quickHide();h.state().privacy.restore();await tick();
  assert.equal(downloads,2);assert.equal(h.created.length,1);
  const url=h.state().cinematicResultUrl;
  pending.resolve({ok:true,blob:async()=>new Blob(['obsolete'])});await opening;
  assert.equal(h.state().cinematicResultUrl,url);assert.equal(h.created.length,1);
  assert.deepEqual(h.revoked,[]);
  const media=h.requests.filter(item=>item.path.startsWith('/assets/'));
  assert.ok(media.every(item=>item.options.cache==='no-store'));
});

test('worker status is rendered as text rather than executable HTML',async t=>{
  const h=await harness(t,path=>path==='/jobs'?{ok:true,json:async()=>[{...job,stage:'<img src=x onerror=alert(1)>',asset_url:null}]}:undefined);
  await h.launcher.openCinematic();
  const dock=h.roots.get('video-workspace').querySelector('.cinematic-result-dock');assert.ok(dock);
  assert.equal(dock.querySelector('img'),null);
  assert.match(dock.querySelector('strong').textContent,/<img src=x onerror=alert\(1\)>/);
});

test('submitting another shot supersedes the old poll and follows the new job',async t=>{
  const pending=deferred();const first={...job,status:'running',asset_url:null};
  const next={...first,id:'d'.repeat(32),status:'queued'};
  const editable={...project,scenes:[{scene_id:'e'.repeat(32),title:'Scene',shots:[{shot_id:'f'.repeat(32),title:'Shot',prompt:'Action',duration_seconds:5}]}]};
  const h=await harness(t,path=>path==='/projects'?{ok:true,json:async()=>[editable]}:path==='/jobs'?{ok:true,json:async()=>[first]}:path===`/jobs/${first.id}`?pending.promise:path===`/jobs/${next.id}`?{ok:true,json:async()=>next}:path.endsWith('/render')?{ok:true,json:async()=>({project:editable,plan:{},job:next})}:undefined);
  const opening=h.launcher.openCinematic();await tick();
  const oldPoll=h.requests.find(item=>item.path===`/jobs/${first.id}`);assert.ok(oldPoll);
  await h.roots.get('video-workspace').querySelector('#cinematic-render-shot').onclick();await tick();
  assert.ok(h.requests.some(item=>item.path===`/jobs/${next.id}`));
  assert.equal(oldPoll.options.signal.aborted,true);
  pending.resolve({ok:true,json:async()=>first});await opening;
  assert.equal(h.state().activeJob.id,next.id);
  assert.equal([...h.timers.values()].filter(item=>item.ms===1500).length,1);
});
