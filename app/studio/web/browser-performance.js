// Touch devices and small browser windows need bounded graphics allocations.
// Do not restore an unknown-size saved GLB automatically on these devices.
export function browserPerformanceProfile(environment=globalThis){
  const limited=Boolean(environment.matchMedia?.('(pointer: coarse)').matches||environment.matchMedia?.('(max-width: 760px)').matches);
  return {
    deferStartupModel:limited,
    pixelRatio:limited?1:Math.min(Number(environment.devicePixelRatio)||1,2),
    antialias:!limited,shadows:!limited,preserveDrawingBuffer:!limited,
    maxTextureSize:limited?512:Infinity,
  };
}

export function limitBrowserTexture(texture,maxEdge,documentRef=globalThis.document){
  const image=texture.image,width=image?.naturalWidth||image?.width,height=image?.naturalHeight||image?.height;
  if(!width||!height||Math.max(width,height)<=maxEdge)return texture;
  const scale=maxEdge/Math.max(width,height),canvas=documentRef.createElement('canvas');
  canvas.width=Math.max(1,Math.round(width*scale));canvas.height=Math.max(1,Math.round(height*scale));
  const context=canvas.getContext('2d');
  if(!context)throw Error('Texture preparation is unavailable in this browser.');
  context.drawImage(image,0,0,canvas.width,canvas.height);
  texture.image=canvas;texture.needsUpdate=true;
  image.close?.();
  return texture;
}
