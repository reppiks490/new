import test from 'node:test';
import assert from 'node:assert/strict';
import {createCinematicMasterPreview} from '../app/studio/web/cinematic-master-preview.js';

const MEDIA='/api/video/assets/'+'c'.repeat(32)+'.mp4';
const VERIFIED=Object.freeze({status:'succeeded',verified:true,assetUrl:MEDIA});

function setup({response,limit=80*1024*1024,request}={}){
  let next=0;
  const calls=[],issued=[],revoked=[];
  const fetchMedia=request||async path=>{calls.push(path);return response;};
  const preview=createCinematicMasterPreview({
    fetchMedia,
    maxBytes:limit,
    createObjectURL:()=>{const url='blob:private-'+(++next);issued.push(url);return url;},
    revokeObjectURL:url=>revoked.push(url),
  });
  return {preview,calls,issued,revoked};
}

function fakeResponse({bytes=1024,type='video/mp4',reported=bytes,ok=true}={}){
  let reads=0;
  const blob={size:bytes,type};
  const response={
    ok,
    headers:{get:key=>key.toLowerCase()==='content-type'?type:
      key.toLowerCase()==='content-length'?String(reported):null},
    blob:async()=>{reads++;return blob;},
  };
  return {response,reads:()=>reads};
}

test('verified MP4 is fetched only by relative bearer-capable path, with revocable object URL',async()=>{
  const fixture=fakeResponse();
  const {preview,calls,issued,revoked}=setup({response:fixture.response});
  assert.equal(await preview.open(VERIFIED),'blob:private-1');
  assert.deepEqual(calls,[MEDIA]);
  assert.equal(fixture.reads(),1);
  assert.equal(preview.currentUrl(),'blob:private-1');
  preview.close();
  assert.deepEqual(revoked,issued);
  assert.equal(preview.currentUrl(),null);
});

test('do not fetch unverified, external or tokenized masters',async()=>{
  const fixture=fakeResponse();
  const {preview,calls}=setup({response:fixture.response});
  for(const item of [
    {...VERIFIED,verified:false},
    {...VERIFIED,status:'queued'},
    {...VERIFIED,assetUrl:'https://evil.example/movie.mp4'},
    {...VERIFIED,assetUrl:MEDIA+'?api_key=secret'},
    {...VERIFIED,assetUrl:'/api/video/assets/../../etc/passwd'},
  ]){
    await assert.rejects(preview.open(item),/verified|asset/i);
  }
  assert.equal(calls.length,0);
});

test('oversize and missing-length media are rejected before loading a blob',async()=>{
  const tooLarge=fakeResponse({reported:2000,bytes:1000});
  const {preview}=setup({response:tooLarge.response,limit:1500});
  await assert.rejects(preview.open(VERIFIED),/too large/i);
  assert.equal(tooLarge.reads(),0);

  const noHeader={
    ok:true,
    headers:{get: key=>key.toLowerCase()==='content-type'?'video/mp4':null},
    blob:async()=>{throw new Error('must not allocate');},
  };
  const next=setup({response:noHeader});
  await assert.rejects(next.preview.open(VERIFIED),/length/i);
});

test('untrustworthy reported length, type, response status and blob size fail closed',async()=>{
  for(const options of [
    {reported:1024,bytes:1536},
    {type:'text/html'},
    {ok:false},
  ]){
    const fixture=fakeResponse(options);
    const {preview,issued}=setup({response:fixture.response});
    await assert.rejects(preview.open(VERIFIED),/length|MP4|failed/i);
    assert.deepEqual(issued,[]);
  }
});

test('closing or quick-hiding while a media fetch is in flight cannot resurrect its object URL',async()=>{
  let resolveResponse;
  const pending=new Promise(resolve=>{resolveResponse=resolve;});
  const fixture=fakeResponse();
  const {preview,issued}=setup({request:async()=>pending});
  const inFlight=preview.open(VERIFIED);
  preview.close();
  resolveResponse(fixture.response);
  assert.equal(await inFlight,null);
  assert.equal(fixture.reads(),0);
  assert.deepEqual(issued,[]);
});

test('opening a new master makes an old in-flight fetch stale and revokes prior URL',async()=>{
  let resolveOld;
  const oldPromise=new Promise(resolve=>{resolveOld=resolve;});
  const fixture=fakeResponse();
  let requests=0;
  const {preview,issued,revoked}=setup({
    request:async()=>{requests++;return requests===1?oldPromise:fixture.response;},
  });
  const obsolete=preview.open(VERIFIED);
  const newer=await preview.open(VERIFIED);
  resolveOld(fixture.response);
  assert.equal(await obsolete,null);
  assert.equal(newer,'blob:private-1');
  assert.deepEqual(issued,['blob:private-1']);
  preview.close();
  assert.deepEqual(revoked,['blob:private-1']);
});

test('size limit is validated and object URLs never contain bearer tokens',()=>{
  assert.throws(()=>createCinematicMasterPreview({
    fetchMedia:async()=>null,maxBytes:-1,
  }),/limit/i);
});
