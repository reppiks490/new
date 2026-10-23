import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createCinematicAssemblyClient,
  normalizeAssemblyJob,
  assemblyStatusSummary,
  isTerminalAssemblyStatus,
} from '../app/studio/web/cinematic-assembly-client.js';

const PROJECT='a'.repeat(32);
const JOB='b'.repeat(32);
const ASSET='c'.repeat(32);
const job=(status,extra={})=>({
  id:JOB,project_id:PROJECT,project_revision:4,ffmpeg_path:'ffmpeg',
  status,stage:'Sensitive server stage',progress:status==='running'?null:0,
  ...extra,
});

test('mobile queue requests include only opaque IDs, revision and method',async()=>{
  const calls=[];
  const client=createCinematicAssemblyClient({
    api:async(path,options)=>{calls.push([path,options]);return job('queued');},
  });
  const queued=await client.submit(PROJECT,4);
  assert.equal(queued.status,'queued');
  assert.equal(queued.progress,0);
  assert.deepEqual(calls,[[
    '/projects/'+PROJECT+'/assembly-jobs',
    {method:'POST',body:JSON.stringify({expected_revision:4})},
  ]]);
  assert.equal(JSON.stringify(calls).includes('Bearer'),false);
  assert.equal(JSON.stringify(calls).includes('prompt'),false);
});

test('polling reports unknown progress as null, never fabricates a running percentage',()=>{
  const normalized=normalizeAssemblyJob(job('running', {progress:null,
    master_prompt:'TOP_SECRET_SCRIPT',error:'Private engine pathname'}),{projectId:PROJECT,jobId:JOB});
  assert.equal(normalized.progress,null);
  assert.equal(normalized.assetUrl,null);
  assert.equal(JSON.stringify(normalized).includes('TOP_SECRET_SCRIPT'),false);
  assert.equal(JSON.stringify(normalized).includes('Private engine pathname'),false);
  assert.deepEqual(assemblyStatusSummary(normalized),{
    label:'Film master',status:'Assembling master',progressLabel:null,terminal:false,
    ready:false,assetUrl:null,
  });
  assert.equal(isTerminalAssemblyStatus('queued'),false);
  assert.equal(isTerminalAssemblyStatus('running'),false);
  assert.equal(isTerminalAssemblyStatus('succeeded'),true);
  assert.equal(isTerminalAssemblyStatus('cancelled'),true);
});

test('verified ready master only exposes exact private asset path, not arbitrary URLs',()=>{
  const asset='/api/video/assets/'+ASSET+'.mp4';
  const valid=normalizeAssemblyJob(job('succeeded',{
    progress:100,asset_id:ASSET,
    asset_url:asset,probe_metadata_verified:true,sha256:'d'.repeat(64),
  }),{projectId:PROJECT,jobId:JOB});
  assert.equal(valid.assetUrl,asset);
  assert.equal(assemblyStatusSummary(valid).ready,true);
  for(const attrs of [
    {asset_url:'https://evil.example/video.mp4'},
    {asset_url:asset+'?token=leak'},
    {probe_metadata_verified:false},
    {sha256:'not-a-checksum'},
  ]){
    const tampered=normalizeAssemblyJob(job('succeeded',{
      progress:100,asset_id:ASSET,
      asset_url:asset,probe_metadata_verified:true,sha256:'d'.repeat(64),...attrs,
    }),{projectId:PROJECT,jobId:JOB});
    assert.equal(tampered.assetUrl,null);
    assert.equal(assemblyStatusSummary(tampered).ready,false);
    assert.equal(assemblyStatusSummary(tampered).status,'Master verification unavailable');
  }
});

test('polling completes through queued, running, then verified master without exposing raw records',async()=>{
  const responses=[
    job('queued'),job('running',{progress:null}),
    job('succeeded',{
      progress:100,asset_id:ASSET,
      asset_url:'/api/video/assets/'+ASSET+'.mp4',probe_metadata_verified:true,
      sha256:'e'.repeat(64),
    }),
  ];
  let sleeps=0;
  const observed=[];
  const client=createCinematicAssemblyClient({
    api:async()=>responses.shift(),
    sleep:async()=>{sleeps+=1;},
  });
  const result=await client.waitForTerminal(PROJECT,JOB,{
    intervalMs:1000,onUpdate:value=>observed.push(value.status),
  });
  assert.equal(result.status,'succeeded');
  assert.equal(result.assetUrl,'/api/video/assets/'+ASSET+'.mp4');
  assert.deepEqual(observed,['queued','running','succeeded']);
  assert.equal(sleeps,2);
});

test('abort interrupts polling without another API call',async()=>{
  const abort=new AbortController();
  let requests=0,sleeps=0;
  const client=createCinematicAssemblyClient({
    api:async()=>{requests+=1;return job('running');},
    sleep:async()=>{sleeps+=1;abort.abort();},
  });
  await assert.rejects(
    client.waitForTerminal(PROJECT,JOB,{signal:abort.signal}),
    error=>error.name==='AbortError',
  );
  assert.equal(requests,1);
  assert.equal(sleeps,1);
});

test('resume searches every server page and does not silently lose an old queued job',async()=>{
  const calls=[];
  const client=createCinematicAssemblyClient({api:async(path)=>{
    calls.push(path);
    if(path.includes('offset=0')) return {
      jobs:[job('succeeded'),job('failed')],total:3,offset:0,limit:2,has_more:true,
    };
    return {jobs:[job('queued',{id:'f'.repeat(32)})],
      total:3,offset:2,limit:2,has_more:false};
  }});
  const active=await client.findActive(PROJECT,{pageSize:2});
  assert.equal(active.id,'f'.repeat(32));
  assert.equal(active.status,'queued');
  assert.equal(calls.length,2);
  assert.match(calls[1],/offset=2/);
});

test('cancel a queued master without claiming to stop running or finished encodes',async()=>{
  const calls=[];
  const client=createCinematicAssemblyClient({api:async(path,options)=>{
    calls.push([path,options]);
    return job('cancelled');
  }});
  const cancelled=await client.cancel(PROJECT,JOB);
  assert.equal(cancelled.status,'cancelled');
  assert.equal(calls[0][0],'/projects/'+PROJECT+'/assembly-jobs/'+JOB+'/cancel');
  assert.equal(calls[0][1].method,'POST');
});

test('reject invalid IDs, revisions and malformed server pagination',async()=>{
  const c=createCinematicAssemblyClient({api:async()=>({
    jobs:[],total:10,offset:0,limit:2,has_more:true,
  })});
  await assert.rejects(c.submit('../film',4),/project ID/i);
  await assert.rejects(c.submit(PROJECT,0),/revision/i);
  await assert.rejects(c.get(PROJECT,'Bearer token'),/job ID/i);
  await assert.rejects(c.findActive(PROJECT,{pageSize:2}),/pagination/i);
});


test('temporary iPhone network drops retry serially with bounded backoff and preserve the job identity',async()=>{
  let reads=0;
  let concurrent=0;
  let maxConcurrent=0;
  const sleeps=[];
  const phases=[];
  const client=createCinematicAssemblyClient({
    api:async()=>{
      concurrent++;maxConcurrent=Math.max(maxConcurrent,concurrent);
      try{
        reads++;
        if(reads===1)throw new TypeError('Failed to fetch');
        if(reads===2){const failure=new Error('Request timed out');failure.name='TimeoutError';throw failure;}
        return job('succeeded',{
          progress:100,asset_id:ASSET,
          asset_url:'/api/video/assets/'+ASSET+'.mp4',
          probe_metadata_verified:true,sha256:'e'.repeat(64),
        });
      }finally{concurrent--;}
    },
    sleep:async ms=>{sleeps.push(ms);},
  });
  const latest=await client.waitForTerminal(PROJECT,JOB,{
    intervalMs:1000,maxTransientFailures:3,
    onConnectionChange:state=>phases.push(state),
  });
  assert.equal(latest.status,'succeeded');
  assert.equal(latest.id,JOB);
  assert.equal(maxConcurrent,1);
  assert.deepEqual(sleeps,[1000,2000]);
  assert.deepEqual(phases,['retrying','retrying','connected']);
});

test('persistent network failure stops after configured finite retries, preserving explicit resume',async()=>{
  let reads=0;
  const client=createCinematicAssemblyClient({
    api:async()=>{reads++;throw new TypeError('Network disconnected');},
    sleep:async()=>{},
  });
  await assert.rejects(
    client.waitForTerminal(PROJECT,JOB,{intervalMs:250,maxTransientFailures:2}),
    /Network disconnected/,
  );
  assert.equal(reads,3);
});

test('authentication errors are never retried as network interruptions',async()=>{
  let reads=0;
  const client=createCinematicAssemblyClient({
    api:async()=>{reads++;throw new Error('Video request failed (401)');},
    sleep:async()=>{throw new Error('Unexpected retry');},
  });
  await assert.rejects(
    client.waitForTerminal(PROJECT,JOB,{maxTransientFailures:8}),
    /401/,
  );
  assert.equal(reads,1);
});

test('abort during reconnect retry ends polling without another request',async()=>{
  let reads=0;
  const controller=new AbortController();
  const client=createCinematicAssemblyClient({
    api:async()=>{reads++;throw new TypeError('Fetch failed');},
    sleep:async()=>{controller.abort();},
  });
  await assert.rejects(
    client.waitForTerminal(PROJECT,JOB,{
      signal:controller.signal,maxTransientFailures:4,
    }),
    error=>error.name==='AbortError',
  );
  assert.equal(reads,1);
});

test('paginated reconnect scanning is abortable after leaving the private cinematic workspace',async()=>{
  const controller=new AbortController();
  let reads=0;
  const client=createCinematicAssemblyClient({api:async()=>{
    reads++;
    controller.abort();
    return {jobs:[job('failed')],total:4,offset:0,limit:2,has_more:true};
  }});
  await assert.rejects(
    client.findActive(PROJECT,{pageSize:2,signal:controller.signal}),
    error=>error.name==='AbortError',
  );
  assert.equal(reads,1);
});
