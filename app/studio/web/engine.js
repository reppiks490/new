import * as THREE from 'three';
import {OrbitControls} from './vendor/OrbitControls.js';
import {GLTFLoader} from './vendor/GLTFLoader.js';
import {GLTFExporter} from './vendor/GLTFExporter.js';
import {applySkinColor,skinMaterial,fabricMaterial,finishGarment,eyeMaterial,addBrows,detailedIris} from './lookdev.js';
import {skinTexture,avatarAsset,addFittedAsset,visibleBodyIndices} from './avatar-assets.js';
import {smoothSurface} from './subdivide.js';
import {applyBodyEdits} from './body-edits.js';

export const MAX_GLB_BYTES=150*1024*1024;

function validateGLB(buffer){
  if(!(buffer instanceof ArrayBuffer)||buffer.byteLength<20||buffer.byteLength>MAX_GLB_BYTES)throw Error('Use a GLB file up to 150 MiB');
  const header=new DataView(buffer);
  if(header.getUint32(0,true)!==0x46546c67||header.getUint32(4,true)!==2||header.getUint32(8,true)!==buffer.byteLength)throw Error('Use a valid GLB 2.0 file');
  let offset=12,doc=null,binaryBytes=0;
  while(offset<buffer.byteLength){
    if(offset+8>buffer.byteLength)throw Error('Incomplete GLB chunk');
    const length=header.getUint32(offset,true),type=header.getUint32(offset+4,true);
    if(length%4||offset+8+length>buffer.byteLength)throw Error('Invalid GLB chunk bounds');
    if(offset===12){
      if(type!==0x4e4f534a||length>16*1024*1024)throw Error('Invalid or oversized GLB metadata');
      doc=JSON.parse(new TextDecoder().decode(new Uint8Array(buffer,offset+8,length)));
    }else if(type===0x004e4942)binaryBytes+=length;
    offset+=8+length;
  }
  if(!doc||doc.asset?.version!=='2.0')throw Error('Use a valid GLB 2.0 asset');
  for(const entry of [...(doc.images||[]),...(doc.buffers||[])])if(entry.uri&&!entry.uri.startsWith('data:'))throw Error('GLB external references are not supported');
  let totalBytes=0;
  for(const b of doc.buffers||[]){
    if(!Number.isSafeInteger(b.byteLength)||b.byteLength<0)throw Error('Invalid GLB buffer size');
    totalBytes+=b.byteLength;
    if(!b.uri&&b.byteLength>binaryBytes)throw Error('GLB buffer exceeds embedded binary data');
  }
  if(totalBytes>MAX_GLB_BYTES)throw Error('Decoded GLB buffers exceed 150 MiB');
  for(const b of doc.bufferViews||[]){
    const size=doc.buffers?.[b.buffer]?.byteLength,start=b.byteOffset??0;
    if(!Number.isSafeInteger(start)||start<0||!Number.isSafeInteger(b.byteLength)||b.byteLength<0||size===undefined||start+b.byteLength>size)throw Error('GLB buffer view is out of bounds');
  }
  for(const accessor of doc.accessors||[])if(!Number.isSafeInteger(accessor.count)||accessor.count<0||accessor.count>20000000)throw Error('Unsupported GLB accessor size');
}

function disposeObject(object){
  const geometries=new Set(),materials=new Set(),textures=new Set();
  object?.traverse(o=>{if(o.geometry)geometries.add(o.geometry);for(const m of [].concat(o.material||[]))materials.add(m);});
  for(const m of materials){for(const value of Object.values(m))if(value?.isTexture&&!value.userData.sharedAvatarTexture)textures.add(value);m.dispose();}
  for(const g of geometries)g.dispose();
  for(const t of textures){t.dispose();t.source?.data?.close?.();}
}

export class StudioView {
  constructor(canvas, onStats) {
    this.canvas=canvas;this.sculptSelection=null;this.sculptOperations=[];
    this.raycaster=new THREE.Raycaster();this.pointer=new THREE.Vector2();
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(38, 1, .01, 10000);
    this.renderer = new THREE.WebGLRenderer({canvas, antialias:true, alpha:true, preserveDrawingBuffer:true});
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    this.renderer.shadowMap.enabled=true;
    this.renderer.shadowMap.type=THREE.PCFSoftShadowMap;
    const environment=new THREE.Scene();environment.background=new THREE.Color('#535965');
    for(const [color,pos,scale] of [['#fff0dc',[-3,3,3],[2,3,1]],['#bfd5f3',[4,2,1],[1,4,2]],['#eee7e0',[0,5,-3],[3,1,2]]]){const panel=new THREE.Mesh(new THREE.BoxGeometry(...scale),new THREE.MeshBasicMaterial({color}));panel.position.set(...pos);environment.add(panel);}
    const pmrem=new THREE.PMREMGenerator(this.renderer);this.environmentMap=pmrem.fromScene(environment,.06);this.scene.environment=this.environmentMap.texture;this.scene.environmentIntensity=.4;pmrem.dispose();
    environment.traverse(o=>{o.geometry?.dispose();o.material?.dispose();});
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.addEventListener('change',()=>this.invalidate());
    this.controls.enableDamping = !matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.controls.target.set(0, .9, 0);
    this.camera.position.set(2.4, 1.35, 4);
    this.scene.add(new THREE.HemisphereLight(0xe1e7f0,0x424354,1.45));
    for(const [color,power,pos] of [[0xffe4cc,2.4,[2,3,4]],[0xc5d9ff,1,[-3,1.5,2]],[0xffedda,2,[1,2,-3]]]) {
      const light=new THREE.DirectionalLight(color,power); light.position.set(...pos); this.scene.add(light);
      if(!this.key){this.key=light;light.castShadow=true;light.shadow.mapSize.set(2048,2048);Object.assign(light.shadow.camera,{left:-2,right:2,top:2,bottom:-2,near:.1,far:15});light.shadow.normalBias=.004;light.shadow.bias=-.0002;}
    }
    this.floor=new THREE.Mesh(new THREE.PlaneGeometry(200,200),new THREE.ShadowMaterial({opacity:.22}));
    this.floor.rotation.x=-Math.PI/2;this.floor.receiveShadow=true;this.scene.add(this.floor);
    this.grid = new THREE.GridHelper(5,30,0x5b6b82,0x364558);
    this.grid.material.transparent=true;this.grid.material.opacity=.24;this.scene.add(this.grid);
    this.onStats=onStats;
    this.observer = new ResizeObserver(()=>this.resize());this.observer.observe(canvas.parentElement);
    this.resize();this.renderer.setAnimationLoop(()=>{this.controls.update();if(this.needsRender){this.needsRender=false;this.renderer.render(this.scene,this.camera);}});
    canvas.addEventListener('keydown',e=>{
      if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','-','=','f','F'].includes(e.key))return;
      e.preventDefault();if(e.key.toLowerCase()==='f')return this.frame();
      const offset=this.camera.position.clone().sub(this.controls.target),s=new THREE.Spherical().setFromVector3(offset);
      if(e.key==='ArrowLeft')s.theta-=.12;if(e.key==='ArrowRight')s.theta+=.12;
      if(e.key==='ArrowUp')s.phi-=.12;if(e.key==='ArrowDown')s.phi+=.12;
      if(e.key==='+'||e.key==='=')s.radius*=.9;if(e.key==='-')s.radius*=1.1;
      s.makeSafe();this.camera.position.copy(this.controls.target).add(new THREE.Vector3().setFromSpherical(s));this.controls.update();
    });
  }
  invalidate(){this.needsRender=true;}
  resize(){const {width,height}=this.renderer.domElement.parentElement.getBoundingClientRect();this.renderer.setSize(width,height,false);this.camera.aspect=width/Math.max(1,height);this.camera.updateProjectionMatrix();this.invalidate();}
  replace(object, reframe=false){
    if(this.object){this.scene.remove(this.object);disposeObject(this.object);}
    this.animations=[];this.morphControls=[];this.sculptSelection=null;this.sculptOperations=[];
    this.object=object;this.scene.add(object);
    this.setWire(this.wire||false);
    let triangles=0;object.traverse(o=>{if(o.isMesh){triangles+=(o.geometry.index?.count||o.geometry.attributes.position.count)/3;o.castShadow=true;o.receiveShadow=true;}});
    const bounds=new THREE.Box3().setFromObject(object);this.floor.position.y=bounds.min.y-.004;this.grid.position.y=bounds.min.y-.003;
    this.onStats(`${Math.round(triangles).toLocaleString()} triangles · ${new THREE.Box3().setFromObject(object).getSize(new THREE.Vector3()).y.toFixed(2)} m tall`);
    if(reframe)this.frame();
  }
  frame(){if(!this.object)return;const box=new THREE.Box3().setFromObject(this.object),center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3()),d=Math.max(size.x,size.y,size.z)*1.9;this.controls.target.copy(center);this.camera.position.copy(center).add(new THREE.Vector3(d*.28,d*.12,d));this.camera.far=Math.max(100,d*100);this.camera.updateProjectionMatrix();this.controls.update();this.grid.scale.setScalar(Math.max(1,size.x/4));this.grid.position.y=box.min.y-.006;this.floor.position.y=box.min.y-.008;}
  portrait(){if(!this.object)return;const box=new THREE.Box3().setFromObject(this.object),h=box.max.y-box.min.y,center=new THREE.Vector3((box.min.x+box.max.x)/2,box.max.y-h*.105,(box.min.z+box.max.z)/2);this.controls.target.copy(center);this.camera.position.copy(center).add(new THREE.Vector3(h*.08,h*.01,h*.55));this.controls.update();}
  angle(direction){if(!this.object)return;const center=this.controls.target,d=this.camera.position.distanceTo(center);this.camera.position.copy(center).add(new THREE.Vector3(...direction).multiplyScalar(d));this.controls.update();}
  setWire(value){this.wire=value;this.object?.traverse(o=>{for(const m of [].concat(o.material||[]))m.wireframe=value;});this.invalidate();}
  async export(){if(!this.object)throw Error('No model to export');return new GLTFExporter().parseAsync(this.object,{binary:true,animations:this.animations||[]});}
  async import(buffer){
    validateGLB(buffer);
    const gltf=await new GLTFLoader().parseAsync(buffer,'');
    try{
      let meshes=0;
      gltf.scene.traverse(o=>{
        if(!o.isMesh)return;meshes++;
        const positions=o.geometry.attributes.position;
        if(!positions||!positions.count)throw Error('Model contains an empty mesh');
        for(let i=0;i<positions.count;i++)for(const value of [positions.getX(i),positions.getY(i),positions.getZ(i)])if(!Number.isFinite(value)||Math.abs(value)>1e6)throw Error('Model contains invalid or unsupported vertex coordinates');
      });
      const bounds=new THREE.Box3().setFromObject(gltf.scene),size=bounds.getSize(new THREE.Vector3());
      if(!meshes||bounds.isEmpty()||![...bounds.min.toArray(),...bounds.max.toArray()].every(Number.isFinite)||Math.max(size.x,size.y,size.z)>1e6||Math.max(size.x,size.y,size.z)<1e-6)throw Error('Model has invalid or unsupported scene bounds');
      this.replace(gltf.scene,true);this.animations=gltf.animations||[];
      let meshIndex=0;
      gltf.scene.traverse(o=>{
        if(!o.isMesh)return;
        const id=meshIndex++;o.userData.formaMeshIndex=id;const names=Object.entries(o.morphTargetDictionary||{});
        for(let index=0;index<(o.morphTargetInfluences?.length||0);index++){
          const value=o.morphTargetInfluences[index];
          if(!Number.isFinite(value)||Math.abs(value)>10)continue;
          const label=names.find(([,i])=>i===index)?.[0]||`Target ${index+1}`;
          this.morphControls.push({id:`m${id}:${index}`,label,mesh:o.name||`Mesh ${id+1}`,object:o,index,initial:value,min:Math.min(0,value),max:Math.max(1,value)});
        }
      });
      return {animations:this.animations.length,morphs:this.morphControls.length};
    }catch(error){if(this.object!==gltf.scene)disposeObject(gltf.scene);throw error;}
  }
  getMorphControls(){return (this.morphControls||[]).map(({object,index,...control})=>({...control,value:object.morphTargetInfluences[index]}));}
  pickSurface(clientX,clientY){
    if(!this.object)throw Error('Open a model before sculpting');
    const rect=this.canvas.getBoundingClientRect();this.pointer.set((clientX-rect.left)/rect.width*2-1,-(clientY-rect.top)/rect.height*2+1);
    this.raycaster.setFromCamera(this.pointer,this.camera);
    const hit=this.raycaster.intersectObject(this.object,true).find(item=>item.object.isMesh&&item.face&&Number.isInteger(item.object.userData.formaMeshIndex)&&!item.object.geometry.morphAttributes?.position?.length);
    if(!hit)throw Error('Click a visible mesh without source shape keys.');
    const mesh=hit.object,geometry=mesh.geometry;
    if(geometry.morphAttributes?.position?.length)throw Error('This mesh already has shape keys. Use its source controls, or pick a separate mesh without them.');
    if(!geometry.boundingBox)geometry.computeBoundingBox();
    const size=geometry.boundingBox.getSize(new THREE.Vector3()),maxDimension=Math.max(size.x,size.y,size.z);
    if(!Number.isFinite(maxDimension)||maxDimension<=0)throw Error('This mesh has no usable sculpt bounds.');
    this.sculptSelection={mesh,meshIndex:mesh.userData.formaMeshIndex,center:mesh.worldToLocal(hit.point.clone()),normal:hit.face.normal.clone().normalize(),maxDimension};
    return {mesh:mesh.name||`Mesh ${this.sculptSelection.meshIndex+1}`,maxDimension};
  }
  sculptFromPrompt(prompt,radiusFraction=.12){
    if(!this.sculptSelection)throw Error('Pick an area on the model first.');
    if(typeof prompt!=='string'||prompt.length>500)throw Error('Keep the sculpt prompt under 500 characters.');
    // This brush only knows the picked surface patch. It has no anatomical
    // segmentation, bilateral pairing, or garment correspondence, so reject
    // prompts that claim to edit a body region instead of silently deforming
    // whichever point happened to be selected.
    if(/\b(?:breasts?|bust|chest|nipples?|glutes?|butt(?:ocks?)?|hips?|waist|abdomen|stomach|thighs?|legs?|calves?|arms?|shoulders?|neck|head|face)\b/i.test(prompt)){
      throw Error('No edit made. This imported mesh has no verified body-region map. Surface sculpt only moves the picked patch; it cannot precisely change breast size or another named body part. Open the editable character base for mapped body controls.');
    }
    const amountMatch=prompt.match(/([+-]?\d+(?:\.\d+)?)\s*%?/),worded=/\b(slightly|subtly|a little)\b/i.test(prompt)?15:/\b(much|drastically|a lot|significantly)\b/i.test(prompt)?60:30;
    let amount=amountMatch?Number(amountMatch[1]):worded;
    if(amount>20)throw Error('No edit made. Local sculpt is limited to 20% of the brush radius per pass. Large percentage prompts are not safe for a point-based brush.');
    if(/\b(smaller|reduce|reduc|decrease|less|shrink|flatten)\b/i.test(prompt)&&amount>0)amount=-amount;
    amount=Math.max(-100,Math.min(100,amount));
    if(!Number.isFinite(radiusFraction)||radiusFraction<.04||radiusFraction>.35)throw Error('Sculpt radius must be between 4% and 35% of the selected mesh.');
    const selection=this.sculptSelection,operation={meshIndex:selection.meshIndex,center:selection.center.toArray(),normal:selection.normal.toArray(),radius:selection.maxDimension*radiusFraction,amount:selection.maxDimension*radiusFraction*amount/100,label:`Sculpt ${this.sculptOperations.length+1}`};
    return this.applySculptOperation(operation);
  }
  applySculptOperation(operation){
    if(!this.object||!operation||!Number.isInteger(operation.meshIndex)||!Array.isArray(operation.center)||operation.center.length!==3||!Array.isArray(operation.normal)||operation.normal.length!==3||!Number.isFinite(operation.radius)||operation.radius<=0||!Number.isFinite(operation.amount)||Math.abs(operation.amount)>1e6)throw Error('Invalid sculpt operation.');
    if(this.sculptOperations.length>=100)throw Error('A model project can contain at most 100 sculpt edits.');
    const meshes=[];this.object.traverse(o=>{if(o.isMesh)meshes.push(o);});const mesh=meshes[operation.meshIndex];
    if(!mesh)throw Error('The sculpted mesh is not present in this source model.');
    let geometry=mesh.geometry;
    if(geometry.morphAttributes?.position?.length&&!mesh.userData.formaSculptGeometry)throw Error('Sculpt edits must target a mesh without source shape keys.');
    if(!mesh.userData.formaSculptGeometry){mesh.geometry=geometry=geometry.clone();mesh.userData.formaSculptGeometry=true;}
    const positions=geometry.attributes.position,delta=new Float32Array(positions.count*3),center=new THREE.Vector3(...operation.center),normal=new THREE.Vector3(...operation.normal).normalize(),r=operation.radius;
    let affected=0;
    for(let i=0;i<positions.count;i++){
      const dx=positions.getX(i)-center.x,dy=positions.getY(i)-center.y,dz=positions.getZ(i)-center.z,distance=Math.hypot(dx,dy,dz);
      if(distance>=r)continue;
      const t=distance/r,weight=1-t*t*(3-2*t),offset=operation.amount*weight;
      delta[i*3]=normal.x*offset;delta[i*3+1]=normal.y*offset;delta[i*3+2]=normal.z*offset;affected++;
    }
    if(!affected)throw Error('The selected brush radius did not reach any vertices. Increase its radius and pick again.');
    const attributes=geometry.morphAttributes.position||(geometry.morphAttributes.position=[]),index=attributes.length,shape=new THREE.Float32BufferAttribute(delta,3);shape.name=operation.label||`Sculpt ${this.sculptOperations.length+1}`;attributes.push(shape);geometry.morphTargetsRelative=true;
    const previous=mesh.morphTargetInfluences?.slice()||[];mesh.updateMorphTargets();for(let i=0;i<previous.length;i++)mesh.morphTargetInfluences[i]=previous[i];mesh.morphTargetInfluences[index]=1;
    const meshIndex=operation.meshIndex,id=`m${meshIndex}:${index}`;
    this.morphControls.push({id,label:shape.name,mesh:mesh.name||`Mesh ${meshIndex+1}`,object:mesh,index,initial:0,min:0,max:1});
    this.sculptOperations.push({meshIndex,center:[...operation.center],normal:[...operation.normal],radius:operation.radius,amount:operation.amount,label:shape.name});
    this.invalidate();return {id,label:shape.name,affected_vertices:affected};
  }
  getSculptOperations(){return this.sculptOperations.map(operation=>({...operation,center:[...operation.center],normal:[...operation.normal]}));}
  morphValues(){return Object.fromEntries(this.getMorphControls().map(c=>[c.id,c.value]));}
  setMorph(id,value){const c=this.morphControls?.find(item=>item.id===id);if(!c||!Number.isFinite(value)||value<c.min||value>c.max)throw Error('Invalid source morph setting');c.object.morphTargetInfluences[c.index]=value;this.invalidate();}
  applyMorphValues(values){for(const [id,value] of Object.entries(values)){const c=this.morphControls?.find(item=>item.id===id);if(!c||!Number.isFinite(value)||value<c.min||value>c.max)throw Error('Project morphs do not match this source model');}for(const [id,value] of Object.entries(values))this.setMorph(id,value);}
  resetMorphs(){for(const c of this.morphControls||[])c.object.morphTargetInfluences[c.index]=c.initial;this.invalidate();}
  snapshot(){this.renderer.render(this.scene,this.camera);return this.renderer.domElement.toDataURL('image/png');}
}

function material(hex, roughness=.62){return new THREE.MeshStandardMaterial({color:hex,roughness,metalness:0,side:THREE.DoubleSide});}
function addSphere(group,name,position,scale,color){const object=new THREE.Mesh(new THREE.SphereGeometry(1,20,12),material(color));object.name=name;object.position.set(...position);object.scale.set(...scale);group.add(object);return object;}

export function characterGeometry(data,state,catalog){
  const group=new THREE.Group();group.name='Forma_static_adult_character';
  const positions=new Float32Array(data.positions.flat());
  for(const target of data.bases[state.base])for(const [i,x,y,z] of target){positions[i*3]+=x/3;positions[i*3+1]+=y/3;positions[i*3+2]+=z/3;}
  for(const control of data.controls){const value=state.controls[control.id]||0;if(!value)continue;for(const [i,x,y,z] of control[value>0?'positive':'negative']){positions[i*3]+=x*Math.abs(value)/100;positions[i*3+1]+=y*Math.abs(value)/100;positions[i*3+2]+=z*Math.abs(value)/100;}}
  let bodyEditReports=[];
  if(state.body_edits?.length){if(!data.region_masks)throw Error('Region maps are unavailable for this character base.');const result=applyBodyEdits(positions,data,data.region_masks,state.body_edits);positions.set(result.positions);bodyEditReports=result.reports;}
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.BufferAttribute(positions,3));geometry.setIndex(data.indices);geometry.computeVertexNormals();
  const hair=avatarAsset(state.hair),authoredOutfit=avatarAsset(state.outfit),shoes=avatarAsset(state.shoes),lashes=avatarAsset('eyelashes01');
  const texture=state.skinTexture===false?null:skinTexture(state.base);
  applySkinColor(geometry,data,state,Boolean(texture));
  const visible=visibleBodyIndices(data.indices,[authoredOutfit,shoes]);
  const renderSource=geometry.clone();renderSource.setIndex(visible.indices);
  let skinUV;
  if(data.uvs&&data.uv_indices){
    const corners=visible.triangleOffsets||data.uv_indices.map((_,i)=>i),uv=new Float32Array(corners.length*2);
    for(let k=0;k<corners.length;k++){const pair=data.uvs[data.uv_indices[corners[k]]];uv[k*2]=pair[0];uv[k*2+1]=pair[1];}
    skinUV=uv;
  }
  const renderGeometry=smoothSurface(renderSource,skinUV);renderSource.dispose();
  const skin=new THREE.Mesh(renderGeometry,skinMaterial(texture));skin.name='MakeHuman_CC0_base_static';group.add(skin);
  const used=new Set(data.indices);let minY=Infinity,maxY=-Infinity;for(const i of used){minY=Math.min(minY,positions[i*3+1]);maxY=Math.max(maxY,positions[i*3+1]);}const h=maxY-minY;
  const item=catalog.find(x=>x.id===state.outfit)||catalog.find(x=>x.id==='bodysuit-001');
  const clothIndices=[],i=item.design,cut=i%10,layer=Math.floor(i/10),collar=.78+cut*.005,hem=.43+layer*.003;
  for(let k=0;k<data.indices.length;k+=3){
    const [a,b,c]=data.indices.slice(k,k+3);const cx=(positions[a*3]+positions[b*3]+positions[c*3])/3,cy=(positions[a*3+1]+positions[b*3+1]+positions[c*3+1])/3;
    const y=(cy-minY)/h,x=Math.abs(cx)/h,wave=Math.sin(cx/h*(10+cut))*.009;
    let selected=false;
    if(item.category==='fashion')selected=(x<.17&&y>hem+wave&&y<collar-x*(cut%3)*.2)||(y<.48+cut*.003&&y>.06+layer*.012);
    else if(item.category==='bodysuit')selected=y>.05+i*.002&&y<.81+(i%5)*.005;
    else if(item.category==='custom')selected=(x<.16&&y>.62+layer*.005&&y<collar)||(y>.40+cut*.003&&y<.53);
    else if(item.category==='lingerie')selected=(x<.16&&y>.63+cut*.0015&&y<.76+layer*.01)||(y>.43+cut*.003&&y<.54+layer*.007);
    else selected=(x<.14&&y>.68+cut*.002&&y<.75+layer*.008)||(y>.46+cut*.002&&y<.53+layer*.007);
    if(selected)clothIndices.push(a,b,c);
  }
  if(authoredOutfit)addFittedAsset(group,authoredOutfit,positions);
  else{
  const garment=finishGarment(geometry,clothIndices);
  const cloth=new THREE.Mesh(garment.surface,fabricMaterial(state.cloth));cloth.name=item.id+'_procedural_surface_shell';group.add(cloth);
  const edge=new THREE.Mesh(garment.edge,fabricMaterial(new THREE.Color(state.cloth).multiplyScalar(.7)));edge.name=item.id+'_finished_edges';group.add(edge);
  }
  const eyeFrames=[];
  for(const side of ['l','r']){
    const indices=data.eyes[side],center=[0,0,0];for(const j of indices)for(let axis=0;axis<3;axis++)center[axis]+=positions[j*3+axis]/indices.length;
    let radius=0;for(const j of indices)radius+=Math.hypot(...center.map((v,axis)=>positions[j*3+axis]-v))/indices.length;radius*=.83;
    eyeFrames.push({side,center,radius});
    addSphere(group,'eye_'+side,center,[radius,radius,radius],'#e2dfd4').material=eyeMaterial('#dfdbcf');
    const iris=detailedIris(state.iris||'#527c83',radius*.48);iris.name='iris_'+side;iris.position.set(center[0],center[1],center[2]+radius*1.01);group.add(iris);
  }
  if(!texture)addBrows(group,skin,eyeFrames);
  if(hair)addFittedAsset(group,hair,positions);
  if(shoes)addFittedAsset(group,shoes,positions);
  if(lashes)addFittedAsset(group,lashes,positions);
  const attachments=state.attachments||[];
  if(attachments.includes('horns'))for(const side of [-1,1]){const m=new THREE.Mesh(new THREE.ConeGeometry(h*.022,h*.14,18),material('#c7b49e'));m.position.set(side*h*.048,maxY+h*.055,0);m.rotation.z=-side*.25;m.name='horn_'+side;group.add(m);}
  if(attachments.includes('ears'))for(const side of [-1,1])addSphere(group,'fantasy_ear_'+side,[side*h*.077,maxY-h*.072,0],[h*.055,h*.013,h*.016],state.skin).rotation.z=side*.45;
  if(attachments.includes('earrings'))for(const side of [-1,1]){const m=new THREE.Mesh(new THREE.TorusGeometry(h*.014,h*.0025,10,28),new THREE.MeshStandardMaterial({color:'#e8bd6b',metalness:.9,roughness:.24}));m.position.set(side*h*.056,maxY-h*.095,h*.004);m.name='earring_'+side;group.add(m);}
  if(attachments.includes('tail')){const curve=new THREE.CatmullRomCurve3([new THREE.Vector3(0,minY+h*.48,-h*.055),new THREE.Vector3(0,minY+h*.32,-h*.23),new THREE.Vector3(.08,minY+h*.2,-h*.34)]);const m=new THREE.Mesh(new THREE.TubeGeometry(curve,25,h*.012,10,false),material(state.skin));m.name='static_tail';group.add(m);}
  if(attachments.includes('wings'))for(const side of [-1,1]){const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute([0,minY+h*.76,-.07,side*h*.6,minY+h*.9,-h*.16,side*h*.3,minY+h*.5,-h*.13],3));g.computeVertexNormals();const m=new THREE.Mesh(g,material(state.cloth,.85));m.name='static_wing_'+side;group.add(m);}
  geometry.dispose();
  group.userData={source:'MakeHuman hm08; see component asset credits',authored_controls:Object.keys(state.controls).filter(k=>state.controls[k]).length,rigged:false,garment_construction:authoredOutfit?'authored_mesh':'procedural_surface',extreme:state.extreme,body_edit_reports:bodyEditReports};return group;
}

export function terrainGeometry({seed=7,size=200,height=35,resolution=6}){
  const n=2**resolution,grid=new Float32Array((n+1)*(n+1));let s=seed|0;
  const random=()=>{s|=0;s=s+0x6D2B79F5|0;let t=Math.imul(s^s>>>15,1|s);t=t+Math.imul(t^t>>>7,61|t)^t;return ((t^t>>>14)>>>0)/4294967296;};
  const at=(x,y)=>y*(n+1)+x;grid[0]=random();grid[n]=random();grid[at(0,n)]=random();grid[at(n,n)]=random();
  let amplitude=.6;for(let step=n;step>1;step/=2){const half=step/2;for(let y=half;y<n;y+=step)for(let x=half;x<n;x+=step)grid[at(x,y)]=(grid[at(x-half,y-half)]+grid[at(x+half,y-half)]+grid[at(x-half,y+half)]+grid[at(x+half,y+half)])/4+(random()-.5)*amplitude;
    for(let y=0;y<=n;y+=half)for(let x=(y/half%2===0?half:0);x<=n;x+=step){let sum=0,count=0;for(const [dx,dy] of [[half,0],[-half,0],[0,half],[0,-half]])if(x+dx>=0&&x+dx<=n&&y+dy>=0&&y+dy<=n){sum+=grid[at(x+dx,y+dy)];count++;}grid[at(x,y)]=sum/count+(random()-.5)*amplitude;}amplitude*=.52;}
  let low=Infinity,high=-Infinity;for(const v of grid){low=Math.min(low,v);high=Math.max(high,v);}const p=[],colors=[],indices=[];
  for(let y=0;y<=n;y++)for(let x=0;x<=n;x++){const value=(grid[at(x,y)]-low)/(high-low||1);p.push((x/n-.5)*size,value*height,(y/n-.5)*size);const color=new THREE.Color(value<.18?'#557d95':value<.35?'#a2a07c':value<.7?'#526e57':value<.85?'#878884':'#d2d7d8');colors.push(color.r,color.g,color.b);if(x<n&&y<n){const a=at(x,y),b=a+1,c=a+n+1;indices.push(a,c,b,b,c,c+1);}}
  const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(p,3));g.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));g.setIndex(indices);g.computeVertexNormals();const m=new THREE.Mesh(g,new THREE.MeshStandardMaterial({vertexColors:true,roughness:.95,side:THREE.DoubleSide}));m.name='seeded_fractal_terrain';m.userData={seed,size,height,resolution};const group=new THREE.Group();group.add(m);return group;
}
