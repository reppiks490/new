// Private mobile MP4 preview gate.
//
// Existing Studio bearer-authenticated fetch remains the sole network owner.
// The caller provides a function that returns a Fetch Response (not an eagerly
// allocated Blob). This module enforces bounded memory, MIME, exact relative
// asset URL, verification metadata and object-URL lifecycle before playback.
//
// This is deliberately NOT the full-length 4K streaming solution. It refuses
// oversized media instead of loading an entire feature film onto an iPhone.

const PRIVATE_MP4=/^\/api\/video\/assets\/[a-f0-9]{32}\.mp4$/;
const DEFAULT_PREVIEW_LIMIT=80*1024*1024;

export function createCinematicMasterPreview({
  fetchMedia,
  maxBytes=DEFAULT_PREVIEW_LIMIT,
  createObjectURL=blob=>URL.createObjectURL(blob),
  revokeObjectURL=url=>URL.revokeObjectURL(url),
}={}){
  if(typeof fetchMedia!=='function')throw new TypeError('Authenticated media fetch required');
  if(!Number.isSafeInteger(maxBytes) || maxBytes<1){
    throw new RangeError('Invalid private preview size limit');
  }
  if(typeof createObjectURL!=='function'||typeof revokeObjectURL!=='function'){
    throw new TypeError('Object URL lifecycle functions required');
  }

  let epoch=0;
  let current=null;
  let activeReader=null;
  let activeController=null;
  function release(){
    if(current!==null){
      const stale=current;
      current=null;
      revokeObjectURL(stale);
    }
  }

  function close(){
    // Invalidate any pending read BEFORE closing the visible media.
    epoch++;
    const controller=activeController;
    activeController=null;
    if(controller)controller.abort();
    const reader=activeReader;
    activeReader=null;
    if(reader){
      try{Promise.resolve(reader.cancel()).catch(()=>{});}catch{}
    }
    release();
  }

  async function open(job){
    if(!job || job.status!=='succeeded' || job.verified!==true
      || typeof job.assetUrl!=='string' || !PRIVATE_MP4.test(job.assetUrl)){
      throw new Error('A verified private MP4 asset is required');
    }
    const path=job.assetUrl;
    close();
    const requestEpoch=epoch;
    const controller=new AbortController();
    activeController=controller;
    let response;
    try{
      response=await fetchMedia(path,{signal:controller.signal});
    }catch(error){
      if(requestEpoch!==epoch)return null;
      throw error;
    }
    if(requestEpoch!==epoch)return null;
    if(!response || response.ok!==true)throw new Error('Private MP4 request failed');
    const getHeader=response.headers?.get?.bind(response.headers);
    const mime=getHeader?.('content-type')?.split(';',1)[0]?.trim()?.toLowerCase();
    if(mime!=='video/mp4')throw new Error('Private asset is not an MP4 response');
    const reported=getHeader?.('content-length');
    if(typeof reported!=='string' || !/^\d+$/.test(reported)){
      throw new Error('Private MP4 response length is unavailable');
    }
    const byteLength=Number(reported);
    if(!Number.isSafeInteger(byteLength) || byteLength<1){
      throw new Error('Invalid private MP4 content length');
    }
    if(byteLength>maxBytes)throw new Error('MP4 is too large for bounded mobile preview');
    let blob;
    // Prefer bounded incremental fetch streaming when the browser exposes it.
    // This also protects memory when a dishonest response claims a small size
    // but sends a much larger body.
    if(typeof response.body?.getReader==='function'){
      const reader=response.body.getReader();
      activeReader=reader;
      const chunks=[];
      let received=0;
      try{
        while(true){
          if(requestEpoch!==epoch)return null;
          const part=await reader.read();
          if(requestEpoch!==epoch)return null;
          if(part.done)break;
          if(!(part.value instanceof Uint8Array)){
            throw new TypeError('Invalid private MP4 byte stream');
          }
          received+=part.value.byteLength;
          if(received>maxBytes)throw new Error('MP4 is too large for bounded mobile preview');
          if(received>byteLength)throw new Error('Private MP4 content length mismatch');
          chunks.push(part.value);
        }
        if(received!==byteLength){
          throw new Error('Private MP4 content length mismatch');
        }
      }catch(error){
        try{await reader.cancel();}catch{}
        throw error;
      }finally{
        if(activeReader===reader)activeReader=null;
        try{reader.releaseLock?.();}catch{}
      }
      if(requestEpoch!==epoch)return null;
      blob=new Blob(chunks,{type:'video/mp4'});
    }else{
      // Legacy fallback is permitted only after the strict size header gate.
      // Modern browsers use the streamed and independently bounded path.
      if(typeof response.blob!=='function'){
        throw new TypeError('Invalid private MP4 response');
      }
      blob=await response.blob();
    }
    if(requestEpoch!==epoch)return null;
    if(!blob || typeof blob.size!=='number' || blob.size!==byteLength){
      throw new Error('Private MP4 content length mismatch');
    }
    if(blob.type && blob.type.split(';',1)[0].trim().toLowerCase()!=='video/mp4'){
      throw new Error('Private MP4 blob has an unexpected type');
    }
    const url=createObjectURL(blob);
    if(requestEpoch!==epoch){
      revokeObjectURL(url);
      return null;
    }
    current=url;
    activeController=null;
    return url;
  }

  return Object.freeze({open,close,currentUrl:()=>current});
}
