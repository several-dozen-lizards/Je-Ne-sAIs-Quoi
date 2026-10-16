import {heightAt} from './terrain.mjs?caves=retired';

// Compatibility only: old files remain readable after the cave tools retire.
export const RETIRED_SCENERY=['cave_tunnel','cave_grotto','stalagmite','stalactite'];
export function removeRetiredCaves(w){
  if(!w||!Array.isArray(w.objects))return w;
  w.objects=w.objects.filter(o=>!RETIRED_SCENERY.includes(o?.kind));
  for(const o of w.objects)if(o)delete o.anchorId;
  for(const b of Array.isArray(w.structures)?w.structures:[]){
    if(b?.supportId&&Array.isArray(w.heights)&&w.heights.length===129**2&&Number.isFinite(b.x)&&Number.isFinite(b.z))b.y=heightAt(w,b.x,b.z)+.12;
    if(b){delete b.supportId;delete b.supportSurface;}
  }
  return w;
}
