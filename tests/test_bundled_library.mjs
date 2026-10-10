import test from 'node:test';
import assert from 'node:assert/strict';
import {validateBundledLibrary,loadBundledLibrary,downloadBundledModel} from '../app/studio/web/bundled-library.js';

const options={origin:'https://studio.example',maxBytes:150*1024*1024};
const model=()=>({id:'abc123',name:'Example source',sha256:'a'.repeat(64),bytes:6,
  chunks:[{url:'/studio/library/abc123/000.bin',bytes:2},{url:'/studio/library/abc123/001.bin',bytes:4}]});

test('manifest preserves source identity and canonicalizes local chunk URLs',()=>{
  const [result]=validateBundledLibrary([model()],options);
  assert.equal(result.id,'abc123');assert.equal(result.sha256,'a'.repeat(64));
  assert.equal(result.chunks[0].url,'https://studio.example/studio/library/abc123/000.bin');
});

test('manifest rejects external, credentialed, redirected-path and non-library URLs',()=>{
  for(const url of ['https://other.example/studio/library/a.bin','https://user:secret@studio.example/studio/library/a.bin',
    '/api/studio/assets/a.glb','/studio/library/../a.bin','/studio/library/%2e%2e/a.bin',
    '/studio/library/a.bin?target=elsewhere','/studio/library/a.bin#x','/studio/library/dir\\a.bin']){
    const record=model();record.chunks[0].url=url;
    assert.throws(()=>validateBundledLibrary([record],options),/bundled model URL/);
  }
});

test('manifest rejects invalid identities, duplicate ids and oversized or inconsistent chunks',()=>{
  for(const changes of [{id:12},{sha256:'bad'},{bytes:options.maxBytes+1},{bytes:0},{bytes:7},{bytes:5},
    {chunks:[]},{chunks:[{url:'/studio/library/a.bin',bytes:16*1024*1024+1}]},
    {chunks:[{url:'/studio/library/a.bin',bytes:3},{url:'/studio/library/a.bin',bytes:3}]}]){
    assert.throws(()=>validateBundledLibrary([{...model(),...changes}],options));
  }
  assert.throws(()=>validateBundledLibrary([model(),model()],options));
});

test('chunks download sequentially into the exact original byte order without auth headers',async()=>{
  const requests=[],progress=[];
  const result=await downloadBundledModel(model(),{...options,onProgress:n=>progress.push(n),fetchImpl:async(url,init)=>{
    requests.push(url);assert.equal(init.headers,undefined);assert.equal(init.redirect,'error');
    if(requests.length===2)assert.deepEqual(progress,[2]);
    return new Response(new Uint8Array(requests.length===1?[1,2]:[3,4,5,6]));
  }});
  assert.deepEqual([...new Uint8Array(result)],[1,2,3,4,5,6]);
  assert.deepEqual(progress,[2,6]);assert.equal(requests.length,2);
});

test('short or oversized chunk streams stop before the next chunk',async()=>{
  for(const bytes of [[1],[1,2,3]]){
    let requests=0;
    await assert.rejects(downloadBundledModel(model(),{...options,fetchImpl:async()=>{
      requests++;return new Response(new Uint8Array(bytes));
    }}),/incomplete|exceeds expected size/);
    assert.equal(requests,1);
  }
});

test('oversized advertised content is canceled before consuming the stream',async()=>{
  let canceled=false;
  const response=new Response(new ReadableStream({cancel(){canceled=true;}}),{headers:{'content-length':'9'}});
  await assert.rejects(downloadBundledModel(model(),{...options,fetchImpl:async()=>response}),/exceeds expected size/);
  assert.equal(canceled,true);
});

test('inventory fetch is bounded and validates the parsed manifest',async()=>{
  const result=await loadBundledLibrary({...options,fetchImpl:async(url,init)=>{
    assert.equal(url.href,'https://studio.example/studio/library/index.json');assert.equal(init.redirect,'error');
    return Response.json([model()]);
  }});
  assert.equal(result.length,1);
  await assert.rejects(loadBundledLibrary({...options,fetchImpl:async()=>new Response(new Uint8Array(1024*1024+1))}),/exceeds expected size/);
});
