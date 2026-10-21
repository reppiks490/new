import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createPrivacyController, DEFAULT_PRIVACY} from '../app/studio/web/privacy-mode.js';
import {neutralJobLabel, deriveControlSupport} from '../app/studio/web/video-studio.js';

class FakeDocument extends EventTarget {
  constructor(){
    super();
    this.hidden=false;
  }
}

class FakeElement extends EventTarget {}

const wait = ms => new Promise(resolve=>setTimeout(resolve,ms));

test('privacy defaults hide prompt and media',()=>{
  const doc=new FakeDocument();
  const privacy=createPrivacyController({documentRef:doc,settings:DEFAULT_PRIVACY});
  assert.equal(privacy.isHidden('prompt'),true);
  assert.equal(privacy.isHidden('source'),true);
  assert.equal(privacy.isHidden('result'),true);
  privacy.destroy();
});

test('hold reveal returns to hidden on release and cancel',()=>{
  const doc=new FakeDocument();
  const privacy=createPrivacyController({documentRef:doc,settings:DEFAULT_PRIVACY});
  const element=new FakeElement();
  privacy.bindHold(element,'source');

  element.dispatchEvent(new Event('pointerdown'));
  assert.equal(privacy.isHidden('source'),false);
  element.dispatchEvent(new Event('pointerup'));
  assert.equal(privacy.isHidden('source'),true);

  element.dispatchEvent(new Event('pointerdown'));
  assert.equal(privacy.isHidden('source'),false);
  element.dispatchEvent(new Event('pointercancel'));
  assert.equal(privacy.isHidden('source'),true);

  element.dispatchEvent(new Event('touchstart'));
  assert.equal(privacy.isHidden('source'),false);
  element.dispatchEvent(new Event('touchend'));
  assert.equal(privacy.isHidden('source'),true);
  privacy.destroy();
});

test('backgrounding immediately conceals and locks private content',()=>{
  const doc=new FakeDocument();
  const privacy=createPrivacyController({documentRef:doc,settings:DEFAULT_PRIVACY});
  privacy.reveal('prompt');
  assert.equal(privacy.isHidden('prompt'),false);
  doc.hidden=true;
  doc.dispatchEvent(new Event('visibilitychange'));
  assert.equal(privacy.isHidden('prompt'),true);
  assert.equal(privacy.snapshot().locked,true);
  privacy.destroy();
});

test('quick hide switches to neutral locked state',()=>{
  const doc=new FakeDocument();
  const privacy=createPrivacyController({documentRef:doc,settings:DEFAULT_PRIVACY});
  privacy.unlock();
  privacy.reveal('result');
  privacy.quickHide();
  const state=privacy.snapshot();
  assert.equal(state.quickHidden,true);
  assert.equal(state.locked,true);
  assert.equal(privacy.isHidden('result'),true);
  privacy.destroy();
});

test('idle timeout locks and re-hides revealed content',async()=>{
  const doc=new FakeDocument();
  const privacy=createPrivacyController({documentRef:doc,settings:{...DEFAULT_PRIVACY,idle_lock_seconds:0.02}});
  privacy.unlock();
  privacy.reveal('prompt');
  assert.equal(privacy.isHidden('prompt'),false);
  await wait(35);
  assert.equal(privacy.snapshot().locked,true);
  assert.equal(privacy.isHidden('prompt'),true);
  privacy.destroy();
});

test('privacy-active recent jobs use neutral names instead of prompts',()=>{
  const job={id:'abc',prompt:'sensitive prompt',stage:'Ready'};
  assert.equal(neutralJobLabel(job,0,{privacy_mode:true,neutral_project_names:true}),'Project 1');
  assert.equal(neutralJobLabel(job,4,{privacy_mode:true,neutral_project_names:true}),'Project 5');
  assert.equal(neutralJobLabel(job,0,{privacy_mode:false,neutral_project_names:true}),'Video 1');
});

test('unsupported controls are disabled from engine capability payload',()=>{
  const support=deriveControlSupport({
    engines:[{
      name:'local-test',available:true,
      supports_motion_strength:false,
      supports_camera_motion:true,
      resolutions:['480p','720p'],profiles:['balanced']
    }],
    recommended_profile:'balanced'
  });
  assert.equal(support.motionStrength,false);
  assert.equal(support.cameraMotion,true);
  assert.deepEqual(support.resolutions,['480p','720p']);
  assert.deepEqual(support.profiles,['balanced']);
});

test('studio shell mounts Video panel without persistent secret storage',()=>{
  const html=readFileSync(new URL('../app/studio/web/index.html',import.meta.url),'utf8');
  const source=readFileSync(new URL('../app/studio/web/video-studio.js',import.meta.url),'utf8');
  assert.match(html,/data-tab="video"/);
  assert.match(html,/video-studio\.css/);
  assert.match(html,/video-studio\.js/);
  assert.match(source,/\/api\/video/);
  assert.doesNotMatch(source,/localStorage|sessionStorage/);
  assert.match(source,/type="\$\{privacy\.isHidden\('prompt'\)\?'password':'text'\}"/);
  assert.match(source,/Quick Hide/);
});
