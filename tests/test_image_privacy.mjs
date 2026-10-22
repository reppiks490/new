import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

import {
  buildPrivateImageAssetRequest,
  renderPrivateImageJobSummary,
} from '../app/studio/web/image-studio.js';


test('studio shell exposes private Image tab and workspace', () => {
  const here=path.dirname(fileURLToPath(import.meta.url));
  const html=fs.readFileSync(path.join(here,'..','app','studio','web','index.html'),'utf8');
  assert.match(html,/data-tab="image"/);
  assert.match(html,/id="image-workspace"/);
  assert.match(html,/\/studio\/image-studio\.css/);
  assert.match(html,/\/studio\/image-studio\.js/);
});


test('private image assets use bearer auth without token leakage', () => {
  const request=buildPrivateImageAssetRequest('/api/image/assets/0123456789abcdef0123456789abcdef.png',{
    origin:'https://private.tailnet.example',
    token:'owner-secret-token',
  });
  assert.equal(request.url,'https://private.tailnet.example/api/image/assets/0123456789abcdef0123456789abcdef.png');
  assert.equal(request.options.headers.Authorization,'Bearer owner-secret-token');
  assert.equal(request.options.cache,'no-store');
  assert.equal(request.url.includes('owner-secret-token'),false);
});


test('private image job summaries never include the raw prompt', () => {
  const summary=renderPrivateImageJobSummary({
    id:'abc',status:'running',stage:'Generating',progress:52,prompt:'sensitive prompt',prompt_chars:16,
  },0,{privacy_mode:true,neutral_project_names:true});
  assert.equal(summary.label,'Project 1');
  assert.equal(summary.status,'Generating · 52%');
  assert.equal('prompt' in summary,false);
  assert.equal(JSON.stringify(summary).includes('sensitive prompt'),false);
});
