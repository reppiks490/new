import * as THREE from 'three';

// One Loop subdivision step, keeping UV seams as triangle-corner data.
// Fitting uses the authored cage; this smooths its displayed/exported surface.
export function smoothSurface(source,cornerUV){
  const p=source.attributes.position.array,idx=source.index.array,count=p.length/3;
  const neighbors=Array.from({length:count},()=>new Set()),edges=new Map();
  for(let f=0;f<idx.length;f+=3){
    const face=[idx[f],idx[f+1],idx[f+2]];
    for(let k=0;k<3;k++){
      const a=face[k],b=face[(k+1)%3],opposite=face[(k+2)%3],key=a<b?`${a}:${b}`:`${b}:${a}`;
      neighbors[a].add(b);neighbors[b].add(a);
      let edge=edges.get(key);
      if(!edge){edge={a,b,opposites:[],id:count+edges.size};edges.set(key,edge);}
      edge.opposites.push(opposite);
    }
  }
  const boundary=Array.from({length:count},()=>[]);
  for(const e of edges.values())if(e.opposites.length===1){boundary[e.a].push(e.b);boundary[e.b].push(e.a);}
  function interpolate(attribute){
    const input=attribute.array,size=attribute.itemSize,result=new Float32Array((count+edges.size)*size);
    for(let i=0;i<count;i++){
      const ring=[...neighbors[i]],border=boundary[i],n=ring.length;
      for(let axis=0;axis<size;axis++){
        if(border.length===2)result[i*size+axis]=input[i*size+axis]*.75+(input[border[0]*size+axis]+input[border[1]*size+axis])*.125;
        else if(n&&border.length===0){const beta=n===3?3/16:3/(8*n);result[i*size+axis]=input[i*size+axis]*(1-n*beta)+ring.reduce((sum,j)=>sum+input[j*size+axis],0)*beta;}
        else result[i*size+axis]=input[i*size+axis];
      }
    }
    for(const e of edges.values())for(let axis=0;axis<size;axis++){
      const ends=input[e.a*size+axis]+input[e.b*size+axis];
      result[e.id*size+axis]=e.opposites.length===2?ends*.375+(input[e.opposites[0]*size+axis]+input[e.opposites[1]*size+axis])*.125:ends*.5;
    }
    return new THREE.BufferAttribute(result,size);
  }
  const faces=[],uv=[];
  const edgeId=(a,b)=>edges.get(a<b?`${a}:${b}`:`${b}:${a}`).id;
  for(let f=0;f<idx.length;f+=3){
    const a=idx[f],b=idx[f+1],c=idx[f+2],ab=edgeId(a,b),bc=edgeId(b,c),ca=edgeId(c,a);
    faces.push(a,ab,ca,ab,b,bc,ca,bc,c,ab,bc,ca);
    if(cornerUV){
      const A=cornerUV.slice(f*2,f*2+2),B=cornerUV.slice(f*2+2,f*2+4),C=cornerUV.slice(f*2+4,f*2+6);
      const AB=A.map((v,k)=>(v+B[k])/2),BC=B.map((v,k)=>(v+C[k])/2),CA=C.map((v,k)=>(v+A[k])/2);
      uv.push(...A,...AB,...CA,...AB,...B,...BC,...CA,...BC,...C,...AB,...BC,...CA);
    }
  }
  const g=new THREE.BufferGeometry();g.setAttribute('position',interpolate(source.attributes.position));
  if(source.attributes.color)g.setAttribute('color',interpolate(source.attributes.color));
  g.setIndex(faces);g.computeVertexNormals();const out=g.toNonIndexed();g.dispose();
  if(cornerUV)out.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));
  return out;
}
