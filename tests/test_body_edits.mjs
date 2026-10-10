import test from 'node:test';
import assert from 'node:assert/strict';
import human from '../app/studio/web/data/human.json' with {type:'json'};
import maskSpec from '../app/studio/web/data/body_region_masks.json' with {type:'json'};
import {applyBodyEdits,buildRegionMasks} from '../app/studio/web/body-edits.js';

test('browser waist edit uses the authored waist mask and protects hip and glute vertices',()=>{
  const source=Float32Array.from(human.positions.flat());
  const masks=buildRegionMasks(source,human,maskSpec);
  assert.ok(masks.waist.size>500);
  const {positions,reports}=applyBodyEdits(source,human,maskSpec,[{region:'waist',operation:'reduce_width',amount_pct:10,protected_regions:['hips','glutes']}]);
  for(const region of ['hips','glutes'])for(const index of masks[region]){
    const offset=index*3;assert.equal(positions[offset],source[offset]);assert.equal(positions[offset+1],source[offset+1]);assert.equal(positions[offset+2],source[offset+2]);
  }
  assert.ok(reports[0].changed_vertices>500);
  assert.deepEqual(reports[0].protected_max_delta,{hips:0,glutes:0});
});

test('unsupported browser body edits fail without modifying the input array',()=>{
  const source=Float32Array.from(human.positions.flat()),before=source.slice();
  assert.throws(()=>applyBodyEdits(source,human,maskSpec,[{region:'hips',operation:'reduce_width',amount_pct:10,protected_regions:[]}]),/Only mapped waist/);
  assert.throws(()=>applyBodyEdits(source,human,maskSpec,[{region:'waist',operation:'increase_width',amount_pct:1,protected_regions:[]}]),/Only mapped waist-width reduction/);
  assert.deepEqual(source,before);
});
