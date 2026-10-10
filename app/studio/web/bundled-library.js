const LIBRARY_ROOT='./studio/library/';
const MAX_MANIFEST_BYTES=1024*1024;
const MAX_CHUNK_BYTES=16*1024*1024;

function assetURL(value,origin){
  if(typeof value!=='string'||value.length>512)throw Error('Invalid bundled model URL');
  const url=new URL(value,origin);
  if(url.origin!==new URL(origin).origin||url.username||url.password||url.search||url.hash||
    !/\/studio\/library\/[a-zA-Z0-9_./-]+$/.test(url.pathname)||
    value.includes('\\')||value.split('/').some(part=>part==='.'||part==='..'))throw Error('Unsupported bundled model URL');
  return url.href;
}

export function validateBundledLibrary(records,{origin,maxBytes}){
  if(!Number.isSafeInteger(maxBytes)||maxBytes<1||!Array.isArray(records)||records.length>100)throw Error('Invalid bundled model inventory');
  const ids=new Set();
  return records.map(record=>{
    if(!record||typeof record!=='object'||typeof record.id!=='string'||!/^[-\w]{1,128}$/.test(record.id)||ids.has(record.id)||
      typeof record.name!=='string'||!record.name.length||record.name.length>256||
      typeof record.sha256!=='string'||!/^[0-9a-f]{64}$/i.test(record.sha256)||!Number.isSafeInteger(record.bytes)||record.bytes<1||record.bytes>maxBytes||
      !Array.isArray(record.chunks)||!record.chunks.length||record.chunks.length>256)throw Error('Invalid bundled model metadata');
    ids.add(record.id);
    let total=0;const urls=new Set();
    const chunks=record.chunks.map(chunk=>{
      if(!chunk||!Number.isSafeInteger(chunk.bytes)||chunk.bytes<1||chunk.bytes>MAX_CHUNK_BYTES)throw Error('Invalid bundled model chunk size');
      total+=chunk.bytes;if(total>record.bytes)throw Error('Bundled model chunks exceed source size');
      const url=assetURL(chunk.url,origin);
      if(urls.has(url))throw Error('Duplicate bundled model chunk');
      urls.add(url);return {url,bytes:chunk.bytes};
    });
    if(total!==record.bytes)throw Error('Bundled model chunks do not match source size');
    return {...record,chunks};
  });
}

async function readBounded(response,limit,onChunk){
  if(!response.ok||Number(response.headers.get('content-length'))>limit){
    await response.body?.cancel().catch(()=>{});
    throw Error(!response.ok?`Bundled library download failed (${response.status})`:'Bundled library response exceeds expected size');
  }
  if(!response.body){const value=new Uint8Array(await response.arrayBuffer());if(value.byteLength>limit)throw Error('Bundled library response exceeds expected size');onChunk(value);return value.byteLength;}
  const reader=response.body.getReader();let bytes=0;
  try{while(true){const {done,value}=await reader.read();if(done)break;bytes+=value.byteLength;if(bytes>limit)throw Error('Bundled library response exceeds expected size');onChunk(value);}}
  catch(error){await reader.cancel().catch(()=>{});throw error;}finally{reader.releaseLock();}
  return bytes;
}

export async function loadBundledLibrary({origin,maxBytes,fetchImpl=fetch}){
  const response=await fetchImpl(new URL(LIBRARY_ROOT+'index.json',origin),{signal:AbortSignal.timeout(30000),redirect:'error'});
  const buffer=new Uint8Array(MAX_MANIFEST_BYTES);let offset=0;
  await readBounded(response,MAX_MANIFEST_BYTES,value=>{buffer.set(value,offset);offset+=value.byteLength;});
  return validateBundledLibrary(JSON.parse(new TextDecoder().decode(buffer.subarray(0,offset))),{origin,maxBytes});
}

export async function downloadBundledModel(record,{origin,maxBytes,fetchImpl=fetch,onProgress=()=>{}}){
  const [model]=validateBundledLibrary([record],{origin,maxBytes});
  const buffer=new Uint8Array(model.bytes);let offset=0;
  for(const chunk of model.chunks){
    const response=await fetchImpl(chunk.url,{signal:AbortSignal.timeout(120000),redirect:'error'});
    const received=await readBounded(response,chunk.bytes,value=>{buffer.set(value,offset);offset+=value.byteLength;onProgress(offset,model.bytes);});
    if(received!==chunk.bytes)throw Error('Bundled model chunk is incomplete');
  }
  return buffer.buffer;
}
