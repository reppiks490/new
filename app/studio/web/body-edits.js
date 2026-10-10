function support(data, ids){
  const controls=new Map(data.controls.map(control=>[control.id,control]));
  const result=new Set();
  for(const id of ids){
    const control=controls.get(id);
    if(!control)throw Error(`Region map references missing authored control: ${id}`);
    for(const side of ['positive','negative'])for(const row of control[side])result.add(Number(row[0]));
  }
  return result;
}

export function buildRegionMasks(positions,data,maskSpec){
  const regions=maskSpec.regions,masks={};
  for(const [name,config] of Object.entries(regions)){
    if(name==='waist')continue;
    masks[name]=support(data,config.authored_support_controls);
  }
  const waist=regions.waist,candidate=support(data,[waist.candidate_support_control]);
  const excluded=new Set(waist.exclude_regions.flatMap(region=>[...masks[region]]));
  masks.waist=new Set([...candidate].filter(index=>{
    const y=positions[index*3+1],x=positions[index*3];
    return !excluded.has(index)&&y>waist.vertical_bounds[0]&&y<waist.vertical_bounds[1]&&Math.abs(x)<waist.max_abs_x;
  }));
  if(!masks.waist.size)throw Error('The authored waist mask is empty for this base mesh.');
  return masks;
}

export function applyBodyEdits(sourcePositions,data,maskSpec,edits){
  if(!Array.isArray(edits)||edits.length>10)throw Error('At most 10 body edits are supported.');
  if(edits.reduce((sum,edit)=>sum+Number(edit?.amount_pct||0),0)>15)throw Error('Combined waist width reduction cannot exceed 15%.');
  const positions=sourcePositions.slice(),masks=buildRegionMasks(positions,data,maskSpec),waist=maskSpec.regions.waist,reports=[];
  for(const edit of edits){
    if(edit.region!=='waist'||edit.operation!=='reduce_width')throw Error('Only mapped waist-width reduction is supported on this base.');
    const amount=Number(edit.amount_pct);
    if(!Number.isFinite(amount)||amount<=0||amount>waist.max_amount_percent)throw Error(`Waist amount must be greater than 0 and at most ${waist.max_amount_percent}%.`);
    if(!Array.isArray(edit.protected_regions)||edit.protected_regions.some(region=>!['hips','glutes'].includes(region)))throw Error('Waist edits can only protect mapped hips and glutes.');
    const [lower,upper]=waist.vertical_bounds,[fullLow,fullHigh]=waist.full_influence_bounds;
    let changed=0;
    for(const index of masks.waist){
      const offset=index*3,y=positions[offset+1],x=positions[offset];let weight=1;
      if(y<fullLow){const t=(y-lower)/(fullLow-lower);weight=t*t*(3-2*t);}
      else if(y>fullHigh){const t=(upper-y)/(upper-fullHigh);weight=t*t*(3-2*t);}
      positions[offset]-=x*(amount/100)*weight;
      if(positions[offset]!==sourcePositions[offset])changed++;
    }
    const protectedMaxDelta={};
    for(const region of edit.protected_regions){
      let maximum=0;for(const index of masks[region]){const offset=index*3;maximum=Math.max(maximum,Math.hypot(positions[offset]-sourcePositions[offset],positions[offset+1]-sourcePositions[offset+1],positions[offset+2]-sourcePositions[offset+2]));}
      protectedMaxDelta[region]=maximum;
      if(maximum!==0)throw Error(`Protected ${region} vertices moved.`);
    }
    reports.push({region:'waist',operation:edit.operation,amount_pct:amount,mask_version:maskSpec.schema_version,changed_vertices:changed,protected_max_delta:protectedMaxDelta});
  }
  return {positions,reports};
}
