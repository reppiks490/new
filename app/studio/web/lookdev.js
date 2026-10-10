import * as THREE from 'three';

// Browser look development. These are explicit surface approximations, not
// claims of scanned textures or physical skin scattering.
export function skinMaterial(map){
  return new THREE.MeshPhysicalMaterial({vertexColors:true,roughness:.68,
    map,metalness:0,specularIntensity:.28,clearcoat:0,side:THREE.DoubleSide});
}

export function fabricMaterial(color){
  return new THREE.MeshPhysicalMaterial({color,roughness:.86,metalness:0,
    sheen:.55,sheenRoughness:.85,sheenColor:new THREE.Color(color).lerp(new THREE.Color('#d9d2ca'),.2),
    specularIntensity:.16,side:THREE.DoubleSide});
}

export function applySkinColor(geometry,data,state,textured=false){
  const p=geometry.attributes.position.array,base=new THREE.Color(state.skin),colors=new Float32Array(p.length);
  if(textured){const neutral=new THREE.Color('#b77f60');base.r=Math.min(2,base.r/neutral.r);base.g=Math.min(2,base.g/neutral.g);base.b=Math.min(2,base.b/neutral.b);}
  for(let i=0;i<p.length;i+=3){
    const subtle=1+Math.sin(p[i]*71+p[i+1]*43+p[i+2]*59)*.007;
    colors[i]=base.r*subtle;colors[i+1]=base.g*subtle;colors[i+2]=base.b*subtle;
  }
  const tint=new THREE.Color('#a45455');
  if(textured){geometry.setAttribute('color',new THREE.BufferAttribute(colors,3));return;}
  for(const id of ['mouth-upperlip-volume','mouth-lowerlip-volume']){
    const target=data.controls.find(c=>c.id===id)?.positive||[];
    let max=0;for(const [,x,y,z] of target)max=Math.max(max,Math.hypot(x,y,z));
    if(!max)continue;
    for(const [i,x,y,z] of target){const w=Math.min(.57,Math.hypot(x,y,z)/max*.57);colors[i*3]=colors[i*3]*(1-w)+tint.r*w;colors[i*3+1]=colors[i*3+1]*(1-w)+tint.g*w;colors[i*3+2]=colors[i*3+2]*(1-w)+tint.b*w;}
  }
  geometry.setAttribute('color',new THREE.BufferAttribute(colors,3));
}

// Give a sampled garment boundary a finished edge and actual thickness.
// Smooth only edge vertices, then build a sidewall between outer/inner rings.
// Garment topology remains a surface template; this is not cloth simulation.
export function finishGarment(source,indices,offset=.004){
  const p=source.attributes.position.array,n=source.attributes.normal.array;
  const positions=new Float32Array(p.length);
  for(let i=0;i<p.length;i++)positions[i]=p[i]+n[i]*offset;
  const edges=new Map();
  for(let k=0;k<indices.length;k+=3){
    const face=indices.slice(k,k+3);
    for(let j=0;j<3;j++){
      const a=face[j],b=face[(j+1)%3],key=a<b?`${a}:${b}`:`${b}:${a}`;
      const e=edges.get(key);if(e)e.count++;else edges.set(key,{a,b,count:1});
    }
  }
  const boundary=[...edges.values()].filter(e=>e.count===1),adjacent=new Map();
  for(const {a,b} of boundary){if(!adjacent.has(a))adjacent.set(a,[]);if(!adjacent.has(b))adjacent.set(b,[]);adjacent.get(a).push(b);adjacent.get(b).push(a);}
  for(let pass=0;pass<3;pass++){
    const before=positions.slice();
    for(const [i,neighbors] of adjacent){if(neighbors.length!==2)continue;for(let axis=0;axis<3;axis++)positions[i*3+axis]=before[i*3+axis]*.6+(before[neighbors[0]*3+axis]+before[neighbors[1]*3+axis])*.2;}
  }
  const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.BufferAttribute(positions,3));g.setIndex(indices);g.computeVertexNormals();
  const walls=[];
  for(const {a,b} of boundary){
    const va=new THREE.Vector3().fromArray(positions,a*3),vb=new THREE.Vector3().fromArray(positions,b*3);
    const ia=va.clone().addScaledVector(new THREE.Vector3().fromArray(n,a*3),-.0028),ib=vb.clone().addScaledVector(new THREE.Vector3().fromArray(n,b*3),-.0028);
    for(const point of [va,vb,ib,va,ib,ia])walls.push(point.x,point.y,point.z);
  }
  const edge=new THREE.BufferGeometry();edge.setAttribute('position',new THREE.Float32BufferAttribute(walls,3));edge.computeVertexNormals();
  return {surface:g,edge};
}

export function eyeMaterial(color){
  return new THREE.MeshPhysicalMaterial({color,roughness:.16,metalness:0,specularIntensity:.7,
    clearcoat:.4,clearcoatRoughness:.1});
}

export function detailedIris(color,radius){
  const canvas=document.createElement('canvas');canvas.width=canvas.height=256;
  const ctx=canvas.getContext('2d'),center=128,outer=124;
  const tone=new THREE.Color(color),rgb=[tone.r,tone.g,tone.b].map(v=>Math.round(THREE.MathUtils.clamp(v,0,1)*255));
  const iris=ctx.createRadialGradient(center,center,23,center,center,outer);
  iris.addColorStop(0,'#322b20');iris.addColorStop(.2,`rgb(${rgb.map(v=>Math.min(255,v*1.8)).join(',')})`);
  iris.addColorStop(.68,color);iris.addColorStop(.9,'#273b3d');iris.addColorStop(1,'#101e25');
  ctx.fillStyle=iris;ctx.fillRect(0,0,256,256);
  let seed=1927;const random=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/4294967296;};
  for(let i=0;i<600;i++){
    const a=random()*Math.PI*2,r0=28+random()*18,r1=88+random()*30;
    ctx.strokeStyle=i%3?`rgba(8,21,28,${.05+random()*.18})`:`rgba(192,171,119,${.1+random()*.22})`;
    ctx.lineWidth=.4+random()*1.4;ctx.beginPath();ctx.moveTo(center+Math.cos(a)*r0,center+Math.sin(a)*r0);
    ctx.quadraticCurveTo(center+Math.cos(a+.03)*70,center+Math.sin(a+.03)*70,center+Math.cos(a)*r1,center+Math.sin(a)*r1);ctx.stroke();
  }
  ctx.fillStyle='#030608';ctx.beginPath();ctx.arc(center,center,29,0,Math.PI*2);ctx.fill();
  const map=new THREE.CanvasTexture(canvas);map.colorSpace=THREE.SRGBColorSpace;
  const mesh=new THREE.Mesh(new THREE.CircleGeometry(radius,48),new THREE.MeshPhysicalMaterial({map,roughness:.2,specularIntensity:.65,clearcoat:.7,clearcoatRoughness:.08}));
  return mesh;
}

function taperedTube(points,radius){
  const curve=new THREE.CatmullRomCurve3(points),segments=32,radial=8;
  const geometry=new THREE.TubeGeometry(curve,segments,radius,radial,false);
  const p=geometry.attributes.position;
  for(let ring=0;ring<=segments;ring++){
    const t=ring/segments,center=curve.getPointAt(t),taper=.12+.88*Math.pow(Math.sin(Math.PI*t),.45);
    for(let j=0;j<=radial;j++){
      const i=ring*(radial+1)+j,v=new THREE.Vector3().fromBufferAttribute(p,i).sub(center).multiplyScalar(taper).add(center);
      p.setXYZ(i,v.x,v.y,v.z);
    }
  }
  geometry.computeVertexNormals();return geometry;
}

export function addBrows(group,skin,eyes,color='#493127'){
  skin.updateMatrixWorld(true);
  const ray=new THREE.Raycaster(),direction=new THREE.Vector3(0,0,-1);
  for(const {side,center,radius} of eyes){
    const sign=side==='l'?1:-1,points=[];
    for(let i=0;i<9;i++){
      const t=i/8,x=center[0]+sign*radius*(-.8+t*2.3),
        y=center[1]+radius*(1.55+Math.sin(t*Math.PI)*.32-t*.38);
      ray.set(new THREE.Vector3(x,y,center[2]+.25),direction);
      const hit=ray.intersectObject(skin,false)[0];
      if(hit)points.push(hit.point.clone().addScaledVector(hit.face.normal,.001));
    }
    if(points.length<4)continue;
    const brow=new THREE.Mesh(taperedTube(points,radius*.14),
      new THREE.MeshStandardMaterial({color,roughness:.85}));
    brow.name=`fitted_brow_${side}`;group.add(brow);
  }
}
