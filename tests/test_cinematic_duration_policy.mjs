import test from 'node:test';
import assert from 'node:assert/strict';
import {validateFilmDuration} from '../app/studio/web/cinematic-studio.js';

test('film duration accepts precise selections through ten minutes',()=>{
  for(const seconds of [10,10.25,599.999,600])assert.equal(validateFilmDuration(seconds),seconds);
});
test('film duration rejects invalid and overlong values without silently changing them',()=>{
  for(const seconds of ['',null,'garbage',NaN,Infinity,0,9.99,600.001,28800])assert.throws(()=>validateFilmDuration(seconds),/600/);
});
