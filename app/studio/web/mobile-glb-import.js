// Inspect compressed headers before decoding. An 8K image can occupy 256 MiB
// even when its PNG/JPEG file is small. Mobile previews never retain that size.
export function imageDimensions(bytes){
  const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength),text=(a,b)=>String.fromCharCode(...bytes.subarray(a,b));
  if(bytes.length>=24&&[137,80,78,71,13,10,26,10].every((v,i)=>bytes[i]===v)&&text(12,16)==='IHDR')return {width:view.getUint32(16),height:view.getUint32(20)};
  if(bytes.length>=4&&bytes[0]===255&&bytes[1]===216){
    let at=2;
    while(at+4<=bytes.length){
      if(bytes[at++]!==255)break;
      while(bytes[at]===255)at++;
      const marker=bytes[at++];
      if(marker===217||marker===218)break;
      if(marker===1||(marker>=208&&marker<=215))continue;
      if(at+2>bytes.length)break;
      const size=view.getUint16(at);
      if(size<2||at+size>bytes.length)break;
      if(marker>=192&&marker<=207&&![196,200,204].includes(marker)&&size>=7)return {width:view.getUint16(at+5),height:view.getUint16(at+3)};
      at+=size;
    }
  }
  if(bytes.length>=30&&text(0,4)==='RIFF'&&text(8,12)==='WEBP'){
    if(text(12,16)==='VP8X')return {width:1+bytes[24]+(bytes[25]<<8)+(bytes[26]<<16),height:1+bytes[27]+(bytes[28]<<8)+(bytes[29]<<16)};
    if(text(12,16)==='VP8L'&&bytes[20]===47){const bits=view.getUint32(21,true);return {width:1+(bits&16383),height:1+((bits>>>14)&16383)};}
    if(text(12,16)==='VP8 '&&bytes[23]===157&&bytes[24]===1&&bytes[25]===42)return {width:view.getUint16(26,true)&16383,height:view.getUint16(28,true)&16383};
  }
  throw Error('This image format cannot be inspected safely for a phone preview. Use PNG, JPEG or WebP textures.');
}

export function mobileGeometryBudget(document){
  const sizes={SCALAR:1,VEC2:2,VEC3:3,VEC4:4,MAT2:4,MAT3:9,MAT4:16},components={5120:1,5121:1,5122:2,5123:2,5125:4,5126:4};
  let viewBytes=0;
  for(const view of document.bufferViews||[]){
    if(!Number.isSafeInteger(view.byteLength)||view.byteLength<0)throw Error('Invalid phone buffer budget.');
    viewBytes+=view.byteLength;
    if(viewBytes>128*1024*1024)throw Error('This model exceeds the phone buffer budget. Make a lower-detail copy on a desktop before importing.');
  }
  if((document.nodes||[]).some(node=>node.extensions?.EXT_mesh_gpu_instancing))throw Error('GPU-instanced models need a desktop-prepared phone copy.');
  let decodedBytes=0;
  for(const accessor of document.accessors||[]){
    const size=sizes[accessor.type],component=components[accessor.componentType];
    if(!size||!component||!Number.isSafeInteger(accessor.count)||accessor.count<0)throw Error('Invalid phone geometry budget.');
    decodedBytes+=accessor.count*size*component;
    if(decodedBytes>96*1024*1024)throw Error('This model exceeds the phone geometry budget. Make a lower-detail copy on a desktop before importing.');
  }
  const counts=(document.meshes||[]).map(mesh=>(mesh.primitives||[]).reduce((sum,p)=>{
    const count=document.accessors?.[p.indices??p.attributes?.POSITION]?.count||0;
    return sum+((p.mode??4)===4?count/3:[5,6].includes(p.mode)?Math.max(0,count-2):0);
  },0));
  const nodes=(document.nodes||[]).filter(node=>node.mesh!==undefined);
  const triangles=nodes.length?nodes.reduce((sum,node)=>sum+(counts[node.mesh]||0),0):counts.reduce((sum,count)=>sum+count,0);
  if(triangles>2500000||(document.nodes?.length||0)>2048)throw Error('This model exceeds the phone scene budget. Make a lower-detail copy on a desktop before importing.');
  return {decodedBytes,triangles};
}

function embeddedView(container,index){
  const entry=container.document.bufferViews?.[index];
  if(!entry||entry.buffer!==0||container.document.buffers?.[0]?.uri)throw Error('Phone previews require embedded GLB resources.');
  const offset=container.binaryOffset+(entry.byteOffset||0);
  if(!Number.isSafeInteger(offset)||offset<0||!Number.isSafeInteger(entry.byteLength)||entry.byteLength<0||offset+entry.byteLength>container.buffer.byteLength)throw Error('Invalid embedded GLB range.');
  return new Uint8Array(container.buffer,offset,entry.byteLength);
}

function imageBytes(container,source){
  if(source.bufferView!==undefined)return embeddedView(container,source.bufferView);
  const match=/^data:image\/(?:png|jpeg|webp);base64,([A-Za-z0-9+/=]+)$/.exec(source.uri||'');
  if(!match)throw Error('Phone previews require embedded PNG, JPEG or WebP images.');
  const decoded=atob(match[1]);return Uint8Array.from(decoded,char=>char.charCodeAt(0));
}

export async function prepareMobileImages(container,{decode=globalThis.createImageBitmap?.bind(globalThis),maxEdge=512}={}){
  const images=new Map();let reducedImages=0;
  const dispose=()=>{for(const image of images.values())image.close?.();images.clear();};
  const retain=used=>{for(const [index,image] of images)if(!used.has(image)){image.close?.();images.delete(index);}};
  try{
    if((container.document.images?.length||0)>32)throw Error('This model exceeds the phone texture budget.');
    if(container.document.images?.length&&!decode)throw Error('This browser cannot resize model textures safely. Try a current Safari version or use a reduced model.');
    for(const [index,source] of (container.document.images||[]).entries()){
      const bytes=imageBytes(container,source),{width,height}=imageDimensions(bytes);
      if(!width||!height||width*height>8192*8192)throw Error('This texture resolution exceeds the phone decode limit. Reduce it on a desktop first.');
      const scale=Math.min(1,maxEdge/Math.max(width,height)),resizeWidth=Math.max(1,Math.round(width*scale)),resizeHeight=Math.max(1,Math.round(height*scale));
      // Decode sequentially, before geometry allocation, directly to small native
      // bitmaps. Resizing after GLTFLoader.parseAsync would be too late.
      const image=await decode(new Blob([bytes],{type:source.mimeType||'application/octet-stream'}),{resizeWidth,resizeHeight,resizeQuality:'high',imageOrientation:'none',premultiplyAlpha:'none',colorSpaceConversion:'none'});
      if(image.width!==resizeWidth||image.height!==resizeHeight){image.close?.();throw Error('This browser did not resize the texture safely. Use a reduced model instead.');}
      images.set(index,image);if(scale<1)reducedImages++;
    }
    return {images,reducedImages,maxEdge,dispose,retain};
  }catch(error){dispose();throw error;}
}

export function mobileGLBPlugin(container,prepared,THREE){
  return parser=>({
    name:'FORMA_mobile_resources',
    beforeRoot(){
      // Optional meshopt declares an ordinary uncompressed fallback view.
      // Bypass its loader extension, which otherwise requests a full BIN body.
      if(!(container.document.extensionsRequired||[]).includes('EXT_meshopt_compression'))for(const view of container.document.bufferViews||[])if(view.extensions)delete view.extensions.EXT_meshopt_compression;
      for(const [index,image] of prepared.images){
        const source=container.document.images[index],texture=new THREE.Texture(image);
        texture.needsUpdate=true;texture.userData={...source.extras,mimeType:source.mimeType};
        parser.sourceCache[index]=Promise.resolve(texture);
      }
    },
    loadBufferView(index){
      const entry=container.document.bufferViews?.[index];
      if(entry?.extensions?.EXT_meshopt_compression)return null;
      const bytes=embeddedView(container,index);
      return Promise.resolve(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength));
    },
  });
}
