import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

import {
  neutralProjectLabel,
  summarizeProject,
  reconcileCinematicSelection,
  summarizeScene,
  visibleShotsForScene,
  buildShotInspectorView,
  buildPlanQualityView,
  buildNeutralCinematicView,
} from '../app/studio/web/cinematic-studio.js';

const makeShot=(index,duration=10)=>({
  shot_id:String(index).padStart(32,'0').slice(-32),
  ordinal:index,
  title:`Shot ${index}`,
  prompt:`Action ${index}`,
  duration_seconds:duration,
  reference_image_ids:[],
});

const makeProject=()=>({
  id:'f'.repeat(32),
  revision:4,
  title:'Secret Feature Film',
  master_prompt:'MASTER_SECRET_SENTINEL world world world',
  target_duration_seconds:600,
  delivery_fps:120,
  delivery_resolution:'2160p',
  aspect_ratio:'16:9',
  scenes:[
    {scene_id:'a'.repeat(32),ordinal:1,title:'Rooftop',target_duration_seconds:300,shots:Array.from({length:30},(_,i)=>makeShot(i+1))},
    {scene_id:'b'.repeat(32),ordinal:2,title:'Alley',target_duration_seconds:300,shots:Array.from({length:30},(_,i)=>makeShot(i+31))},
  ],
});

test('privacy-active project summaries use neutral labels and omit master prompt',()=>{
  const project=makeProject();
  assert.equal(neutralProjectLabel(0),'Film Project 1');
  const summary=summarizeProject(project,0,{privacy_mode:true,neutral_project_names:true});
  assert.equal(summary.label,'Film Project 1');
  assert.equal(summary.duration,'10:00');
  assert.equal(summary.scenes,2);
  assert.equal(summary.shots,60);
  assert.equal(JSON.stringify(summary).includes('MASTER_SECRET_SENTINEL'),false);
  assert.equal(JSON.stringify(summary).includes('Secret Feature Film'),false);
});

test('selected project survives list refresh when the project still exists',()=>{
  const project=makeProject();
  const selection=reconcileCinematicSelection({projectId:project.id,sceneId:project.scenes[1].scene_id,shotId:project.scenes[1].shots[2].shot_id},[project]);
  assert.equal(selection.projectId,project.id);
  assert.equal(selection.sceneId,project.scenes[1].scene_id);
  assert.equal(selection.shotId,project.scenes[1].shots[2].shot_id);
});

test('selection falls back deterministically when selected scene or shot disappears',()=>{
  const project=makeProject();
  const selection=reconcileCinematicSelection({projectId:project.id,sceneId:'c'.repeat(32),shotId:'d'.repeat(32)},[project]);
  assert.equal(selection.projectId,project.id);
  assert.equal(selection.sceneId,project.scenes[0].scene_id);
  assert.equal(selection.shotId,project.scenes[0].shots[0].shot_id);
});

test('scene summaries report shot counts and exact duration totals',()=>{
  const scene=makeProject().scenes[0];
  const summary=summarizeScene(scene);
  assert.equal(summary.shots,30);
  assert.equal(summary.seconds,300);
  assert.equal(summary.duration,'5:00');
});

test('long projects expose only a bounded shot window for the selected scene',()=>{
  const scene=makeProject().scenes[0];
  const visible=visibleShotsForScene(scene,{offset:0,limit:12});
  assert.equal(visible.items.length,12);
  assert.equal(visible.total,30);
  assert.equal(visible.hasMore,true);
  assert.equal(visible.items[0].ordinal,1);
  assert.equal(visible.items.at(-1).ordinal,12);
});

test('shot inspector view never carries the project master prompt',()=>{
  const project=makeProject();
  const shot=project.scenes[0].shots[0];
  const view=buildShotInspectorView(project,project.scenes[0],shot);
  assert.equal(view.title,'Shot 1');
  assert.equal(view.prompt,'Action 1');
  assert.equal(JSON.stringify(view).includes('MASTER_SECRET_SENTINEL'),false);
  assert.equal('master_prompt' in view,false);
});

test('plan quality view distinguishes native generation from delivery target',()=>{
  const view=buildPlanQualityView({
    generation_resolution:'1080p',generation_fps:60,
    delivery_resolution:'2160p',delivery_fps:120,
  });
  assert.deepEqual(view,{
    native:'1080p · 60 FPS',
    delivery:'2160p · 120 FPS target',
    finishingRequired:true,
  });
});

test('quick-hide cinematic view contains no project or prompt content',()=>{
  const project=makeProject();
  const view=buildNeutralCinematicView(project);
  assert.deepEqual(view,{title:'Workspace',message:'Private cinematic project is hidden.'});
  assert.equal(JSON.stringify(view).includes(project.title),false);
  assert.equal(JSON.stringify(view).includes(project.master_prompt),false);
});

test('studio shell loads cinematic launcher and responsive command-center styling',()=>{
  const here=path.dirname(fileURLToPath(import.meta.url));
  const web=path.join(here,'..','app','studio','web');
  const html=fs.readFileSync(path.join(web,'index.html'),'utf8');
  const css=fs.readFileSync(path.join(web,'cinematic-studio.css'),'utf8');
  const launcher=fs.readFileSync(path.join(web,'cinematic-launcher.js'),'utf8');
  assert.match(html,/\/studio\/cinematic-studio\.css/);
  assert.match(html,/\/studio\/cinematic-launcher\.js/);
  assert.doesNotMatch(html,/src="\/studio\/video-studio\.js"/);
  assert.match(css,/\.cinematic-shot-grid/);
  assert.match(css,/@media\(max-width:760px\)/);
  assert.match(launcher,/import\('\.\/video-studio\.js'\)/);
  assert.match(launcher,/stopImmediatePropagation\(\)/);
});
