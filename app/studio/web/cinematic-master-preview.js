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
    const response=await fetchMedia(path);
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
    if(typeof response.blob!=='function')throw new TypeError('Invalid private MP4 response');
    const blob=await response.blob();
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
    return url;
  }

  return Object.freeze({open,close,currentUrl:()=>current});
}
