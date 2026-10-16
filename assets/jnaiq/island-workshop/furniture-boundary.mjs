export const furnitureWorldRange=size=>Number(size)*2;

export function furniturePositionInside(position,limit){
  return Array.isArray(position)&&position.length===2&&position.every(v=>Number.isFinite(v)&&Math.abs(v)<=limit);
}

export function boundedFurniturePosition(position,limit){
  return position.map(v=>Math.max(-limit,Math.min(limit,v)));
}

export function removeFurnitureOutsideWorld(objects={},limit){
  const removed=new Set(Object.entries(objects).filter(([,o])=>!furniturePositionInside(o?.position_m,limit)).map(([id])=>id));
  let changed=true;
  while(changed){
    changed=false;
    for(const [id,o] of Object.entries(objects))if(!removed.has(id)&&removed.has(o.support_oid)){removed.add(id);changed=true;}
  }
  return {objects:Object.fromEntries(Object.entries(objects).filter(([id])=>!removed.has(id))),removed:[...removed]};
}
