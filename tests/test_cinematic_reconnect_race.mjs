import test from 'node:test';
import assert from 'node:assert/strict';
import {createCinematicAssemblyClient} from '../app/studio/web/cinematic-assembly-client.js';

const PROJECT='1'.repeat(32), A='2'.repeat(32), B='3'.repeat(32), C='4'.repeat(32);
const job=(id,status)=>({id,project_id:PROJECT,project_revision:1,status,progress:null});
const page=(items,offset,hasMore)=>({
  jobs:items.map(([id,status])=>job(id,status)),total:3,offset,limit:2,has_more:hasMore,
});

test('reconnect retries when an active job moves to an already scanned page',async()=>{
  const calls=[];
  const responses=[
    page([[A,'succeeded'],[B,'failed']],0,true),
    page([[B,'failed']],2,false),
    page([[C,'running'],[A,'succeeded']],0,true),
  ];
  const client=createCinematicAssemblyClient({api:async path=>{
    calls.push(Number(path.split('offset=')[1]));return responses.shift();
  }});
  const active=await client.findActive(PROJECT,{pageSize:2});
  assert.equal(active.id,C);
  assert.equal(active.status,'running');
  assert.deepEqual(calls,[0,2,0]);
});

test('persistent reorder raises instability instead of false no-active result',async()=>{
  const calls=[];
  const client=createCinematicAssemblyClient({api:async path=>{
    const offset=Number(path.split('offset=')[1]);calls.push(offset);
    return offset===0
      ?page([[A,'succeeded'],[B,'failed']],0,true)
      :page([[B,'failed']],2,false);
  }});
  await assert.rejects(
    client.findActive(PROJECT,{pageSize:2,maxPasses:3}),
    /history changed during reconnect/,
  );
  assert.deepEqual(calls,[0,2,0,2,0,2]);
});

test('abort prevents another reconnect page request',async()=>{
  const signal={aborted:false};let calls=0;
  const client=createCinematicAssemblyClient({api:async()=>{
    calls++;signal.aborted=true;
    return page([[A,'failed'],[B,'succeeded']],0,true);
  }});
  await assert.rejects(
    client.findActive(PROJECT,{pageSize:2,signal}),
    error=>error.name==='AbortError',
  );
  assert.equal(calls,1);
});

test('stable history still finishes in one pass',async()=>{
  let calls=0;
  const client=createCinematicAssemblyClient({api:async path=>{
    calls++;const offset=Number(path.split('offset=')[1]);
    return offset===0
      ?page([[A,'succeeded'],[B,'failed']],0,true)
      :page([[C,'cancelled']],2,false);
  }});
  assert.equal(await client.findActive(PROJECT,{pageSize:2}),null);
  assert.equal(calls,2);
});
