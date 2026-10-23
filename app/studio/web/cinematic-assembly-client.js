// Browser-only, private cinematic master-assembly client.
//
// This module accepts the studio's existing authenticated api(path, options)
// function. It never reads or writes tokens, prompts, media, URL query secrets,
// browser storage, or cross-origin asset links. DOM integration belongs to the
// cinematic editor owner; keep raw backend job objects out of rendered HTML.
const ID=/^[a-f0-9]{32}$/;
const SHA=/^[a-f0-9]{64}$/;
const STATES=new Set(['queued','running','succeeded','failed','cancelled']);
const ACTIVE=new Set(['queued','running']);
const TERMINAL=new Set(['succeeded','failed','cancelled']);

const STATUS_LABELS=Object.freeze({
  queued:'Waiting in queue',
  running:'Assembling master',
  succeeded:'Master ready',
  failed:'Assembly failed',
  cancelled:'Cancelled',
});

function validId(value,kind){
  if(typeof value!=='string' || !ID.test(value)){
    throw new TypeError('Invalid '+kind+' ID');
  }
  return value;
}

function validInteger(value,kind,min,max){
  if(!Number.isSafeInteger(value) || value<min || value>max){
    throw new RangeError('Invalid '+kind);
  }
  return value;
}

function abortError(){
  const error=new Error('Assembly polling stopped');
  error.name='AbortError';
  return error;
}
function ensureNotAborted(signal){
  if(signal?.aborted)throw abortError();
}
function defaultSleep(ms,signal){
  return new Promise((resolve,reject)=>{
    if(signal?.aborted){reject(abortError());return;}
    const done=()=>{
      signal?.removeEventListener?.('abort',onAbort);
      resolve();
    };
    const onAbort=()=>{
      clearTimeout(timer);
      signal?.removeEventListener?.('abort',onAbort);
      reject(abortError());
    };
    const timer=setTimeout(done,ms);
    signal?.addEventListener?.('abort',onAbort,{once:true});
  });
}

export function isTerminalAssemblyStatus(status){
  return TERMINAL.has(status);
}

export function normalizeAssemblyJob(raw,{projectId,jobId}={}){
  if(raw===null || typeof raw!=='object' || Array.isArray(raw)){
    throw new TypeError('Invalid master job response');
  }
  const id=validId(raw.id,'job');
  const project=validId(raw.project_id,'project');
  if(projectId!==undefined && project!==validId(projectId,'project')){
    throw new Error('Master job belongs to another project');
  }
  if(jobId!==undefined && id!==validId(jobId,'job')){
    throw new Error('Unexpected master job identity');
  }
  if(!STATES.has(raw.status))throw new Error('Unknown master assembly status');
  const revision=validInteger(raw.project_revision,'project revision',1,Number.MAX_SAFE_INTEGER);
  // A null running progress is UNKNOWN, not 0%. Never coerce Number(null).
  const progress=typeof raw.progress==='number' && Number.isFinite(raw.progress)
    && raw.progress>=0 && raw.progress<=100 ? raw.progress : null;

  const assetId=raw.asset_id;
  const assetUrl=raw.asset_url;
  const verified=raw.status==='succeeded' && raw.probe_metadata_verified===true
    && typeof assetId==='string' && ID.test(assetId)
    && typeof raw.sha256==='string' && SHA.test(raw.sha256)
    && assetUrl==='/api/video/assets/'+assetId+'.mp4';

  // Whitelist neutral metadata instead of passing raw stage/error/prompt fields
  // to the UI, even if a backend later adds new sensitive record attributes.
  return Object.freeze({
    id,projectId:project,revision,status:raw.status,progress,
    assetUrl:verified ? assetUrl : null,
    verified,
  });
}

export function assemblyStatusSummary(job){
  if(!job || !STATES.has(job.status))throw new TypeError('Invalid master job');
  const ready=job.status==='succeeded' && job.verified===true && Boolean(job.assetUrl);
  const progressLabel=job.status==='running' && typeof job.progress==='number'
    ? String(Math.floor(job.progress))+'%' : null;
  return Object.freeze({
    label:'Film master',
    status:job.status==='succeeded' && !ready
      ? 'Master verification unavailable' : STATUS_LABELS[job.status],
    progressLabel,
    terminal:TERMINAL.has(job.status),
    ready,
    assetUrl:ready ? job.assetUrl : null,
  });
}

export function createCinematicAssemblyClient({api,sleep=defaultSleep}={}){
  if(typeof api!=='function')throw new TypeError('Provide the authenticated studio API');
  if(typeof sleep!=='function')throw new TypeError('Invalid polling sleep handler');

  const base=projectId=>'/projects/'+validId(projectId,'project')+'/assembly-jobs';

  async function submit(projectId,revision){
    const path=base(projectId);
    validInteger(revision,'project revision',1,Number.MAX_SAFE_INTEGER);
    const result=await api(path,{
      method:'POST',
      body:JSON.stringify({expected_revision:revision}),
    });
    return normalizeAssemblyJob(result,{projectId});
  }

  async function get(projectId,jobId){
    const path=base(projectId)+'/'+validId(jobId,'job');
    return normalizeAssemblyJob(await api(path),{projectId,jobId});
  }

  async function cancel(projectId,jobId){
    const path=base(projectId)+'/'+validId(jobId,'job')+'/cancel';
    const result=normalizeAssemblyJob(await api(path,{method:'POST'}),{projectId,jobId});
    if(result.status!=='cancelled'){
      throw new Error('Server did not confirm queued-job cancellation');
    }
    return result;
  }

  async function list(projectId,{limit=50,offset=0}={}){
    const path=base(projectId);
    validInteger(limit,'page size',1,200);
    validInteger(offset,'page offset',0,Number.MAX_SAFE_INTEGER);
    const raw=await api(path+'?limit='+limit+'&offset='+offset);
    if(!raw || typeof raw!=='object' || !Array.isArray(raw.jobs)
      || !Number.isSafeInteger(raw.total) || raw.total<0
      || raw.offset!==offset || raw.limit!==limit
      || typeof raw.has_more!=='boolean' || raw.jobs.length>limit
      || offset+raw.jobs.length>raw.total
      || (raw.has_more && (!raw.jobs.length || offset+raw.jobs.length>=raw.total))
      || (!raw.has_more && offset+raw.jobs.length<raw.total)){
      throw new Error('Invalid assembly pagination response');
    }
    return Object.freeze({
      jobs:raw.jobs.map(row=>normalizeAssemblyJob(row,{projectId})),
      total:raw.total,offset,limit,hasMore:raw.has_more,
    });
  }

  async function findActive(projectId,{pageSize=200,maxPasses=3,signal}={}){
    validInteger(pageSize,'page size',1,200);
    validInteger(maxPasses,'reconnect passes',1,10);
    // Updated timestamps can reorder offset-paginated results mid-scan.
    // A duplicate identity or changing total signals a non-snapshot page set.
    // Never report "no active job" on a detected unstable scan.
    for(let pass=0;pass<maxPasses;pass++){
      let offset=0,expectedTotal=null,unstable=false;
      const seen=new Set();
      while(true){
        ensureNotAborted(signal);
        const page=await list(projectId,{limit:pageSize,offset});
        ensureNotAborted(signal);
        if(expectedTotal!==null && page.total!==expectedTotal){
          unstable=true;
          break;
        }
        expectedTotal=page.total;
        for(const item of page.jobs){
          if(seen.has(item.id)){unstable=true;break;}
          seen.add(item.id);
        }
        if(unstable)break;
        const active=page.jobs.find(item=>ACTIVE.has(item.status));
        if(active)return active;
        if(!page.hasMore)return null;
        offset+=page.jobs.length;
      }
    }
    // Fail closed: this fallback is not an atomic queue-state snapshot.
    throw new Error('Assembly history changed during reconnect; retry when stable');
  }

  async function waitForTerminal(projectId,jobId,{
    signal,onUpdate,intervalMs=2000,
  }={}){
    validInteger(intervalMs,'poll interval',250,60000);
    if(onUpdate!==undefined && typeof onUpdate!=='function'){
      throw new TypeError('Invalid status callback');
    }
    while(true){
      ensureNotAborted(signal);
      const current=await get(projectId,jobId);
      ensureNotAborted(signal);
      onUpdate?.(current);
      ensureNotAborted(signal);
      if(isTerminalAssemblyStatus(current.status))return current;
      await sleep(intervalMs,signal);
      ensureNotAborted(signal);
    }
  }

  return Object.freeze({submit,get,cancel,list,findActive,waitForTerminal});
}
