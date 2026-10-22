import test from 'node:test';
import assert from 'node:assert/strict';

import {bindVolatileEditorDraft} from '../app/studio/web/private-media-draft.js';

class FakeInput {
  constructor(value='') {
    this.value=value;
    this.events=new Map();
  }
  addEventListener(name, callback) {
    if(!this.events.has(name))this.events.set(name,[]);
    this.events.get(name).push(callback);
  }
  emit(name) {
    for(const callback of this.events.get(name)||[])callback();
  }
}

function fakeInspector(fields) {
  return {querySelector:selector=>fields[selector.slice(1)]||null};
}

test('private image prompt and seed survive inspector replacement without HTML interpolation', () => {
  const draft={};
  const original={
    'image-prompt':new FakeInput(),
    'image-seed':new FakeInput('0'),
  };
  bindVolatileEditorDraft(fakeInspector(original),draft,{prompt:'image-prompt',seed:'image-seed'});
  const sensitive='Private <scene> & "character" prompt';
  original['image-prompt'].value=sensitive;
  original['image-prompt'].emit('input');
  original['image-seed'].value='456';
  original['image-seed'].emit('change');
  assert.deepEqual(draft,{prompt:sensitive,seed:'456'});
  const replacement={
    'image-prompt':new FakeInput(),
    'image-seed':new FakeInput('0'),
  };
  bindVolatileEditorDraft(fakeInspector(replacement),draft,{prompt:'image-prompt',seed:'image-seed'});
  assert.equal(replacement['image-prompt'].value,sensitive);
  assert.equal(replacement['image-seed'].value,'456');
});

test('private video motion settings and prompt survive privacy screen reconstruction', () => {
  const fields={
    prompt:'video-prompt',
    profile:'video-profile',
    resolution:'video-resolution',
    fps:'video-fps',
    duration:'video-duration',
    seed:'video-seed',
    camera:'video-camera',
    motion:'video-motion',
  };
  const draft={};
  const original=Object.fromEntries(Object.values(fields).map(id=>[id,new FakeInput()]));
  bindVolatileEditorDraft(fakeInspector(original),draft,fields);
  for(const [index,id] of Object.values(fields).entries()){
    original[id].value=`private-value-${index}`;
    original[id].emit('input');
  }
  const reconstructed=Object.fromEntries(Object.values(fields).map(id=>[id,new FakeInput('reset')]));
  bindVolatileEditorDraft(fakeInspector(reconstructed),draft,fields);
  for(const [index,id] of Object.values(fields).entries()){
    assert.equal(reconstructed[id].value,`private-value-${index}`);
  }
  assert.equal(Object.keys(draft).length,8);
});

test('missing or newly introduced editor controls are tolerated', () => {
  const draft={prompt:'still private'};
  const root=fakeInspector({'image-prompt':new FakeInput()});
  assert.doesNotThrow(()=>bindVolatileEditorDraft(root,draft,{prompt:'image-prompt',missing:'future-control'}));
  assert.equal(root.querySelector('#image-prompt').value,'still private');
  assert.doesNotThrow(()=>bindVolatileEditorDraft(null,draft,{prompt:'image-prompt'}));
});
