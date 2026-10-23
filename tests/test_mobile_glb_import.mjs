import test from 'node:test';
import assert from 'node:assert/strict';
import {imageDimensions,mobileGeometryBudget,prepareMobileImages,mobileGLBPlugin} from '../app/studio/web/mobile-glb-import.js';

function png(width=8192,height=8192){
  const bytes=new Uint8Array(24);bytes.set([137,80,78,71,13,10,26,10]);
  bytes.set([73,72,68,82],12);const view=new DataView(bytes.buffer);view.setUint32(16,width);view.setUint32(20,height);return bytes;
}
const fixture=()=>{
  const bytes=new Uint8Array(48);bytes.set(png());bytes.set(png(8192,4096),24);
  return {buffer:bytes.buffer,binaryOffset:0,document:{buffers:[{byteLength:48}],bufferViews:[{buffer:0,byteOffset:0,byteLength:24},{buffer:0,byteOffset:24,byteLength:24}],images:[{bufferView:0,mimeType:'image/png'},{bufferView:1,mimeType:'image/png'}],textures:[{source:0},{source:1}],materials:[{name:'Original',pbrMetallicRoughness:{baseColorTexture:{index:0}},normalTexture:{index:1}}]}};
};

test('image dimensions are read without decoding an 8K PNG',()=>{
  assert.deepEqual(imageDimensions(png()),{width:8192,height:8192});
  assert.throws(()=>imageDimensions(new Uint8Array(8)),/image format/);
});

test('JPEG and WebP dimensions are inspected without pixel decoding',()=>{
  const jpeg=new Uint8Array([255,216,255,192,0,11,8,16,0,32,0,1,1,17,0,255,217]);
  assert.deepEqual(imageDimensions(jpeg),{width:8192,height:4096});
  const webp=new Uint8Array(30);
  for(const [offset,text] of [[0,'RIFF'],[8,'WEBP'],[12,'VP8X']])for(let i=0;i<text.length;i++)webp[offset+i]=text.charCodeAt(i);
  webp[24]=255;webp[25]=31;webp[27]=255;webp[28]=15;
  assert.deepEqual(imageDimensions(webp),{width:8192,height:4096});
});

test('Cammy-sized geometry fits while oversized decoded accessor allocations are blocked',()=>{
  const document={accessors:[{count:1002001,type:'VEC3',componentType:5126},{count:1002001,type:'VEC3',componentType:5126},{count:1002001,type:'VEC2',componentType:5126},{count:6000000,type:'SCALAR',componentType:5125}],meshes:[{primitives:[{attributes:{POSITION:0,NORMAL:1,TEXCOORD_0:2},indices:3}]}]};
  assert.equal(mobileGeometryBudget(document).triangles,2000000);
  assert.throws(()=>mobileGeometryBudget({...document,accessors:[{count:20000000,type:'VEC4',componentType:5126}]}),/phone.*budget/i);
});

test('overlapping buffer views cannot bypass the phone allocation budget',()=>{
  const document={bufferViews:[{byteLength:70*1024*1024},{byteLength:70*1024*1024}]};
  assert.throws(()=>mobileGeometryBudget(document),/phone.*budget/i);
});

test('GPU instancing is rejected before it can bypass the phone scene budget',()=>{
  const document={accessors:[{count:1000000,type:'VEC3',componentType:5126}],nodes:[{mesh:0,extensions:{EXT_mesh_gpu_instancing:{attributes:{TRANSLATION:0}}}}]};
  assert.throws(()=>mobileGeometryBudget(document),/instanc/i);
});

test('embedded 8K images decode sequentially directly into bounded bitmaps',async()=>{
  const container=fixture();let active=0,peak=0;const calls=[];
  const result=await prepareMobileImages(container,{decode:async(blob,options)=>{
    active++;peak=Math.max(peak,active);calls.push(options);await new Promise(resolve=>setImmediate(resolve));active--;
    return {width:options.resizeWidth,height:options.resizeHeight,close(){}};
  }});
  assert.equal(peak,1);assert.equal(result.images.size,2);
  assert.deepEqual(calls.map(x=>[x.resizeWidth,x.resizeHeight]),[[512,512],[512,256]]);
  assert.ok(calls.every(x=>x.premultiplyAlpha==='none'&&x.colorSpaceConversion==='none'));
  assert.equal(result.reducedImages,2);
  assert.equal(container.document.materials[0].normalTexture.index,1);
});

test('unsupported resizing fails safely and closes images rather than retaining 8K results',async()=>{
  let closed=0;
  await assert.rejects(prepareMobileImages(fixture(),{decode:async()=>({width:8192,height:8192,close(){closed++;}})}),/resize/i);
  assert.equal(closed,1);
});

test('a later decode failure closes earlier prepared images',async()=>{
  let calls=0,closed=0;
  await assert.rejects(prepareMobileImages(fixture(),{decode:async()=>{
    if(++calls===2)throw Error('decode failed');return {width:512,height:512,close(){closed++;}};
  }}),/decode failed/);
  assert.equal(closed,1);
});

test('an excessive source resolution is rejected before decoding',async()=>{
  const container=fixture();new Uint8Array(container.buffer).set(png(32768,32768));let called=false;
  await assert.rejects(prepareMobileImages(container,{decode:async()=>{called=true;}}),/resolution/i);
  assert.equal(called,false);
});

test('invalid embedded image ranges are rejected without invoking the decoder',async()=>{
  const container=fixture();container.document.bufferViews[0].byteLength=1000;let called=false;
  await assert.rejects(prepareMobileImages(container,{decode:async()=>{called=true;}}),/range/);
  assert.equal(called,false);
});

test('plugin serves bounded images and embedded views without the original loader',async()=>{
  const container=fixture();const prepared=await prepareMobileImages(container,{decode:async(blob,options)=>({width:options.resizeWidth,height:options.resizeHeight,close(){}})});
  const parser={sourceCache:{}};
  class Texture{constructor(image){this.image=image;this.userData={};}}
  const plugin=mobileGLBPlugin(container,prepared,{Texture})(parser);
  await plugin.beforeRoot();
  const texture=await parser.sourceCache[0];assert.equal(texture.image.width,512);
  assert.deepEqual(new Uint8Array(await plugin.loadBufferView(1)),png(8192,4096));
});

test('optional meshopt uses its embedded fallback without the binary loader extension',async()=>{
  const container=fixture();
  container.document.extensionsUsed=['EXT_meshopt_compression'];
  container.document.bufferViews[0].extensions={EXT_meshopt_compression:{buffer:0,byteLength:8},OTHER_extension:{}};
  const plugin=mobileGLBPlugin(container,{images:new Map()},{})({sourceCache:{}});
  await plugin.beforeRoot();
  assert.equal(container.document.bufferViews[0].extensions.EXT_meshopt_compression,undefined);
  assert.deepEqual(container.document.bufferViews[0].extensions.OTHER_extension,{});
  assert.deepEqual(new Uint8Array(await plugin.loadBufferView(0)),png());
});

test('unused prepared bitmaps close after scene ownership is established',async()=>{
  const closed=[];
  const prepared=await prepareMobileImages(fixture(),{decode:async(blob,options)=>{
    const index=closed.length;closed.push(false);
    return {width:options.resizeWidth,height:options.resizeHeight,close(){closed[index]=true;}};
  }});
  const retained=prepared.images.get(0);
  prepared.retain(new Set([retained]));
  assert.deepEqual(closed,[false,true]);assert.equal(prepared.images.size,1);
  prepared.dispose();assert.deepEqual(closed,[true,true]);
});
