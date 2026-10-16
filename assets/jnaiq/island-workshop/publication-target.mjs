export function replacementDestination(destinations,activeId,name){
  const normalized=String(name||'').trim().toLocaleLowerCase();
  if(!normalized)return null;
  const matches=(destinations||[]).filter(item=>item?.id!==activeId&&String(item?.name||'').trim().toLocaleLowerCase()===normalized);
  if(matches.length>1)throw Error(`More than one existing JNAIQ world is named “${name}”. Rename this draft so the destination is unambiguous.`);
  return matches[0]?.id||null;
}
