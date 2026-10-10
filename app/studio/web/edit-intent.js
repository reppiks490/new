const REGION_ALIASES={
  waist:['waist','midsection','middle'],
  glutes:['glutes?','butt(?:ocks?)?','rear','backside'],
  hips:['hips?'],
  breasts:['breasts?','bust'],
};

const OPERATION_PATTERNS=[
  {operation:'reduce_width',pattern:/\b(?:slim(?:mer)?|narrow(?:er)?|trim|reduce\s+(?:the\s+)?width|decrease\s+(?:the\s+)?width|reduce\s+(?:the\s+)?[a-z ]{0,20}\bwidth)\b/g},
  {operation:'increase_width',pattern:/\b(?:widen|wider|increase\s+(?:the\s+)?width)\b/g},
  {operation:'reduce_size',pattern:/\b(?:reduce|decrease|shrink|smaller|less|flatten)\b/g},
  {operation:'increase_size',pattern:/\b(?:increase|enlarge|larger|bigger|fuller|rounder)\b/g},
  {operation:'set_size',pattern:/\b(?:set|make)\b/g},
];
const AMOUNT_PATTERN=/(?<![\w.])([+-]?\d+(?:\.\d+)?)\s*(%|percent|millimeters?|mm|centimeters?|cm|inches?|in)(?![a-z])/gi;

function regionsIn(text){
  const found=[];
  for(const [region,aliases] of Object.entries(REGION_ALIASES)){
    if(aliases.some(alias=>new RegExp(`\\b${alias}\\b`,'i').test(text)))found.push(region);
  }
  return found;
}

function amountsIn(text){
  const amounts=[];
  for(const match of text.matchAll(AMOUNT_PATTERN)){
    const rawUnit=match[2].toLowerCase();
    const amount=Number(match[1]);
    const amountUnit=rawUnit==='%'||rawUnit==='percent'?'percent':
      ['mm','millimeter','millimeters'].includes(rawUnit)?'mm':
      ['in','inch','inches'].includes(rawUnit)?'in':'cm';
    amounts.push({amount,amountUnit});
  }
  return amounts;
}

function operationsIn(text){
  const found=[];
  for(const {operation,pattern} of OPERATION_PATTERNS){
    if(pattern.test(text))found.push(operation);
    pattern.lastIndex=0;
  }
  if(found.includes('reduce_width'))return ['reduce_width'];
  if(found.includes('increase_width'))return ['increase_width'];
  // “make the waist 12% narrower” is a reduction, while “make it larger” is an increase.
  if(found.includes('set_size')){
    if(/\b(?:smaller|narrower|slimmer|thinner|reduced?)\b/.test(text))return ['reduce_size'];
    if(/\b(?:larger|wider|bigger|fuller)\b/.test(text))return ['increase_size'];
    if(found.length===1)return ['set_size'];
  }
  return found;
}

export function parseEditIntent(prompt){
  if(typeof prompt!=='string'||prompt.length>2000)throw Error('Keep the edit prompt under 2,000 characters.');
  const normalized=prompt.toLowerCase().replace(/[’']/g,' ').replace(/\s+/g,' ').trim();
  if(!normalized)throw Error('Enter an edit instruction.');

  const protectedClause=normalized.match(/\bwithout\s+(?:(?:reducing|changing|affecting|altering|shrinking|decreasing|increasing)\s+)?(.+)$/);
  const protected_regions=protectedClause?regionsIn(protectedClause[1]):[];
  const targetText=protectedClause?normalized.slice(0,protectedClause.index).trim():normalized;
  let target_regions=regionsIn(targetText);
  const mentionsRecognizedRegion=regionsIn(normalized).length>0;

  if(!target_regions.length){
    const result={status:'unsupported',operation:null,target_regions:[],protected_regions,amount:null,amount_unit:null,requires_amount_review:false,reason:mentionsRecognizedRegion?'The instruction only names protected regions; specify a region to edit.':'I could not identify a supported body region.'};
    return result;
  }
  target_regions=target_regions.filter(region=>!protected_regions.includes(region));
  if(!target_regions.length){
    return {status:'unsupported',operation:null,target_regions:[],protected_regions,amount:null,amount_unit:null,requires_amount_review:false,reason:'The requested target is also protected; resolve this constraint conflict.'};
  }

  const operations=operationsIn(targetText);
  if(operations.length>1){
    return {status:'unsupported',operation:null,target_regions,protected_regions,amount:null,amount_unit:null,requires_amount_review:false,reason:'The instruction contains conflicting or multiple operations. Submit one operation at a time.'};
  }
  const operation=operations[0]||null;
  const amounts=amountsIn(targetText);
  if(amounts.length>1&&(amounts.some(x=>x.amount!==amounts[0].amount)||amounts.some(x=>x.amountUnit!==amounts[0].amountUnit))){
    return {status:'unsupported',operation,target_regions,protected_regions,amount:null,amount_unit:null,requires_amount_review:false,reason:'The instruction contains conflicting amount expressions.'};
  }
  const amount=amounts[0]?.amount??null;
  const amount_unit=amounts[0]?.amountUnit??null;
  if(amount!==null&&amount<=0){
    return {status:'unsupported',operation,target_regions,protected_regions,amount,amount_unit,requires_amount_review:false,reason:'Use a positive amount; the operation describes the direction of change.'};
  }
  const reason=!operation?'Specify an operation describing how the target region should change.':amount===null?'Choose the amount before applying this edit.':null;
  return {status:reason?'needs_review':'ready',operation,target_regions,protected_regions,amount,amount_unit,requires_amount_review:amount===null,reason};
}
