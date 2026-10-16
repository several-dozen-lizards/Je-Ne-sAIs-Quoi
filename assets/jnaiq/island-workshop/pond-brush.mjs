import {N} from './terrain.mjs?caves=retired';
import {inPond} from './pond-shape.mjs';
import {addPond} from './ponds.mjs?caves=retired';

export function paintPond(world,stroke,radius,depth){
  if(!stroke.length||!Number.isFinite(radius)||radius<world.size/N*3||radius>50)throw Error('Use a pond brush at least three terrain cells wide, up to 50 metres.');
  if(stroke.length>256||stroke.some(p=>!Number.isFinite(p.x)||!Number.isFinite(p.z)))throw Error('Finish this pond stroke before painting farther.');
  const step=world.size/N,mask=new Uint8Array(N*N);
  const distance=(x,z)=>{
    let d=Math.hypot(x-stroke[0].x,z-stroke[0].z);
    for(let i=1;i<stroke.length;i++){
      const a=stroke[i-1],b=stroke[i],dx=b.x-a.x,dz=b.z-a.z,t=Math.max(0,Math.min(1,((x-a.x)*dx+(z-a.z)*dz)/(dx*dx+dz*dz||1)));
      d=Math.min(d,Math.hypot(x-a.x-dx*t,z-a.z-dz*t));
    }return d;
  };
  const point=(i,j)=>({x:(i/N-.5)*world.size,z:(j/N-.5)*world.size});
  for(let j=0;j<N;j++)for(let i=0;i<N;i++){const p=point(i+.5,j+.5);if(distance(p.x,p.z)<=radius)mask[j*N+i]=1;}
  // Overlapping strokes extend existing ponds rather than replacing their water.
  const pending=(world.features||[]).filter(f=>f.kind==='pond');let changed=true;
  while(changed){changed=false;for(let f=pending.length-1;f>=0;f--){
    const cells=[];let touches=false;
    for(let j=0;j<N;j++)for(let i=0;i<N;i++){const p=point(i+.5,j+.5);if(inPond(pending[f].points,p.x,p.z)){cells.push(j*N+i);if(mask[j*N+i])touches=true;}}
    if(touches){for(const k of cells)mask[k]=1;pending.splice(f,1);changed=true;}
  }}
  const edges=new Map(),key=(i,j)=>j*(N+1)+i;
  const edge=(a,b)=>{if(!edges.has(a))edges.set(a,[]);edges.get(a).push(b);};
  for(let j=0;j<N;j++)for(let i=0;i<N;i++)if(mask[j*N+i]){
    if(i<3||j<3||i>=N-3||j>=N-3)throw Error('Keep the pond brush away from the island edge.');
    if(!mask[(j-1)*N+i])edge(key(i,j),key(i+1,j));
    if(!mask[j*N+i+1])edge(key(i+1,j),key(i+1,j+1));
    if(!mask[(j+1)*N+i])edge(key(i+1,j+1),key(i,j+1));
    if(!mask[j*N+i-1])edge(key(i,j+1),key(i,j));
  }
  const loops=[];
  while(edges.size){const start=edges.keys().next().value,loop=[];let k=start;
    do{loop.push(point(k%(N+1),Math.floor(k/(N+1))));const next=edges.get(k);if(!next?.length)throw Error('Paint a wider connection between pond areas.');const a=k;k=next.pop();if(!next.length)edges.delete(a);}while(k!==start);
    loops.push(loop.filter((p,i)=>{const a=loop[(i+loop.length-1)%loop.length],b=loop[(i+1)%loop.length];return (p.x-a.x)*(b.z-p.z)!==(p.z-a.z)*(b.x-p.x);}));
  }
  const area=loop=>Math.abs(loop.reduce((sum,p,i)=>{const q=loop[(i+1)%loop.length];return sum+p.x*q.z-q.x*p.z;},0));
  loops.sort((a,b)=>area(b)-area(a));const outline=loops[0];
  if(!outline||outline.length>256)throw Error('Finish a smaller pond stroke.');
  const next=structuredClone(world);addPond(next,outline,depth,{painted:true});
  // Unpainted islands inside a looping stroke keep their original ground.
  for(let j=1;j<N;j++)for(let i=1;i<N;i++)if(![mask[j*N+i],mask[j*N+i-1],mask[(j-1)*N+i],mask[(j-1)*N+i-1]].some(Boolean))next.heights[j*(N+1)+i]=world.heights[j*(N+1)+i];
  return next;
}
