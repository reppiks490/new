import * as THREE from 'three';
import {smoothSurface} from './subdivide.js';
import {browserPerformanceProfile,limitBrowserTexture} from './browser-performance.js';

// Authored MakeHuman accessories are bound to the original helper vertices.
// Fit them after morphing, rather than stretching an object-space bounding box.
const library={assets:[],textures:{}};
const cache=new Map();
const base='/studio/data/quality-assets/';

export async function loadAvatarAssets(){
  const response=await fetch(base+'index.json');
  if(!response.ok)throw Error('Character finish assets could not be loaded');
  const index=await response.json();
  library.assets=await Promise.all(index.assets.map(async entry=>{
    const r=await fetch(base+entry.file);
    if(!r.ok)throw Error(`${entry.label} mesh could not be loaded`);
    return {...await r.json(),...entry};
  }));
  const paths=new Set(Object.values(index.textures||{}));
  for(const a of library.assets)for(const key of ['diffuse','normal'])if(a.material?.[key])paths.add(a.material[key]);
  const loader=new THREE.TextureLoader();
  const profile=browserPerformanceProfile();
  const loadTexture=async path=>{
    const texture=await loader.loadAsync(base+path);
    limitBrowserTexture(texture,profile.maxTextureSize);
    texture.colorSpace=path.includes('normal')?THREE.NoColorSpace:THREE.SRGBColorSpace;
    texture.anisotropy=4;texture.userData.sharedAvatarTexture=true;
    cache.set(path,texture);
  };
  // Decode one full-size source at a time, then retain only its small canvas.
  if(Number.isFinite(profile.maxTextureSize))for(const path of paths)await loadTexture(path);
  else await Promise.all([...paths].map(loadTexture));
  library.textures=index.textures||{};
  return library;
}

export function skinTexture(baseType){return cache.get(library.textures['skin_'+baseType]);}
export function avatarOptions(kind){return library.assets.filter(a=>a.kind===kind);}
export function avatarAsset(id){return library.assets.find(a=>a.id===id);}

export function fittedGeometry(asset,body){
  const p=new Float32Array(asset.bindings.length*3);
  const scale=[1,1,1];
  for(const [axis,key] of ['x','y','z'].entries()){
    const s=asset.scales?.[key];
    if(s)scale[axis]=Math.abs(body[s[0]*3+axis]-body[s[1]*3+axis])*10/s[2];
  }
  for(let i=0;i<asset.bindings.length;i++){
    const b=asset.bindings[i];
    for(let axis=0;axis<3;axis++)p[i*3+axis]=body[b[0]*3+axis]*b[3]+body[b[1]*3+axis]*b[4]+body[b[2]*3+axis]*b[5]+b[6+axis]*scale[axis]/10;
  }
  const source=new THREE.BufferGeometry();source.setAttribute('position',new THREE.BufferAttribute(p,3));source.setIndex(asset.indices);source.computeVertexNormals();
  const uv=new Float32Array(asset.uv_indices.length*2);
  asset.uv_indices.forEach((id,i)=>{uv[i*2]=asset.uvs[id][0];uv[i*2+1]=asset.uvs[id][1];});
  const geometry=asset.kind==='lashes'?source.toNonIndexed():smoothSurface(source,uv);source.dispose();
  if(asset.kind==='lashes')geometry.setAttribute('uv',new THREE.BufferAttribute(uv,2));
  return geometry;
}

export function addFittedAsset(group,asset,positions){
  const hair=asset.kind==='hair'||asset.kind==='lashes';
  const material=new THREE.MeshPhysicalMaterial({
    color:asset.material.color||'#ffffff',map:cache.get(asset.material.diffuse),
    normalMap:cache.get(asset.material.normal),normalScale:new THREE.Vector2(.55,.55),
    side:THREE.DoubleSide,roughness:hair?.56:.83,metalness:0,
    specularIntensity:hair?.3:.2,alphaTest:asset.material.alpha?.45:0,
    sheen:hair?.2:.45,sheenRoughness:.7,sheenColor:new THREE.Color('#867b6d'),
  });
  const mesh=new THREE.Mesh(fittedGeometry(asset,positions),material);
  mesh.name=asset.id;mesh.userData={source:asset.source,license:asset.license,fit:'MakeHuman helper vertex binding',rigged:false};group.add(mesh);return mesh;
}

export function visibleBodyIndices(indices,assets){
  const hidden=new Set(assets.flatMap(a=>a?.hidden_vertices||[]));
  if(!hidden.size)return {indices,triangleOffsets:null};
  const kept=[],triangleOffsets=[];
  for(let i=0;i<indices.length;i+=3){
    if([indices[i],indices[i+1],indices[i+2]].every(v=>hidden.has(v)))continue;
    kept.push(indices[i],indices[i+1],indices[i+2]);triangleOffsets.push(i,i+1,i+2);
  }
  return {indices:kept,triangleOffsets};
}
