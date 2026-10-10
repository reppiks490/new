import test from 'node:test';
import assert from 'node:assert/strict';
import {parseEditIntent} from '../app/studio/web/edit-intent.js';

test('protected waist request targets the waist and protects glutes and hips',()=>{
  assert.deepEqual(parseEditIntent('slim her waist without reducing glute and hip size'),{
    status:'needs_review',operation:'reduce_width',target_regions:['waist'],
    protected_regions:['glutes','hips'],amount:null,amount_unit:null,
    requires_amount_review:true,reason:'Choose the amount before applying this edit.'
  });
});

test('explicit percentage is parsed without a guessed default',()=>{
  const result=parseEditIntent('reduce waist width by 12%');
  assert.equal(result.operation,'reduce_width');
  assert.deepEqual(result.target_regions,['waist']);
  assert.equal(result.amount,12);assert.equal(result.amount_unit,'percent');
  assert.equal(result.requires_amount_review,false);
});

test('physical units remain explicit',()=>{
  const result=parseEditIntent('reduce waist by 2.5 cm');
  assert.equal(result.amount,2.5);assert.equal(result.amount_unit,'cm');
});

test('explicit comparison ranges are rejected until a conversion rule is specified',()=>{
  const result=parseEditIntent('reduce waist width from 80 cm to 70 cm');
  assert.equal(result.status,'unsupported');
  assert.match(result.reason,/amount/i);
});

test('negative signed amounts are not reinterpreted as positive changes',()=>{
  const result=parseEditIntent('increase waist width by -10%');
  assert.equal(result.status,'unsupported');
  assert.match(result.reason,/positive amount/i);
});

test('set-to comparisons have an explicit set operation',()=>{
  const result=parseEditIntent('set waist size to 70%');
  assert.equal(result.operation,'set_size');
  assert.equal(result.amount,70);
});

test('one action can target multiple regions joined by and',()=>{
  const result=parseEditIntent('increase glute and hip size by 20%');
  assert.deepEqual(result.target_regions,['glutes','hips']);
  assert.equal(result.operation,'increase_size');
});

test('without clauses protect rather than edit their regions',()=>{
  const result=parseEditIntent('slim waist without reducing glutes or hips');
  assert.deepEqual(result.target_regions,['waist']);
  assert.deepEqual(result.protected_regions,['glutes','hips']);
});

test('region synonyms resolve to canonical names',()=>{
  const result=parseEditIntent('narrow the midsection without changing backside size');
  assert.deepEqual(result.target_regions,['waist']);
  assert.deepEqual(result.protected_regions,['glutes']);
});

test('unrecognized anatomy is blocked instead of silently ignored',()=>{
  const result=parseEditIntent('make her wings larger by 20%');
  assert.equal(result.status,'unsupported');
  assert.match(result.reason,/region|anatomy/i);
});

test('conflicting direction verbs are blocked',()=>{
  const result=parseEditIntent('increase and reduce waist size by 20%');
  assert.equal(result.status,'unsupported');
  assert.match(result.reason,/conflict/i);
});

test('conflicting amount expressions are blocked',()=>{
  const result=parseEditIntent('slim waist by 10% and 3 cm');
  assert.equal(result.status,'unsupported');
  assert.match(result.reason,/amount/i);
});

test('recognized region without an operation needs clarification',()=>{
  const result=parseEditIntent('change the waist');
  assert.equal(result.status,'needs_review');
  assert.equal(result.operation,null);
  assert.match(result.reason,/operation/i);
});

test('empty and overlong prompts fail with actionable errors',()=>{
  assert.throws(()=>parseEditIntent('  '),/enter/i);
  assert.throws(()=>parseEditIntent('x'.repeat(2001)),/2,000/);
});
