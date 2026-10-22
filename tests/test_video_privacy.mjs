import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

import {
  DEFAULT_PRIVACY_PREFERENCES,
  createPrivacyController,
  revealWhileHeld,
} from '../app/studio/web/privacy-mode.js';
import {
  neutralJobLabel,
  availableVideoControls,
  renderPrivateJobSummary,
  buildPrivateAssetRequest,
} from '../app/studio/web/video-studio.js';

class FakeTarget {
  constructor(){ this.handlers = new Map(); }
  addEventListener(name, fn){ if(!this.handlers.has(name))this.handlers.set(name, []); this.handlers.get(name).push(fn); }
  removeEventListener(name, fn){ const list=this.handlers.get(name)||[]; this.handlers.set(name,list.filter(item=>item!==fn)); }
  dispatch(name){ for(const fn of this.handlers.get(name)||[]) fn({type:name, preventDefault(){}}); }
}

class FakeDocument extends FakeTarget {
  constructor(){ super(); this.hidden=false; }
}


test('studio shell exposes a dedicated Video tab, workspace, stylesheet, and module', () => {
  const here=path.dirname(fileURLToPath(import.meta.url));
  const web=path.join(here,'..','app','studio','web');
  const html=fs.readFileSync(path.join(web,'index.html'),'utf8');
  const css=fs.readFileSync(path.join(web,'video-studio.css'),'utf8');
  assert.match(html,/data-tab="video"/);
  assert.match(html,/id="video-workspace"/);
  assert.match(html,/\/studio\/video-studio\.css/);
  // Cinematic mode owns the Video tab and lazy-imports the legacy quick
  // editor. A direct script tag would compete for the same click listener.
  const launcher=fs.readFileSync(path.join(web,'cinematic-launcher.js'),'utf8');
  assert.ok(
    /\/studio\/video-studio\.js/.test(html) ||
      (/\/studio\/cinematic-launcher\.js/.test(html) &&
       /import\(['"]\.\/video-studio\.js['"]\)/.test(launcher)),
    'Video editor must be reachable directly or via cinematic launcher',
  );
  assert.match(css,/\.privacy-blurred/);
  assert.match(css,/@media\(max-width:760px\)/);
});

test('privacy defaults protect prompt, media, quick hide, and resume', () => {
  assert.deepEqual(DEFAULT_PRIVACY_PREFERENCES, {
    privacy_mode: true,
    mask_prompts: true,
    blur_media: true,
    quick_hide: true,
    idle_lock_seconds: 30,
    require_unlock_on_resume: true,
    neutral_project_names: true,
  });
  const privacy=createPrivacyController();
  assert.equal(privacy.shouldMaskPrompt(), true);
  assert.equal(privacy.shouldBlurMedia('source'), true);
  assert.equal(privacy.isQuickHidden(), false);
});

test('press and hold reveal returns to concealed on every release path', () => {
  const privacy=createPrivacyController();
  const target=new FakeTarget();
  const cleanup=revealWhileHeld(target,'source',privacy);
  for(const down of ['pointerdown','touchstart']){
    target.dispatch(down);
    assert.equal(privacy.isRevealed('source'), true);
    for(const up of ['pointerup','pointercancel','pointerleave','touchend','touchcancel']){
      target.dispatch(up);
      assert.equal(privacy.isRevealed('source'), false);
      target.dispatch(down);
    }
  }
  cleanup();
});

test('visibilitychange immediately conceals revealed media and quick hides when resume lock is enabled', () => {
  const doc=new FakeDocument();
  const privacy=createPrivacyController({documentRef:doc});
  const cleanup=privacy.attachVisibilityGuard();
  privacy.reveal('prompt');
  privacy.reveal('preview');
  doc.hidden=true;
  doc.dispatch('visibilitychange');
  assert.equal(privacy.isRevealed('prompt'), false);
  assert.equal(privacy.isRevealed('preview'), false);
  assert.equal(privacy.isQuickHidden(), true);
  cleanup();
});

test('quick hide clears reveal state and restore leaves sensitive content concealed', () => {
  const privacy=createPrivacyController();
  privacy.reveal('prompt');
  privacy.quickHide();
  assert.equal(privacy.isQuickHidden(), true);
  assert.equal(privacy.isRevealed('prompt'), false);
  privacy.restore();
  assert.equal(privacy.isQuickHidden(), false);
  assert.equal(privacy.isRevealed('prompt'), false);
});


test('idle guard quick hides private content after the configured timeout', () => {
  const doc=new FakeDocument();
  let scheduled=null;
  let cleared=[];
  const privacy=createPrivacyController({
    documentRef:doc,
    setTimeoutRef:(fn,ms)=>{scheduled={fn,ms,id:7};return 7;},
    clearTimeoutRef:id=>cleared.push(id),
  });
  const cleanup=privacy.attachIdleGuard();
  assert.equal(scheduled.ms,30000);
  privacy.reveal('prompt');
  scheduled.fn();
  assert.equal(privacy.isQuickHidden(),true);
  assert.equal(privacy.isRevealed('prompt'),false);
  cleanup();
  assert.ok(cleared.includes(7));
});

test('privacy-active job summaries use neutral labels and omit prompt data', () => {
  const job={id:'abc',status:'running',stage:'Generating',progress:44,prompt:'secret prompt',prompt_chars:13};
  assert.equal(neutralJobLabel(0),'Project 1');
  const summary=renderPrivateJobSummary(job,0,{privacy_mode:true,neutral_project_names:true});
  assert.equal(summary.label,'Project 1');
  assert.equal(summary.status,'Generating · 44%');
  assert.equal('prompt' in summary,false);
  assert.equal(JSON.stringify(summary).includes('secret prompt'),false);
});

test('capability-driven controls disable unsupported motion and camera settings', () => {
  const capability={
    name:'limited',
    profiles:['balanced'],
    supported_resolutions:['720p'],
    supported_fps:[24],
    supports_motion_strength:false,
    camera_motion_presets:['static'],
  };
  assert.deepEqual(availableVideoControls(capability),{
    profiles:['balanced'],
    resolutions:['720p'],
    fps:[24],
    motionStrength:false,
    cameraMotions:['static'],
  });
});


test('private media assets use bearer headers without leaking tokens into URLs', () => {
  const request=buildPrivateAssetRequest('/api/video/assets/0123456789abcdef0123456789abcdef.mp4',{
    origin:'https://private.tailnet.example',
    token:'super-secret-token',
  });
  assert.equal(request.url,'https://private.tailnet.example/api/video/assets/0123456789abcdef0123456789abcdef.mp4');
  assert.equal(request.options.headers.Authorization,'Bearer super-secret-token');
  assert.equal(request.options.cache,'no-store');
  assert.equal(request.url.includes('super-secret-token'),false);
});
