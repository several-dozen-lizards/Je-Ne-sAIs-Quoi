import {N,heightAt,clamp} from './terrain.mjs?caves=retired';
import {inPond,pondEdge,validatePond} from './pond-shape.mjs';
import {pondSpillLevel,settlePonds} from './pond-level.mjs';
import {placementClearance,applyClearance} from './placement-clearance.mjs';
export function addPond(w,outline,depth,{painted=false}={}){
  if(!Number.isFinite(depth)||depth<.5||depth>6)throw Error('Choose a pond depth from 0.5 to 6 metres.');
  validatePond(outline);
  const step=w.size/N,bounds={minX:Math.min(...outline.map(p=>p.x)),maxX:Math.max(...outline.map(p=>p.x)),minZ:Math.min(...outline.map(p=>p.z)),maxZ:Math.max(...outline.map(p=>p.z))};
  if(Math.max(bounds.maxX-bounds.minX,bounds.maxZ-bounds.minZ)>100)throw Error('Keep pond outlines within 100 metres.');
  const cells=[],shore=pondSpillLevel(w,outline);
  for(let j=1;j<N;j++)for(let i=1;i<N;i++){
    const x=(i/N-.5)*w.size,z=(j/N-.5)*w.size,edge=pondEdge(outline,x,z),inside=inPond(outline,x,z);
    if(!inside&&edge>step*2)continue;
    if(Math.abs(x)>w.size/2-step*3||Math.abs(z)>w.size/2-step*3||(!painted||!inside)&&heightAt(w,x,z)<.5)throw Error('Keep the pond and its banks on dry land.');
    if(inside)cells.push({k:j*(N+1)+i,edge});
  }
  if(cells.length<9||!Number.isFinite(shore))throw Error('Make the pond wider so there is room for a basin.');
  const level=shore,points=outline.map(p=>({x:p.x,z:p.z,y:level}));
  // Preserve the terrain cells touching the outline so carving cannot lower
  // the bank through triangle interpolation. Ease into the basin behind them.
  const carved=cells.map(({k,edge})=>{
    const blend=clamp((edge-step*Math.SQRT2)/(step*2),0,1);
    return {k,height:Math.max(-12,Math.min(w.heights[k],w.heights[k]+(level-depth-w.heights[k])*blend))};
  });
  if(!carved.some(({height})=>height<level-.1))throw Error('Make the pond wider so its banks leave room for water.');
  const f={kind:'pond',width:1,points},clearance=placementClearance(w,f,step*2);
  if(clearance.features.length>=12)throw Error('Remove a landscape feature before adding another.');
  for(const {k,height} of carved)w.heights[k]=height;
  applyClearance(w,clearance);w.features??=[];w.features.push(f);
  w.objects=w.objects.filter(o=>!inPond(points,o.x,o.z)&&pondEdge(points,o.x,o.z)>step);
  settlePonds(w);
  return f;
}
