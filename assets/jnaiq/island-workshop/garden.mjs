import {heightAt,insideStructure} from './terrain.mjs';
import {featureDistance} from './landscape-features.mjs';
import crops from './garden-crops.json' with {type:'json'};
export const BED_WIDTH=2.4,BED_DEPTH=1.6;
export const CROPS=Object.freeze(crops);
export function validateGarden(garden,size=160,furniture={}){
  if(garden===undefined)return;
  if(!garden||Array.isArray(garden)||Object.keys(garden).some(k=>!['beds','pace'].includes(k))||!Array.isArray(garden.beds)||garden.beds.length>32||!Number.isFinite(garden.pace)||garden.pace<1||garden.pace>24)throw Error('Use up to 32 beds and a garden pace from 1 to 24.');
  const ids=new Set(Object.keys(furniture));
  for(const b of garden.beds){
    if(!b||Object.keys(b).sort().join(',')!=='id,name,rotation,x,z'||!/^garden_[a-zA-Z0-9_-]{1,60}$/.test(b.id)||ids.has(b.id)||typeof b.name!=='string'||b.name.trim().length<1||b.name.length>60||![b.x,b.z,b.rotation].every(Number.isFinite)||Math.abs(b.rotation)>Math.PI*2||Math.abs(b.x)+1.5>size/2||Math.abs(b.z)+1.5>size/2)throw Error('Invalid garden bed.');
    ids.add(b.id);
  }
}
export function bedPoint(b,x,z){const c=Math.cos(b.rotation),s=Math.sin(b.rotation);return {x:b.x+c*x+s*z,z:b.z-s*x+c*z};}
export function bedDistance(b,x,z){const c=Math.cos(b.rotation),s=Math.sin(b.rotation),dx=x-b.x,dz=z-b.z;return Math.hypot(Math.max(0,Math.abs(c*dx-s*dz)-BED_WIDTH/2),Math.max(0,Math.abs(s*dx+c*dz)-BED_DEPTH/2));}
export function placeBed(world,b){
  const next=structuredClone(world);next.garden??={beds:[],pace:12};
  next.garden.beds.push(b);validateGarden(next.garden,world.size,world.furniture);
  const heights=[];
  for(let i=0;i<=6;i++)for(let j=0;j<=4;j++){
    const p=bedPoint(b,(i/6-.5)*BED_WIDTH,(j/4-.5)*BED_DEPTH);heights.push(heightAt(world,p.x,p.z));
    if(world.structures?.some(s=>insideStructure(s,p.x,p.z,.4)))throw Error('Place the bed outside the building footprint.');
    if(world.features?.some(f=>featureDistance(f,p.x,p.z)<(f.kind==='pond'?0.05:f.width/2)+.35))throw Error('Place the bed clear of paths and water.');
    if(world.garden?.beds.some(old=>bedDistance(old,p.x,p.z)<.4))throw Error('Leave a little space between beds.');
    if(Object.values(world.furniture||{}).some(o=>Math.hypot(p.x-o.position_m[0],p.z+o.position_m[1])<o.size_m/2+.3))throw Error('Place the bed clear of furniture.');
    if(world.columns?.some(c=>Math.hypot(p.x-c.x,p.z-c.z)<(c.length||0)/2+c.radius+.4))throw Error('Place the bed clear of columns.');
    if(world.stepRoutes?.some(r=>featureDistance({points:[r.a,r.b]},p.x,p.z)<r.width/2+.3))throw Error('Place the bed clear of steps.');
  }
  if(Math.min(...heights)<.15)throw Error('Choose dry land for this bed.');
  if(Math.max(...heights)-Math.min(...heights)>.55)throw Error('This patch is too steep for a bed. Flatten it or choose a gentler patch.');
  next.objects=next.objects.filter(o=>bedDistance(b,o.x,o.z)>Math.max(.45,o.scale*.9));
  return next;
}
